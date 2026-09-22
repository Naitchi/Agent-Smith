"""Validate a SWE-bench solution with the moulinette on rootless Docker.

Usage: uv run --project moulinette python scripts/validate_swebench.py
       TASK_FILE SOLUTION_FILE [--skip-metrics]
"""
import argparse
import io
import tarfile
from pathlib import Path

from moulinette.__main__ import MoulinetteCLI
from moulinette.swebench import interact


def copy_to_container_rootless(container, src: Path, dst: Path) -> None:
    """Copy a file into the container as a root:root tar entry."""
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as tar:
        info = tar.gettarinfo(str(src), arcname=dst.name)
        info.uid = info.gid = 0
        info.uname = info.gname = "root"
        with open(src, "rb") as file:
            tar.addfile(info, file)
    container.exec_run(f"mkdir -p {dst.parent}")
    container.put_archive(str(dst.parent), buffer.getvalue())


def main() -> None:
    parser = argparse.ArgumentParser(prog="validate_swebench")
    parser.add_argument("task_file")
    parser.add_argument("solution_file")
    parser.add_argument("--skip-metrics", action="store_true")
    args = parser.parse_args()

    interact.copy_to_container = copy_to_container_rootless
    MoulinetteCLI().validate(
        "swebench", args.task_file, args.solution_file,
        skip_metrics=args.skip_metrics,
    )


if __name__ == "__main__":
    main()
