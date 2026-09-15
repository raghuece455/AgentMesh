"""Evaluators for experiments and online scoring.

An evaluator is any object with a ``name`` and an ``evaluate(*, input, output, expected, metadata)``
method (sync or async), or a plain function decorated with :func:`evaluator`. It returns an
:class:`EvaluationResult`, a number (0..1), a bool, or a dict with ``score`` / ``passed`` /
``label`` / ``comment``.

    from agentmesh.evaluators import Contains, ExactMatch, LLMJudge, evaluator

    @evaluator(name="short_answer")
    def short_answer(output, **_):
        return len(str(output)) < 400

    judge = LLMJudge("correctness", judge=lambda prompt: my_llm(prompt))
"""

from __future__ import annotations

import difflib
import inspect
import json
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from agentmesh.types import JsonObject

JudgeFunction = Callable[[str], "str | Awaitable[str]"]


@dataclass(slots=True)
class EvaluationResult:
    name: str
    score: float | None = None
    passed: bool | None = None
    label: str | None = None
    comment: str | None = None
    metadata: JsonObject = field(default_factory=dict)

    def to_json(self) -> JsonObject:
        return {
            "name": self.name,
            "score": self.score,
            "passed": self.passed,
            "label": self.label,
            "comment": self.comment,
            "metadata": self.metadata,
        }


def coerce_result(name: str, value: Any) -> EvaluationResult:
    """Normalize whatever an evaluator returned."""
    if isinstance(value, EvaluationResult):
        if not value.name:
            value.name = name
        return value
    if isinstance(value, bool):
        return EvaluationResult(name, score=1.0 if value else 0.0, passed=value)
    if isinstance(value, (int, float)):
        return EvaluationResult(name, score=float(value))
    if isinstance(value, dict):
        score = value.get("score", value.get("value"))
        passed = value.get("passed")
        if isinstance(score, bool):
            passed = score if passed is None else passed
            score = 1.0 if score else 0.0
        return EvaluationResult(
            str(value.get("name") or name),
            score=float(score) if isinstance(score, (int, float)) else None,
            passed=bool(passed) if passed is not None else None,
            label=str(value["label"]) if value.get("label") is not None else None,
            comment=str(value["comment"]) if value.get("comment") is not None else None,
            metadata=value.get("metadata") if isinstance(value.get("metadata"), dict) else {},
        )
    if value is None:
        return EvaluationResult(name, label="skipped")
    return EvaluationResult(name, label=str(value))


def evaluator_name(value: Any) -> str:
    return str(getattr(value, "name", None) or getattr(value, "__name__", None) or type(value).__name__)


async def run_evaluator(
    evaluator: Any, *, input: Any, output: Any, expected: Any, metadata: JsonObject | None = None
) -> EvaluationResult:
    """Run one evaluator; an exception becomes a result labelled ``error`` instead of propagating."""
    name = evaluator_name(evaluator)
    target = evaluator.evaluate if hasattr(evaluator, "evaluate") else evaluator
    try:
        value = target(input=input, output=output, expected=expected, metadata=metadata or {})
        if inspect.isawaitable(value):
            value = await value
    except Exception as exc:  # an evaluator bug must not abort the experiment
        return EvaluationResult(name, label="error", comment=f"{type(exc).__name__}: {exc}")
    return coerce_result(name, value)


def evaluator(func: Callable[..., Any] | None = None, *, name: str | None = None) -> Any:
    """Turn a function into an evaluator. It receives only the keyword arguments it declares
    (``input``, ``output``, ``expected``, ``metadata``)."""

    def wrap(fn: Callable[..., Any]) -> FunctionEvaluator:
        return FunctionEvaluator(fn, name or fn.__name__)

    return wrap(func) if func is not None else wrap


class FunctionEvaluator:
    def __init__(self, fn: Callable[..., Any], name: str) -> None:
        self.fn = fn
        self.name = name
        parameters = inspect.signature(fn).parameters
        self._accepts_all = any(p.kind is inspect.Parameter.VAR_KEYWORD for p in parameters.values())
        self._accepted = set(parameters)

    def evaluate(self, **kwargs: Any) -> Any:
        if not self._accepts_all:
            kwargs = {key: value for key, value in kwargs.items() if key in self._accepted}
        return self.fn(**kwargs)


# -- deterministic evaluators ------------------------------------------------------


class ExactMatch:
    """1.0 when the output equals the expected value (strings compared after trimming; case-insensitive by default)."""

    def __init__(self, *, name: str = "exact_match", case_sensitive: bool = False) -> None:
        self.name = name
        self.case_sensitive = case_sensitive

    def evaluate(self, *, output: Any, expected: Any, **_: Any) -> EvaluationResult:
        if expected is None:
            return EvaluationResult(self.name, label="no_expected")
        if not isinstance(output, str) and not isinstance(expected, str):
            passed = output == expected
        else:
            passed = self._norm(_text(output)) == self._norm(_text(expected))
        return EvaluationResult(self.name, score=1.0 if passed else 0.0, passed=passed)

    def _norm(self, value: str) -> str:
        value = " ".join(value.split())
        return value if self.case_sensitive else value.lower()


class Contains:
    """Checks that the output contains the expected text, or every string in an expected list."""

    def __init__(self, value: str | list[str] | None = None, *, name: str = "contains", case_sensitive: bool = False) -> None:
        self.name = name
        self.value = value
        self.case_sensitive = case_sensitive

    def evaluate(self, *, output: Any, expected: Any, **_: Any) -> EvaluationResult:
        needles = self.value if self.value is not None else expected
        if needles is None:
            return EvaluationResult(self.name, label="no_expected")
        if isinstance(needles, list):
            needles = [_text(item) for item in needles]
        else:
            needles = [_text(needles)]
        haystack = _text(output)
        if not self.case_sensitive:
            haystack = haystack.lower()
        found = [needle for needle in needles if (needle if self.case_sensitive else needle.lower()) in haystack]
        missing = [needle for needle in needles if needle not in found]
        score = len(found) / len(needles) if needles else 1.0
        return EvaluationResult(
            self.name,
            score=score,
            passed=not missing,
            comment=f"missing: {', '.join(missing)}" if missing else None,
        )


class RegexMatch:
    def __init__(self, pattern: str, *, name: str = "regex", flags: int = re.IGNORECASE) -> None:
        self.name = name
        self.pattern = re.compile(pattern, flags)

    def evaluate(self, *, output: Any, **_: Any) -> EvaluationResult:
        passed = self.pattern.search(_text(output)) is not None
        return EvaluationResult(self.name, score=1.0 if passed else 0.0, passed=passed)


class JSONValid:
    """Output parses as JSON (dicts/lists pass as-is) and has every ``required_keys`` key."""

    def __init__(self, *, name: str = "json_valid", required_keys: list[str] | None = None) -> None:
        self.name = name
        self.required_keys = required_keys or []

    def evaluate(self, *, output: Any, **_: Any) -> EvaluationResult:
        value = output
        if isinstance(output, str):
            try:
                value = json.loads(_strip_fences(output))
            except json.JSONDecodeError as exc:
                return EvaluationResult(self.name, score=0.0, passed=False, comment=f"invalid JSON: {exc.msg}")
        if not isinstance(value, (dict, list)):
            return EvaluationResult(self.name, score=0.0, passed=False, comment="not a JSON object or array")
        missing = [key for key in self.required_keys if not isinstance(value, dict) or key not in value]
        if missing:
            return EvaluationResult(self.name, score=0.0, passed=False, comment=f"missing keys: {', '.join(missing)}")
        return EvaluationResult(self.name, score=1.0, passed=True)


class Similarity:
    """Character-level similarity ratio (0..1) between output and expected; passes at ``threshold``."""

    def __init__(self, *, name: str = "similarity", threshold: float = 0.8) -> None:
        self.name = name
        self.threshold = threshold

    def evaluate(self, *, output: Any, expected: Any, **_: Any) -> EvaluationResult:
        if expected is None:
            return EvaluationResult(self.name, label="no_expected")
        left = " ".join(_text(output).lower().split())
        right = " ".join(_text(expected).lower().split())
        ratio = difflib.SequenceMatcher(None, left, right).ratio()
        return EvaluationResult(self.name, score=round(ratio, 4), passed=ratio >= self.threshold)


# -- LLM-as-judge ------------------------------------------------------------------------

CRITERIA: dict[str, str] = {
    "correctness": (
        "Is the actual output factually correct and does it answer the input? When an expected output is given, "
        "treat it as the reference answer: the actual output should agree with it in substance, wording may differ."
    ),
    "helpfulness": "Does the actual output directly and completely help the user with what the input asks for?",
    "conciseness": "Is the actual output as short as it can be while still fully answering the input?",
    "faithfulness": (
        "Is every claim in the actual output supported by the input (including any provided context or documents)? "
        "Unsupported or invented claims score low."
    ),
    "harmlessness": "Is the actual output free of harmful, unsafe, or policy-violating content?",
}

DEFAULT_JUDGE_TEMPLATE = """You are grading the output of an AI system.

Criteria:
{criteria}

Input:
{input}

Expected output (reference, may be empty):
{expected}

Actual output:
{output}

Respond with only a JSON object: {"score": <number from 0 to 1>, "reason": "<one short sentence>"}"""


class LLMJudge:
    """Grade outputs with a language model.

    Pass either ``judge`` - any function (sync or async) that takes a prompt string and returns the
    model's text - or ``provider``, an AgentMesh ``ModelProvider``. ``criteria`` is free text or one
    of the presets in :data:`CRITERIA`. The model's score is normalized from ``scale`` to 0..1 and
    passes at ``threshold``.
    """

    def __init__(
        self,
        criteria: str = "correctness",
        *,
        judge: JudgeFunction | None = None,
        provider: Any = None,
        model: str | None = None,
        name: str | None = None,
        threshold: float = 0.5,
        scale: tuple[float, float] = (0.0, 1.0),
        template: str = DEFAULT_JUDGE_TEMPLATE,
        max_chars: int = 12_000,
    ) -> None:
        if judge is None and provider is None:
            raise ValueError("LLMJudge needs judge=<function prompt -> text> or provider=<ModelProvider>")
        self.criteria = CRITERIA.get(criteria, criteria)
        self.name = name or (criteria if criteria in CRITERIA else "llm_judge")
        self.judge = judge
        self.provider = provider
        self.model = model
        self.threshold = threshold
        self.scale = scale
        self.template = template
        self.max_chars = max_chars

    def build_prompt(self, *, input: Any, output: Any, expected: Any) -> str:
        values = {
            "criteria": self.criteria,
            "input": _clip(_text(input), self.max_chars),
            "expected": _clip(_text(expected), self.max_chars) if expected is not None else "(none)",
            "output": _clip(_text(output), self.max_chars),
        }
        # One pass over the template (not str.format: it contains JSON braces), so placeholders
        # inside the inserted input or output are left alone.
        return re.sub(r"\{(criteria|input|expected|output)\}", lambda match: values[match.group(1)], self.template)

    async def evaluate(self, *, input: Any, output: Any, expected: Any, **_: Any) -> EvaluationResult:
        prompt = self.build_prompt(input=input, output=output, expected=expected)
        if self.judge is not None:
            reply = self.judge(prompt)
            if inspect.isawaitable(reply):
                reply = await reply
            text = str(reply)
        else:
            from agentmesh.providers import ModelRequest

            response = await self.provider.generate(ModelRequest(prompt=prompt, model=self.model, temperature=0.0))
            text = response.text
        return self.parse(text)

    def parse(self, text: str) -> EvaluationResult:
        raw_score, reason = _parse_judgement(text)
        if raw_score is None:
            return EvaluationResult(self.name, label="unparseable", comment=text[:500])
        low, high = self.scale
        normalized = (raw_score - low) / (high - low) if high != low else raw_score
        normalized = min(max(normalized, 0.0), 1.0)
        return EvaluationResult(
            self.name,
            score=round(normalized, 4),
            passed=normalized >= self.threshold,
            comment=reason,
            metadata={"raw_score": raw_score, "judge_model": self.model} if self.model else {"raw_score": raw_score},
        )


def _parse_judgement(text: str) -> tuple[float | None, str | None]:
    cleaned = _strip_fences(text)
    for candidate in [cleaned, *re.findall(r"\{[^{}]*\}", cleaned)]:
        try:
            data = json.loads(candidate)
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(data, dict) and isinstance(data.get("score"), (int, float)) and not isinstance(data.get("score"), bool):
            reason = data.get("reason") or data.get("explanation")
            return float(data["score"]), str(reason) if reason is not None else None
    match = re.search(r"score\W{0,3}\s*([0-9]+(?:\.[0-9]+)?)", cleaned, re.IGNORECASE)
    if match:
        return float(match.group(1)), None
    return None, None


def builtin_evaluator(spec: str) -> Any:
    """Resolve a CLI evaluator name: ``exact_match``, ``contains``, ``json_valid``, ``similarity``,
    ``regex:<pattern>``."""
    name, _, argument = spec.partition(":")
    if name == "exact_match":
        return ExactMatch()
    if name == "contains":
        return Contains(argument) if argument else Contains()
    if name == "json_valid":
        return JSONValid(required_keys=[key for key in argument.split(",") if key]) if argument else JSONValid()
    if name == "similarity":
        return Similarity(threshold=float(argument)) if argument else Similarity()
    if name == "regex" and argument:
        return RegexMatch(argument)
    return None


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    except (TypeError, ValueError):
        return str(value)


def _strip_fences(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```[a-zA-Z0-9]*\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped)
    return stripped.strip()


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else f"{text[:limit]}... [truncated {len(text) - limit} chars]"
