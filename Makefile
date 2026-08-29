install:
	uv sync
	mv .env.example .env

run:
	uv run -m src

clean:
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type d -name "backup_memory" -exec rm -rf {} +
	rm -rf .venv
	rm .env
	echo "GROQ_API_KEY=" > .env.example
	echo "GEMINI_API_KEY=" >> .env.example
