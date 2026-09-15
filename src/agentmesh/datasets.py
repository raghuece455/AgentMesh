"""Datasets and experiments: turn traces into test cases, run new versions, compare scores.

A *dataset* is a named list of items (``input``, optional ``expected`` output, metadata),
added by hand, imported from JSONL, or copied from a recorded trace. An *experiment* runs a
task over every item, scores each output with evaluators (see ``agentmesh.evaluators``),
and stores per-item results so two experiments can be compared item by item.

Functions here take a DB-API connection and use SQL that works on SQLite and PostgreSQL.
Use them through ``SQLiteStore`` / ``PostgreSQLStore`` or ``agentmesh.run_experiment``.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from agentmesh.types import JsonObject, JsonValue, dumps_json, loads_json, new_id, utc_now

_MISSING = object()


def create_dataset(
    conn: Any,
    name: str,
    description: str | None = None,
    metadata: JsonObject | None = None,
    exist_ok: bool = False,
) -> JsonObject:
    name = (name or "").strip()
    if not name:
        raise ValueError("dataset name is required")
    if "/" in name:
        # Names are used as URL path segments by the API, the dashboard, and the SDKs.
        raise ValueError("dataset names cannot contain '/'")
    existing = _dataset_row(conn, name)
    if existing is not None:
        if not exist_ok:
            raise ValueError(f"dataset already exists: {name}")
        return _dataset_to_json(conn, existing)
    now = utc_now()
    dataset_id = new_id("ds")
    conn.execute(
        """
        insert into datasets (dataset_id, name, description, created_at, updated_at, metadata_json)
        values (?, ?, ?, ?, ?, ?)
        """,
        (dataset_id, name, description, now, now, dumps_json(metadata or {})),
    )
    return _dataset_to_json(conn, _dataset_row(conn, dataset_id))


def list_datasets(conn: Any) -> list[JsonObject]:
    rows = conn.execute("select * from datasets order by updated_at desc").fetchall()
    return [_dataset_to_json(conn, row) for row in rows]


def get_dataset(
    conn: Any, ref: str, include_items: bool = True, limit: int | None = 5000, offset: int = 0
) -> JsonObject | None:
    """A dataset with a page of its items (``limit=None`` returns all of them; ``item_count`` is the total)."""
    row = _dataset_row(conn, ref)
    if row is None:
        return None
    data = _dataset_to_json(conn, row)
    if include_items:
        data["items"] = list_dataset_items(conn, str(row["dataset_id"]), limit, offset)
    return data


def delete_dataset(conn: Any, ref: str) -> bool:
    row = _dataset_row(conn, ref)
    if row is None:
        return False
    dataset_id = row["dataset_id"]
    conn.execute(
        "delete from experiment_results where experiment_id in (select experiment_id from experiments where dataset_id = ?)",
        (dataset_id,),
    )
    conn.execute("delete from experiments where dataset_id = ?", (dataset_id,))
    conn.execute("delete from dataset_items where dataset_id = ?", (dataset_id,))
    conn.execute("delete from datasets where dataset_id = ?", (dataset_id,))
    return True


def list_dataset_items(conn: Any, dataset_id: str, limit: int | None = 5000, offset: int = 0) -> list[JsonObject]:
    query = "select * from dataset_items where dataset_id = ? order by created_at asc, item_id asc"
    offset = max(int(offset), 0)
    if limit is None:
        rows = conn.execute(query, (dataset_id,)).fetchall()[offset:]
    else:
        rows = conn.execute(f"{query} limit ? offset ?", (dataset_id, max(int(limit), 1), offset)).fetchall()
    return [_item_to_json(row) for row in rows]


def add_dataset_items(conn: Any, ref: str, items: list[JsonObject]) -> list[JsonObject]:
    row = _dataset_row(conn, ref)
    if row is None:
        raise KeyError(f"dataset not found: {ref}")
    dataset_id = str(row["dataset_id"])
    now = utc_now()
    created: list[JsonObject] = []
    for item in items:
        if not isinstance(item, dict) or "input" not in item:
            raise ValueError("each dataset item needs an 'input'")
        item_id = str(item.get("item_id") or item.get("id") or new_id("item"))
        owner = conn.execute("select dataset_id from dataset_items where item_id = ?", (item_id,)).fetchone()
        if owner is not None and owner["dataset_id"] != dataset_id:
            # The id belongs to another dataset (e.g. importing an export of it): copy, never move.
            item_id = new_id("item")
        values = (
            dataset_id,
            dumps_json(item.get("input")),
            dumps_json(item.get("expected")) if item.get("expected") is not None else None,
            dumps_json(item.get("metadata") if isinstance(item.get("metadata"), dict) else {}),
            _str(item.get("source_trace_id")),
            _str(item.get("source_span_id")),
        )
        conn.execute(
            """
            insert into dataset_items
            (item_id, dataset_id, input_json, expected_json, metadata_json, source_trace_id, source_span_id, created_at)
            values (?, ?, ?, ?, ?, ?, ?, ?)
            on conflict(item_id) do update set
              input_json = excluded.input_json,
              expected_json = excluded.expected_json,
              metadata_json = excluded.metadata_json,
              source_trace_id = excluded.source_trace_id,
              source_span_id = excluded.source_span_id
            """,
            (item_id, *values, now),
        )
        created.append({"item_id": item_id, "dataset_id": dataset_id})
    conn.execute("update datasets set updated_at = ? where dataset_id = ?", (now, dataset_id))
    return created


def add_trace_to_dataset(
    conn: Any,
    ref: str,
    trace_id: str,
    span_id: str | None = None,
    expected: Any = _MISSING,
    metadata: JsonObject | None = None,
) -> JsonObject:
    """Copy a trace's (or one span's) input into a dataset item.

    The recorded output becomes ``expected`` unless ``expected`` is given, which is the usual
    way to turn a good production answer into a regression test. Pass ``expected=None`` for
    an item without a reference output (e.g. a failed run you want an LLM judge to grade).
    """
    if span_id:
        source = conn.execute(
            "select input_json, output_json, name, event_type from spans where trace_id = ? and span_id = ?",
            (trace_id, span_id),
        ).fetchone()
        label = (source["name"] or source["event_type"]) if source is not None else None
    else:
        source = conn.execute(
            "select input_json, output_json, workflow_name from workflow_runs where trace_id = ?", (trace_id,)
        ).fetchone()
        label = source["workflow_name"] if source is not None else None
    if source is None:
        raise KeyError(f"trace not found: {trace_id}" if not span_id else f"span not found: {span_id}")
    input_value = loads_json(source["input_json"])
    if input_value is None:
        raise ValueError("the trace has no recorded input (content capture may be disabled)")
    expected_value = loads_json(source["output_json"]) if expected is _MISSING else expected
    item_metadata = {"source": "trace", "trace_name": label, **(metadata or {})}
    created = add_dataset_items(
        conn,
        ref,
        [
            {
                "input": input_value,
                "expected": expected_value,
                "metadata": item_metadata,
                "source_trace_id": trace_id,
                "source_span_id": span_id,
            }
        ],
    )
    return {**created[0], "input": input_value, "expected": expected_value}


def delete_dataset_item(conn: Any, ref: str, item_id: str) -> bool:
    row = _dataset_row(conn, ref)
    if row is None:
        return False
    cursor = conn.execute(
        "delete from dataset_items where dataset_id = ? and item_id = ?", (row["dataset_id"], item_id)
    )
    return (cursor.rowcount or 0) > 0


def inline_item_id(input_value: JsonValue) -> str:
    """A stable id for items passed as plain dicts, so experiments over the same inputs compare."""
    digest = hashlib.sha1(json.dumps(input_value, sort_keys=True, default=str).encode("utf-8")).hexdigest()
    return f"item_{digest[:16]}"


# -- experiments ---------------------------------------------------------------


def save_experiment(conn: Any, payload: JsonObject) -> JsonObject:
    """Create or update an experiment and upsert any results it carries.

    Callers may send the header first (``status='running'``, no results), then results in
    batches, then the final status. The summary is always recomputed from stored results.
    """
    experiment_id = str(payload.get("experiment_id") or new_id("exp"))
    name = _str(payload.get("name")) or experiment_id
    dataset_id = _str(payload.get("dataset_id"))
    dataset_name = _str(payload.get("dataset_name"))
    dataset_ref = _str(payload.get("dataset"))
    if dataset_ref and not dataset_id:
        row = _dataset_row(conn, dataset_ref)
        if row is not None:
            dataset_id, dataset_name = str(row["dataset_id"]), str(row["name"])
        else:
            dataset_name = dataset_name or dataset_ref
    now = utc_now()
    existing = conn.execute("select started_at from experiments where experiment_id = ?", (experiment_id,)).fetchone()
    started_at = str(payload.get("started_at") or (existing["started_at"] if existing is not None else now))
    status = str(payload.get("status") or "running")
    for result in payload.get("results") or []:
        _upsert_result(conn, experiment_id, result)
    summary = _summarize_results(_result_rows(conn, experiment_id))
    conn.execute(
        """
        insert into experiments
        (experiment_id, dataset_id, dataset_name, name, description, status, started_at, ended_at,
         evaluators_json, summary_json, metadata_json)
        values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        on conflict(experiment_id) do update set
          dataset_id = coalesce(excluded.dataset_id, experiments.dataset_id),
          dataset_name = coalesce(excluded.dataset_name, experiments.dataset_name),
          name = excluded.name,
          description = coalesce(excluded.description, experiments.description),
          status = excluded.status,
          ended_at = coalesce(excluded.ended_at, experiments.ended_at),
          evaluators_json = excluded.evaluators_json,
          summary_json = excluded.summary_json,
          metadata_json = excluded.metadata_json
        """,
        (
            experiment_id,
            dataset_id,
            dataset_name,
            name,
            _str(payload.get("description")),
            status,
            started_at,
            _str(payload.get("ended_at")),
            dumps_json(payload.get("evaluators") or []),
            dumps_json(summary),
            dumps_json(payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}),
        ),
    )
    return {"experiment_id": experiment_id, "status": status, "summary": summary}


def list_experiments(conn: Any, dataset: str | None = None, limit: int = 100) -> list[JsonObject]:
    params: list[Any] = []
    clause = ""
    if dataset:
        row = _dataset_row(conn, dataset)
        clause = "where e.dataset_id = ? or e.dataset_name = ?"
        params.extend([row["dataset_id"] if row is not None else dataset, dataset])
    rows = conn.execute(
        f"""
        select e.*,
          (select coalesce(sum(c.estimated_cost), 0) from cost_records c
             where c.trace_id in (select r.trace_id from experiment_results r where r.experiment_id = e.experiment_id)) as total_cost,
          (select coalesce(sum(c.total_tokens), 0) from cost_records c
             where c.trace_id in (select r.trace_id from experiment_results r where r.experiment_id = e.experiment_id)) as total_tokens
        from experiments e
        {clause}
        order by e.started_at desc
        limit ?
        """,
        (*params, max(min(int(limit), 1000), 1)),
    ).fetchall()
    return [_experiment_to_json(row) for row in rows]


def get_experiment(conn: Any, experiment_id: str) -> JsonObject | None:
    row = conn.execute(
        """
        select e.*,
          (select coalesce(sum(c.estimated_cost), 0) from cost_records c
             where c.trace_id in (select r.trace_id from experiment_results r where r.experiment_id = e.experiment_id)) as total_cost,
          (select coalesce(sum(c.total_tokens), 0) from cost_records c
             where c.trace_id in (select r.trace_id from experiment_results r where r.experiment_id = e.experiment_id)) as total_tokens
        from experiments e where e.experiment_id = ?
        """,
        (experiment_id,),
    ).fetchone()
    if row is None:
        return None
    data = _experiment_to_json(row)
    costs = {
        str(item["trace_id"]): item
        for item in conn.execute(
            """
            select trace_id, coalesce(sum(estimated_cost), 0) as cost, coalesce(sum(total_tokens), 0) as tokens
            from cost_records
            where trace_id in (select trace_id from experiment_results where experiment_id = ?)
            group by trace_id
            """,
            (experiment_id,),
        ).fetchall()
    }
    results = []
    for result in _result_rows(conn, experiment_id):
        cost = costs.get(str(result["trace_id"]))
        result["estimated_cost"] = float(cost["cost"]) if cost is not None else 0.0
        result["total_tokens"] = int(cost["tokens"]) if cost is not None else 0
        results.append(result)
    data["results"] = results
    return data


def delete_experiment(conn: Any, experiment_id: str) -> bool:
    conn.execute("delete from experiment_results where experiment_id = ?", (experiment_id,))
    cursor = conn.execute("delete from experiments where experiment_id = ?", (experiment_id,))
    return (cursor.rowcount or 0) > 0


def compare_experiments(conn: Any, base_id: str, candidate_id: str) -> JsonObject | None:
    """Item-by-item comparison. An item regresses when it newly errors, newly fails an
    evaluator, or its mean score drops; it improves in the opposite cases."""
    base = get_experiment(conn, base_id)
    candidate = get_experiment(conn, candidate_id)
    if base is None or candidate is None:
        return None
    base_items = {str(item["item_id"]): item for item in base["results"]}
    candidate_items = {str(item["item_id"]): item for item in candidate["results"]}
    rows: list[JsonObject] = []
    counts = {"improved": 0, "regressed": 0, "unchanged": 0, "added": 0, "removed": 0}
    for item_id in list(dict.fromkeys([*base_items, *candidate_items])):
        left, right = base_items.get(item_id), candidate_items.get(item_id)
        if left is None:
            change = "added"
        elif right is None:
            change = "removed"
        else:
            change = _item_change(left, right)
        counts[change] += 1
        source = right or left or {}
        rows.append(
            {
                "item_id": item_id,
                "input": source.get("input"),
                "expected": source.get("expected"),
                "change": change,
                "base": _compact_result(left),
                "candidate": _compact_result(right),
            }
        )
    order = {"regressed": 0, "improved": 1, "added": 2, "removed": 3, "unchanged": 4}
    rows.sort(key=lambda row: order[str(row["change"])])
    base_scores = base["summary"].get("scores", {})
    candidate_scores = candidate["summary"].get("scores", {})
    deltas = {}
    for name in dict.fromkeys([*base_scores, *candidate_scores]):
        left_mean = (base_scores.get(name) or {}).get("mean")
        right_mean = (candidate_scores.get(name) or {}).get("mean")
        deltas[name] = {
            "base": left_mean,
            "candidate": right_mean,
            "delta": (right_mean - left_mean) if left_mean is not None and right_mean is not None else None,
        }
    return {
        "base": {key: value for key, value in base.items() if key != "results"},
        "candidate": {key: value for key, value in candidate.items() if key != "results"},
        "score_deltas": deltas,
        "cost_delta": float(candidate.get("total_cost") or 0) - float(base.get("total_cost") or 0),
        "latency_delta_ms": _delta(base["summary"].get("avg_latency_ms"), candidate["summary"].get("avg_latency_ms")),
        "counts": counts,
        "items": rows,
    }


# -- helpers ---------------------------------------------------------------------


def _dataset_row(conn: Any, ref: str) -> Any:
    return conn.execute("select * from datasets where dataset_id = ? or name = ?", (ref, ref)).fetchone()


def _dataset_to_json(conn: Any, row: Any) -> JsonObject:
    counts = conn.execute(
        """
        select
          (select count(*) from dataset_items where dataset_id = ?) as item_count,
          (select count(*) from experiments where dataset_id = ?) as experiment_count,
          (select max(started_at) from experiments where dataset_id = ?) as last_experiment_at
        """,
        (row["dataset_id"], row["dataset_id"], row["dataset_id"]),
    ).fetchone()
    return {
        "dataset_id": row["dataset_id"],
        "name": row["name"],
        "description": row["description"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "metadata": loads_json(row["metadata_json"]) or {},
        "item_count": int(counts["item_count"] or 0),
        "experiment_count": int(counts["experiment_count"] or 0),
        "last_experiment_at": counts["last_experiment_at"],
    }


def _item_to_json(row: Any) -> JsonObject:
    return {
        "item_id": row["item_id"],
        "dataset_id": row["dataset_id"],
        "input": loads_json(row["input_json"]),
        "expected": loads_json(row["expected_json"]),
        "metadata": loads_json(row["metadata_json"]) or {},
        "source_trace_id": row["source_trace_id"],
        "source_span_id": row["source_span_id"],
        "created_at": row["created_at"],
    }


def _upsert_result(conn: Any, experiment_id: str, result: JsonObject) -> None:
    item_id = str(result.get("item_id") or inline_item_id(result.get("input")))
    result_id = str(result.get("result_id") or f"{experiment_id}:{item_id}")
    scores = [score for score in result.get("scores") or [] if isinstance(score, dict) and score.get("name")]
    conn.execute(
        """
        insert into experiment_results
        (result_id, experiment_id, item_id, trace_id, status, input_json, expected_json, output_json, error_message,
         duration_ms, scores_json, created_at)
        values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        on conflict(result_id) do update set
          trace_id = excluded.trace_id,
          status = excluded.status,
          input_json = excluded.input_json,
          expected_json = excluded.expected_json,
          output_json = excluded.output_json,
          error_message = excluded.error_message,
          duration_ms = excluded.duration_ms,
          scores_json = excluded.scores_json
        """,
        (
            result_id,
            experiment_id,
            item_id,
            _str(result.get("trace_id")),
            "failed" if result.get("error") or result.get("status") == "failed" else "completed",
            dumps_json(result.get("input")),
            dumps_json(result.get("expected")) if result.get("expected") is not None else None,
            dumps_json(result.get("output")),
            _str(result.get("error")),
            _num(result.get("duration_ms")),
            dumps_json(scores),
            str(result.get("created_at") or utc_now()),
        ),
    )


def _result_rows(conn: Any, experiment_id: str) -> list[JsonObject]:
    rows = conn.execute(
        "select * from experiment_results where experiment_id = ? order by created_at asc, item_id asc",
        (experiment_id,),
    ).fetchall()
    return [
        {
            "result_id": row["result_id"],
            "item_id": row["item_id"],
            "trace_id": row["trace_id"],
            "status": row["status"],
            "input": loads_json(row["input_json"]),
            "expected": loads_json(row["expected_json"]),
            "output": loads_json(row["output_json"]),
            "error": row["error_message"],
            "duration_ms": row["duration_ms"],
            "scores": loads_json(row["scores_json"]) or [],
            "created_at": row["created_at"],
        }
        for row in rows
    ]


def _summarize_results(results: list[JsonObject]) -> JsonObject:
    by_name: dict[str, dict[str, list[Any]]] = {}
    for result in results:
        for score in result.get("scores") or []:
            bucket = by_name.setdefault(str(score["name"]), {"values": [], "passed": []})
            if score.get("score") is not None:
                bucket["values"].append(float(score["score"]))
            if score.get("passed") is not None:
                bucket["passed"].append(bool(score["passed"]))
    scores = {
        name: {
            "mean": sum(bucket["values"]) / len(bucket["values"]) if bucket["values"] else None,
            "min": min(bucket["values"]) if bucket["values"] else None,
            "max": max(bucket["values"]) if bucket["values"] else None,
            "count": len(bucket["values"]),
            "pass_rate": sum(bucket["passed"]) / len(bucket["passed"]) if bucket["passed"] else None,
        }
        for name, bucket in by_name.items()
    }
    durations = [float(result["duration_ms"]) for result in results if result.get("duration_ms") is not None]
    errors = sum(1 for result in results if result.get("status") == "failed")
    return {
        "items": len(results),
        "errors": errors,
        "error_rate": errors / len(results) if results else 0.0,
        "avg_latency_ms": sum(durations) / len(durations) if durations else None,
        "scores": scores,
    }


def _experiment_to_json(row: Any) -> JsonObject:
    return {
        "experiment_id": row["experiment_id"],
        "dataset_id": row["dataset_id"],
        "dataset_name": row["dataset_name"],
        "name": row["name"],
        "description": row["description"],
        "status": row["status"],
        "started_at": row["started_at"],
        "ended_at": row["ended_at"],
        "evaluators": loads_json(row["evaluators_json"]) or [],
        "summary": loads_json(row["summary_json"]) or {},
        "metadata": loads_json(row["metadata_json"]) or {},
        "total_cost": float(row["total_cost"] or 0),
        "total_tokens": int(row["total_tokens"] or 0),
    }


def _item_change(left: JsonObject, right: JsonObject) -> str:
    if left["status"] != right["status"]:
        return "regressed" if right["status"] == "failed" else "improved"
    left_scores = {str(score["name"]): score for score in left.get("scores") or []}
    right_scores = {str(score["name"]): score for score in right.get("scores") or []}
    shared = [name for name in left_scores if name in right_scores]
    worse = better = False
    for name in shared:
        before, after = left_scores[name], right_scores[name]
        if before.get("passed") is not None and after.get("passed") is not None and before["passed"] != after["passed"]:
            worse, better = worse or not after["passed"], better or bool(after["passed"])
        elif before.get("score") is not None and after.get("score") is not None:
            delta = float(after["score"]) - float(before["score"])
            worse, better = worse or delta < -1e-9, better or delta > 1e-9
    if worse:
        return "regressed"
    return "improved" if better else "unchanged"


def _compact_result(result: JsonObject | None) -> JsonObject | None:
    if result is None:
        return None
    return {
        "status": result["status"],
        "output": result.get("output"),
        "error": result.get("error"),
        "trace_id": result.get("trace_id"),
        "duration_ms": result.get("duration_ms"),
        "estimated_cost": result.get("estimated_cost"),
        "scores": result.get("scores"),
    }


def _delta(left: Any, right: Any) -> float | None:
    if left is None or right is None:
        return None
    return float(right) - float(left)


def _str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text else None


def _num(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None
