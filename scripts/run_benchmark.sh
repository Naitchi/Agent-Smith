#!/usr/bin/env bash
# Benchmark SWE-bench : chaque modele x chaque tache, valide et range.
#
#   scripts/run_benchmark.sh
#   MODELS="gemini-3.5-flash" TASKS="sympy__sympy-14711" scripts/run_benchmark.sh
#   RUN_LABEL=ablation_x scripts/run_benchmark.sh      # meme taches, autre reglage
#
# Sortie : BENCHMARK/<label>/<modele>/<tache>/{solution.json, agent.log,
# validation.log, verdict.txt}. Une case avec verdict.txt n'est pas relancee :
# apres un mur de quota, on relance le script et il reprend ou il en etait.
# Une case « INDISPO » (provider en panne ou quota epuise) n'a pas de
# verdict.txt, elle est donc retentee au prochain lancement.
#
# NO_BASCULE=1 : un run = un modele, sinon la case mesure un autre modele.
# La validation passe par scripts/validate_swebench.py (Docker rootless).
set -uo pipefail
unset VIRTUAL_ENV

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LABEL="${RUN_LABEL:-main}"
OUT="$ROOT/BENCHMARK/$LABEL"
TASK_DIR="$ROOT/BENCHMARK/tasks"
MODELS="${MODELS:-gemini-3.5-flash gemini-3.5-flash-lite gemini-3.6-flash openai/gpt-oss-120b qwen/qwen3.8-27b}"
TASKS="${TASKS:-sympy__sympy-14711 sympy__sympy-13480 pydata__xarray-4629}"
TIME_LIMIT=900

mkdir -p "$OUT" "$TASK_DIR"

for task in $TASKS; do
    task_file="$TASK_DIR/$task.json"
    if [ ! -s "$task_file" ]; then
        echo "dump $task"
        (cd "$ROOT/moulinette" && uv run moulinette_eval dump swebench --task-id "$task" --output "$task_file") > /dev/null 2>&1
    fi
    image="$(python3 -c "import json,sys; print(json.load(open(sys.argv[1]))['docker_image'])" "$task_file")"

    for model in $MODELS; do
        dir="$OUT/${model//\//_}/$task"
        if [ -f "$dir/verdict.txt" ]; then
            echo "= $model x $task : $(cat "$dir/verdict.txt") (deja fait)"
            continue
        fi
        mkdir -p "$dir"
        echo "$model" > "$dir/model.txt"
        echo "> $model x $task"

        # Meme plafond que la moulinette, tue le groupe au-dela.
        (cd "$ROOT" && NO_BASCULE=1 timeout --kill-after=10 "$TIME_LIMIT" \
            uv run python -m agent_swebench --task-file "$task_file" \
            --output "$dir/solution.json" --model-name "$model") > "$dir/agent.log" 2>&1

        verdict="NO_OUTPUT"
        if grep -q "plus aucun modele disponible" "$dir/solution.json" 2>/dev/null; then
            verdict="INDISPO"
        elif [ -s "$dir/solution.json" ]; then
            (cd "$ROOT" && uv run --project moulinette python scripts/validate_swebench.py \
                "$task_file" "$dir/solution.json") > "$dir/validation.log" 2>&1
            if grep -q "Resolution status: RESOLVED_FULL" "$dir/validation.log"; then
                verdict="PASS"
            else
                verdict="FAIL"
            fi
        fi
        echo "  -> $verdict"
        [ "$verdict" != "INDISPO" ] && echo "$verdict" > "$dir/verdict.txt"

        # Conteneurs laisses par l'agent (cleanup du serveur MCP) et la validation.
        docker ps -aq --filter "ancestor=$image" | xargs -r docker rm -f > /dev/null
    done
done

uv run python "$ROOT/scripts/benchmark_report.py" "$LABEL"
