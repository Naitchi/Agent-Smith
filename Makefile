install:
	uv sync
	mv .env.example .env

run:
# 	uv sync
	uv run -m src

clean:
	rm -rf __pycache__ src/__pycache__ .venv
	rm .env
	echo "default=oui" > .env.example
	echo "default2=non" >> .env.example