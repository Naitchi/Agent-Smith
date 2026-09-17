TASK ?= cache/mbpp_task.json
OUT  ?= solution.json
MODEL ?= qwen/qwen3.8-27b

install:
	uv sync
	mv .env.example .env

run:
	uv run -m src

solution:
	uv run python -m moulinette dump mbpp --task-id 3 --output task.json


run_mbpp:
	uv run python -m agent_mbpp --task-file $(TASK) --output $(OUT) $(if $(MODEL),--model-name $(MODEL))

clean:
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type d -name "backup_memory" -exec rm -rf {} + 

fclean:
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type d -name "backup_memory" -exec rm -rf {} +
	rm -rf .venv
	rm .env
	echo "GROQ_API_KEY=" > .env.example
	echo "GEMINI_API_KEY=" >> .env.example
	echo "TESTBED_PATH=" >> .env.example
