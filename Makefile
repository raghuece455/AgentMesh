.PHONY: setup test dev dashboard demo example lint format typecheck build-dashboard smoke screenshots docker clean

setup:
	python -m pip install -e ".[dev]"
	cd dashboard && npm ci

test:
	pytest

dev:
	python -m agentmesh.cli demo seed
	python -m agentmesh.cli dashboard

dashboard:
	python -m agentmesh.cli dashboard

demo:
	python -m agentmesh.cli demo seed --reset

example:
	python -m agentmesh.cli run examples/hello_agent.py

lint:
	ruff check src tests examples

format:
	ruff format src tests examples

typecheck:
	mypy src

build-dashboard:
	cd dashboard && npm run build

smoke:
	cd dashboard && npm run test:smoke

screenshots:
	cd dashboard && npm run screenshots

docker:
	docker compose up --build

clean:
	python -c "import shutil, pathlib; [shutil.rmtree(p, ignore_errors=True) for p in ['.pytest_cache', '.mypy_cache', '.ruff_cache', 'build', 'dist']]; [shutil.rmtree(p, ignore_errors=True) for p in pathlib.Path('.').rglob('__pycache__')]"
