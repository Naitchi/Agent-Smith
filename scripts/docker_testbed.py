"""Lightweight local stand-in for a SWE-bench Docker instance.

Spins up (or tears down) a throwaway container seeded with a tiny git repo
at TESTBED_PATH, containing one buggy function, a failing test, and an
eval script — just enough to develop and smoke-test the SWE-bench MCP
tools' Docker bridge (Option B: sandbox on the host, tools exec into
Docker) without pulling a real multi-GB swebench/sweb.eval.* image.

Once the real thing is needed, swap this for a task dumped by the
moulinette (docker_image + eval_script from SWEBenchTaskInput).

Usage:
    uv run python ./scripts/docker_testbed.py start
    uv run python ./scripts/docker_testbed.py stop <container_id>
"""

from __future__ import annotations

import argparse
import subprocess
import sys

from docker.errors import ImageNotFound

import docker

IMAGE = "agent-smith/testbed:latest"
DOCKERFILE_DIR = "docker"
DOCKERFILE_NAME = "testbed.Dockerfile"
TESTBED_PATH = "/testbed"

# Seeds a git repo with a bug (add() subtracts instead of adding), a test
# that catches it, and an eval script — mirrors the shape of a real
# SWE-bench instance (problem statement + failing test + eval_script)
# closely enough to exercise all 9 mandatory tools.
SETUP_SCRIPT = f"""
set -e
mkdir -p {TESTBED_PATH}
cd {TESTBED_PATH}
git init -q
git config user.email test@example.com
git config user.name test
cat > add.py <<'EOF'
def add(a, b):
    return a - b  # bug: should be a + b
EOF
cat > test_add.py <<'EOF'
from add import add


def test_add():
    assert add(2, 3) == 5


if __name__ == "__main__":
    test_add()
    print("OK")
EOF
cat > eval.sh <<'EOF'
#!/bin/bash
cd {TESTBED_PATH}
# -B: skip .pyc caching. Repeated edit/run cycles during dev can land
# within the same on-disk mtime tick, which would otherwise make Python
# reuse a stale cached bytecode for add.py after edit_file changes it.
python -B test_add.py
EOF
chmod +x eval.sh
git add -A
git commit -q -m "initial state (with bug)"
"""


def _ensure_image(client: docker.DockerClient) -> None:
    try:
        client.images.get(IMAGE)
    except ImageNotFound:
        print(
            f"Building {IMAGE} (one-time, needs git on top of "
            "python:3.11-slim)...",
            file=sys.stderr,
        )
        # Shells out to the docker CLI rather than client.images.build():
        # docker-py's legacy build API fails on some rootless/remapped
        # daemons (lchown error on the build context tar), while a plain
        # `docker build` (BuildKit) works fine on the same daemon.
        subprocess.run(
            [
                "docker",
                "build",
                "-t",
                IMAGE,
                "-f",
                f"{DOCKERFILE_DIR}/{DOCKERFILE_NAME}",
                DOCKERFILE_DIR,
            ],
            check=True,
        )


def start() -> str:
    client = docker.from_env()
    _ensure_image(client)
    container = client.containers.run(
        IMAGE, command="tail -f /dev/null", detach=True
    )
    exit_code, output = container.exec_run(["bash", "-c", SETUP_SCRIPT])
    if exit_code != 0:
        container.stop(timeout=5)
        container.remove()
        raise RuntimeError(f"Repo setup failed:\n{output.decode()}")

    print(f"Container {container.id} ready.")
    print(
        f"  TESTBED_PATH={TESTBED_PATH} "
        "(path inside the container, not the host)"
    )
    print(f"  docker exec -it {container.id} bash   # to poke around")
    print(f"  uv run python ./scripts/docker_testbed.py stop {container.id}")
    return container.id


def stop(container_id: str) -> None:
    client = docker.from_env()
    container = client.containers.get(container_id)
    container.stop(timeout=5)
    container.remove()
    print(f"Container {container_id} stopped and removed.")


def main() -> None:
    parser = argparse.ArgumentParser(prog="docker_testbed")
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser(
        "start", help="Build (if needed) and start a testbed container."
    )
    stop_parser = sub.add_parser(
        "stop", help="Stop and remove a testbed container."
    )
    stop_parser.add_argument("container_id")
    args = parser.parse_args()

    if args.action == "start":
        start()
    else:
        stop(args.container_id)


if __name__ == "__main__":
    main()
