TASK ?= cache/mbpp_task.json
SWE_TASK ?= cache/swebench_task.json
OUT  ?= solution.json
MODEL ?= qwen/qwen3.8-27b

install:
	uv sync
	echo "Please edit .env file to add your API keys."
	echo "GROQ_API_KEY=" > .env
	echo "GEMINI_API_KEY=" >> .env
	echo "MISTRAL_API_KEY=" >> .env
	echo "TESTBED_PATH=" >> .env

run:
	uv run -m src

solution:
	uv run python -m moulinette dump mbpp --task-id 3 --output task.json


run_mbpp:
	uv run python -m agent_mbpp --task-file $(TASK) --output $(OUT) $(if $(MODEL),--model-name $(MODEL))

run_sw-bench:
	uv run python -m agent_swebench --task-file $(SWE_TASK) --output $(OUT) $(if $(MODEL),--model-name $(MODEL))


bench:
	scripts/run_benchmark.sh

clean:
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type d -name "backup_memory" -exec rm -rf {} + 

fclean:
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type d -name "backup_memory" -exec rm -rf {} +
	rm -rf .venv
	rm -f .env
