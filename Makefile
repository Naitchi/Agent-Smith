TASK ?= cache/mbpp_task.json
SWE_TASK ?= cache/swebench_task.json
OUT  ?= solution.json
MODEL ?= qwen/qwen3.8-27b

install:
	uv sync
	make banner
	test -f .env || cp .env.example .env
	@echo "Please edit .env file to add your API keys."



banner:
	@printf '\033[1;38;5;118m%s\033[0m\n' ' █████╗  ██████╗ ███████╗███╗   ██╗████████╗    ███████╗███╗   ███╗██╗████████╗██╗  ██╗'
	@printf '\033[1;38;5;82m%s\033[0m\n' '██╔══██╗██╔════╝ ██╔════╝████╗  ██║╚══██╔══╝    ██╔════╝████╗ ████║██║╚══██╔══╝██║  ██║'
	@printf '\033[1;38;5;46m%s\033[0m\n' '███████║██║  ███╗█████╗  ██╔██╗ ██║   ██║       ███████╗██╔████╔██║██║   ██║   ███████║'
	@printf '\033[1;38;5;40m%s\033[0m\n' '██╔══██║██║   ██║██╔══╝  ██║╚██╗██║   ██║       ╚════██║██║╚██╔╝██║██║   ██║   ██╔══██║'
	@printf '\033[1;38;5;34m%s\033[0m\n' '██║  ██║╚██████╔╝███████╗██║ ╚████║   ██║       ███████║██║ ╚═╝ ██║██║   ██║   ██║  ██║'
	@printf '\033[1;38;5;28m%s\033[0m\n' '╚═╝  ╚═╝ ╚═════╝ ╚══════╝╚═╝  ╚═══╝   ╚═╝       ╚══════╝╚═╝     ╚═╝╚═╝   ╚═╝   ╚═╝  ╚═╝'

run:
	clear
	make banner
	@read -p "Enter your benchmark category (0 = mbpp, 1 = swe): " bench; \
	if [ "$$bench" = 0 ]; then \
		uv run python -m agent_mbpp --task-file $(TASK) --output $(OUT) $(if $(MODEL),--model-name $(MODEL)); \
	else \
		uv run python -m agent_swebench --task-file $(SWE_TASK) --output $(OUT) $(if $(MODEL),--model-name $(MODEL)); \
	fi



solution:
	uv run python -m moulinette dump mbpp --task-id 3 --output task.json


run_mbpp:
	uv run python -m agent_mbpp --task-file $(TASK) --output $(OUT) $(if $(MODEL),--model-name $(MODEL))

run_sw-bench:
	uv run python -m agent_swebench --task-file $(SWE_TASK) --output $(OUT) $(if $(MODEL),--model-name $(MODEL))

clean: 
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type d -name "backup_memory" -exec rm -rf {} + 

fclean:
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type d -name "backup_memory" -exec rm -rf {} +
	find . -type d -name ".mypy_cache" -exec rm -rf {} +
	echo "GROQ_API_KEY=" > .env.example
	echo "GEMINI_API_KEY=" >> .env.example
	echo "MISTRAL_API_KEY=" >> .env.example
	echo "TESTBED_PATH=" >> .env.example
	rm -rf .venv
	rm -f .env


lint:
	uv run flake8 --extend-exclude moulinette,.venv,BENCHMARK,cache .
	uv run mypy .
