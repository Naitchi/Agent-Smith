"""Tableaux du benchmark, generes depuis BENCHMARK/<label>/*/*/solution.json.

    uv run python scripts/benchmark_report.py [label]      # defaut : main

Ecrit entre les marqueurs `<!-- AUTO:<label>:START/END -->` de
BENCHMARK_REPORT.md (cree avec les sections du sujet V.7 s'il manque) : le
texte ecrit a la main autour n'est jamais touche. Seuls les chiffres sont
generes ; l'analyse et les conclusions restent a ecrire depuis ces chiffres.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from statistics import mean

ROOT = Path(__file__).resolve().parent.parent
REPORT = ROOT / "BENCHMARK_REPORT.md"

SQUELETTE = """# Benchmark Report

## 1. Setup

## 2. Results

## 3. Provider reliability

Voir le tableau « fiabilite » de la section 2.

## 4. Intermediary metrics

Voir le tableau « metriques intermediaires » de la section 2.

## 5. Ablation

## 6. Conclusions
"""


def tests_ok(output: str) -> bool:
    """Heuristique : la sortie de `run_tests()` annonce-t-elle un succes ?

    Formats vus : sympy (`tests finished: 4 passed, in 2.4 seconds`, un echec
    ajoute `, 1 failed` avant `, in`), unittest/django (`OK` seul en ligne),
    pytest (`=== 5 passed ===`). Une sortie tronquee par le serveur peut
    perdre le resume : on rend alors False, la metrique vaut « ? ».
    """
    if re.search(r"tests finished: \d+ passed(?:, \d+ (?:skipped|expected to fail))*, in", output):
        return True
    if re.search(r"^OK\b", output, re.MULTILINE) and not re.search(r"^FAILED \(", output, re.MULTILINE):
        return True
    return bool(re.search(r"=+ \d+ passed", output)) and not re.search(r"\d+ (?:failed|errors?)\b", output)


def premier_contact(steps: list[dict], fichiers: list[str]) -> tuple[int | None, int | None]:
    """(1er step qui lit/cherche un fichier du patch final, 1er qui l'edite)."""
    lecture = edition = None
    for s in steps:
        code = s["sandbox_input"]
        if not any(f in code for f in fichiers):
            continue
        if lecture is None:
            lecture = s["step"]
        if edition is None and "edit_file" in code:
            edition = s["step"]
    return lecture, edition


def discipline(steps: list[dict], success: bool) -> str:
    """Iterations entre le 1er `run_tests()` OK et `final_answer` (ideal 0)."""
    if not success or not steps:
        return "-"
    for s in steps:
        if "run_tests" in s["sandbox_input"] and tests_ok(s["sandbox_output"]):
            return str(max(0, steps[-1]["step"] - s["step"] - 1))
    return "?"


def charger(label: str) -> list[dict]:
    """Une ligne par case modele x tache, avec son verdict."""
    cases = []
    for sol in sorted((ROOT / "BENCHMARK" / label).glob("*/*/solution.json")):
        data = json.loads(sol.read_text())
        verdict_file = sol.parent / "verdict.txt"
        verdict = verdict_file.read_text().strip() if verdict_file.exists() else "INDISPO"
        fichiers = re.findall(r"^diff --git a/(\S+) b/", data["solution"], re.MULTILINE)
        lecture, edition = premier_contact(data["steps"], fichiers)
        cases.append({
            "model": (sol.parent / "model.txt").read_text().strip(),
            "task": sol.parent.name,
            "verdict": verdict,
            "data": data,
            "lecture": lecture,
            "edition": edition,
            "discipline": discipline(data["steps"], data["success"]),
        })
    return cases


def tableaux(label: str, cases: list[dict]) -> str:
    if not cases:
        return f"_Aucun run dans BENCHMARK/{label}/._"
    lignes = [
        f"### Resultats ({label})",
        "",
        "`final_answer` : non = l'agent n'a pas soumis lui-meme ; la CLI a rendu le "
        "patch du conteneur (`get_patch()`), c'est lui qui a ete valide.",
        "",
        "| modele | tache | verdict | final_answer | iterations | tokens in | tokens out | temps (s) |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for c in cases:
        d = c["data"]
        lignes.append(
            f"| {c['model']} | {c['task']} | {c['verdict']} | {'oui' if d['success'] else 'non'} | {d['iterations']} "
            f"| {d['total_input_tokens']} | {d['total_output_tokens']} | {d['total_time_seconds']:.0f} |"
        )

    lignes += [
        "",
        f"### Fiabilite des providers ({label})",
        "",
        "Temps moyen = moyenne des `request_time_ms` des steps. Retries = somme des "
        "`retries` (429, reseau, reponses vides). Requetes utiles = steps / requetes "
        "envoyees. Disponibilite = cases non INDISPO / cases lancees.",
        "",
        "| modele | temps moyen / requete (s) | retries | requetes utiles | disponibilite |",
        "|---|---|---|---|---|",
    ]
    for model in sorted({c["model"] for c in cases}):
        mine = [c for c in cases if c["model"] == model]
        steps = [s for c in mine for s in c["data"]["steps"]]
        requetes = sum(c["data"]["total_requests"] for c in mine)
        temps = f"{mean(s['request_time_ms'] for s in steps) / 1000:.1f}" if steps else "-"
        utiles = f"{len(steps)}/{requetes}" if requetes else "-"
        dispo = sum(c["verdict"] != "INDISPO" for c in mine)
        lignes.append(
            f"| {model} | {temps} | {sum(s['retries'] for s in steps)} | {utiles} | {dispo}/{len(mine)} |"
        )

    lignes += [
        "",
        f"### Metriques intermediaires ({label})",
        "",
        "1er contact = 1er step dont le code nomme un fichier du patch final ; "
        "1re edition = 1er `edit_file` sur ce fichier. Discipline = iterations entre "
        "le 1er `run_tests()` qui passe et `final_answer` (ideal 0 ; « ? » si le "
        "resume des tests a ete tronque).",
        "",
        "| modele | tache | 1er contact | 1re edition | discipline |",
        "|---|---|---|---|---|",
    ]
    for c in cases:
        lignes.append(
            f"| {c['model']} | {c['task']} | {c['lecture'] or '-'} | {c['edition'] or '-'} | {c['discipline']} |"
        )
    return "\n".join(lignes)


def main() -> None:
    label = sys.argv[1] if len(sys.argv) > 1 else "main"
    debut, fin = f"<!-- AUTO:{label}:START -->", f"<!-- AUTO:{label}:END -->"
    bloc = f"{debut}\n{tableaux(label, charger(label))}\n{fin}"

    texte = REPORT.read_text() if REPORT.exists() else SQUELETTE
    if debut in texte:
        texte = re.sub(re.escape(debut) + r".*?" + re.escape(fin), lambda _: bloc, texte, flags=re.DOTALL)
    else:
        texte = texte.replace("## 3. Provider reliability", f"{bloc}\n\n## 3. Provider reliability", 1)
    REPORT.write_text(texte)
    print(f"{REPORT.name} : tableaux '{label}' a jour")


if __name__ == "__main__":
    main()
