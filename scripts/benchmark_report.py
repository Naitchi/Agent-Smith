"""Write the benchmark tables of BENCHMARK/<label> into BENCHMARK_REPORT.md.

Usage: uv run python scripts/benchmark_report.py [label]
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from statistics import mean

ROOT = Path(__file__).resolve().parent.parent
REPORT = ROOT / "BENCHMARK_REPORT.md"

SKELETON = """# Benchmark Report

## 1. Setup

## 2. Results

## 3. Provider reliability

See the reliability tables in section 2.

## 4. Intermediary metrics

See the intermediary metrics tables in section 2.

## 5. Ablation

## 6. Conclusions
"""

SYMPY_PASSED = (r"tests finished: \d+ passed"
                r"(?:, \d+ (?:skipped|expected to fail))*, in")


def tests_ok(output: str) -> bool:
    """Return True if a run_tests() output reports that all tests passed."""
    if re.search(SYMPY_PASSED, output):
        return True
    if (re.search(r"^OK\b", output, re.MULTILINE)
            and not re.search(r"^FAILED \(", output, re.MULTILINE)):
        return True
    return (bool(re.search(r"=+ \d+ passed", output))
            and not re.search(r"\d+ (?:failed|errors?)\b", output))


def first_contact(steps: list[dict],
                  files: list[str]) -> tuple[int | None, int | None]:
    """Return the first step reading and the first step editing a file."""
    read = edit = None
    for step in steps:
        code = step["sandbox_input"]
        if not any(name in code for name in files):
            continue
        if read is None:
            read = step["step"]
        if edit is None and "edit_file" in code:
            edit = step["step"]
    return read, edit


def discipline(steps: list[dict], success: bool) -> str:
    """Count iterations between the first passing run_tests and the end."""
    if not success or not steps:
        return "-"
    for step in steps:
        if ("run_tests" in step["sandbox_input"]
                and tests_ok(step["sandbox_output"])):
            return str(max(0, steps[-1]["step"] - step["step"] - 1))
    return "?"


def load_cases(label: str) -> list[dict]:
    """Return one entry per model x task run, with its verdict."""
    cases = []
    runs = (ROOT / "BENCHMARK" / label).glob("*/*/solution.json")
    for solution in sorted(runs):
        data = json.loads(solution.read_text())
        verdict_file = solution.parent / "verdict.txt"
        verdict = (verdict_file.read_text().strip()
                   if verdict_file.exists() else "INDISPO")
        files = re.findall(r"^diff --git a/(\S+) b/", data["solution"],
                           re.MULTILINE)
        read, edit = first_contact(data["steps"], files)
        cases.append({
            "model": (solution.parent / "model.txt").read_text().strip(),
            "task": solution.parent.name,
            "verdict": verdict,
            "data": data,
            "read": read,
            "edit": edit,
            "discipline": discipline(data["steps"], data["success"]),
        })
    return cases


def results_table(label: str, cases: list[dict]) -> list[str]:
    lines = [
        f"### Results ({label})",
        "",
        "`final_answer`: no = the agent did not submit by itself; the CLI "
        "returned the container's patch (`get_patch()`), which is what was "
        "validated. INDISPO = provider unavailable (quota or overload).",
        "",
        "| model | task | verdict | final_answer | iterations | tokens in "
        "| tokens out | time (s) |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for case in cases:
        data = case["data"]
        answered = "yes" if data["success"] else "no"
        lines.append(
            f"| {case['model']} | {case['task']} | {case['verdict']} "
            f"| {answered} | {data['iterations']} "
            f"| {data['total_input_tokens']} "
            f"| {data['total_output_tokens']} "
            f"| {data['total_time_seconds']:.0f} |"
        )
    return lines


def reliability_table(label: str, cases: list[dict]) -> list[str]:
    lines = [
        "",
        f"### Provider reliability ({label})",
        "",
        "Average time = mean `request_time_ms` of the steps. Retries = sum "
        "of step `retries` (429, network, empty answers). Useful requests = "
        "steps / requests sent. Availability = runs not INDISPO / runs "
        "launched.",
        "",
        "| model | average time / request (s) | retries | useful requests "
        "| availability |",
        "|---|---|---|---|---|",
    ]
    for model in sorted({case["model"] for case in cases}):
        runs = [case for case in cases if case["model"] == model]
        steps = [step for case in runs for step in case["data"]["steps"]]
        requests = sum(case["data"]["total_requests"] for case in runs)
        average = (f"{mean(s['request_time_ms'] for s in steps) / 1000:.1f}"
                   if steps else "-")
        useful = f"{len(steps)}/{requests}" if requests else "-"
        available = sum(case["verdict"] != "INDISPO" for case in runs)
        retries = sum(step["retries"] for step in steps)
        lines.append(
            f"| {model} | {average} | {retries} | {useful} "
            f"| {available}/{len(runs)} |"
        )
    return lines


def intermediary_table(label: str, cases: list[dict]) -> list[str]:
    lines = [
        "",
        f"### Intermediary metrics ({label})",
        "",
        "First contact = first step whose code names a file of the final "
        "patch; first edit = first `edit_file` on that file. Discipline = "
        "iterations between the first passing `run_tests()` and "
        "`final_answer` (ideal 0; \"?\" when the test summary was "
        "truncated).",
        "",
        "| model | task | first contact | first edit | discipline |",
        "|---|---|---|---|---|",
    ]
    for case in cases:
        lines.append(
            f"| {case['model']} | {case['task']} | {case['read'] or '-'} "
            f"| {case['edit'] or '-'} | {case['discipline']} |"
        )
    return lines


def tables(label: str, cases: list[dict]) -> str:
    """Render the results, reliability and intermediary metrics tables."""
    if not cases:
        return f"_No run in BENCHMARK/{label}/._"
    return "\n".join(results_table(label, cases)
                     + reliability_table(label, cases)
                     + intermediary_table(label, cases))


def main() -> None:
    label = sys.argv[1] if len(sys.argv) > 1 else "main"
    start = f"<!-- AUTO:{label}:START -->"
    end = f"<!-- AUTO:{label}:END -->"
    block = f"{start}\n{tables(label, load_cases(label))}\n{end}"

    text = REPORT.read_text() if REPORT.exists() else SKELETON
    if start in text:
        text = re.sub(re.escape(start) + r".*?" + re.escape(end),
                      lambda _: block, text, flags=re.DOTALL)
    else:
        text = text.replace("## 3. Provider reliability",
                            f"{block}\n\n## 3. Provider reliability", 1)
    REPORT.write_text(text)
    print(f"{REPORT.name}: '{label}' tables updated")


if __name__ == "__main__":
    main()
