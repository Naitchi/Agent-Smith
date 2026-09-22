"""Valide une solution SWE-bench avec la moulinette, sur un Docker rootless.

    uv run --project moulinette python scripts/validate_swebench.py \
        cache/swebench_task.json cache/swebench_solution.json [--skip-metrics]

Meme verdict que `moulinette_eval validate swebench ...` : on appelle sa
propre `validate()` (FAIL_TO_PASS / PASS_TO_PASS, statut FULL, puis limites).
Seule difference : `copy_to_container` est remplace.

Pourquoi : celui de swebench tarre le fichier avec l'UID/GID de l'hote
(103940:4225 ici). En Docker rootless, la plage de subuid ne fait que 65536,
donc `put_archive` echoue sur `lchown ... invalid argument` et le patch
n'entre jamais dans le conteneur -- la validation echoue quel que soit le
patch. Ici l'archive est ecrite en root:root, que le daemon sait mapper.

Ne touche a aucun fichier de la moulinette : le remplacement est fait en
memoire, dans ce process seulement.
"""
import argparse
import io
import tarfile
from pathlib import Path

from moulinette.__main__ import MoulinetteCLI
from moulinette.swebench import interact


def copy_to_container_rootless(container, src: Path, dst: Path) -> None:
    """`copy_to_container` de swebench, mais avec une entree tar root:root."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        info = tar.gettarinfo(str(src), arcname=dst.name)
        info.uid = info.gid = 0
        info.uname = info.gname = "root"
        with open(src, "rb") as f:
            tar.addfile(info, f)
    container.exec_run(f"mkdir -p {dst.parent}")
    container.put_archive(str(dst.parent), buf.getvalue())


def main() -> None:
    parser = argparse.ArgumentParser(prog="validate_swebench")
    parser.add_argument("task_file")
    parser.add_argument("solution_file")
    parser.add_argument("--skip-metrics", action="store_true")
    args = parser.parse_args()

    interact.copy_to_container = copy_to_container_rootless
    MoulinetteCLI().validate(
        "swebench", args.task_file, args.solution_file, skip_metrics=args.skip_metrics
    )


if __name__ == "__main__":
    main()
