install:
	uv sync

run:
	uv sync
	uv run -m src

clean:
	rm -rf __pycache__ src/__pycache__ .venv