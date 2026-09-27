"""Local (host) command executor for the SWE-bench MCP tools.

The counterpart to `DockerManager`: same `exec` / `replace_file` / `cleanup`
interface, but runs commands on the host filesystem rooted at `TESTBED_PATH`
instead of inside a container. It is used when the MCP server is started
without a task (no `docker_image` to build a container from) — the way the
moulinette tests the tools in isolation, setting `TESTBED_PATH` to a real
repository checkout before starting the server.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path, PurePosixPath


class LocalManager:
    """Runs shell commands on the host, rooted at `TESTBED_PATH`.

    Attributes:
        timeout_timer: Wall-clock limit, in seconds, applied to every
            command run via `exec()`.
        workdir: Absolute path to the repository root on the host, read
            from the `TESTBED_PATH` environment variable.
    """

    def __init__(self, timeout_timer: int = 30) -> None:
        """Resolve the repository root from `TESTBED_PATH`.

        Args:
            timeout_timer: Wall-clock limit, in seconds, for one `exec()`
                call before it is killed.

        Raises:
            RuntimeError: If `TESTBED_PATH` is unset or empty — the subject
                requires the moulinette to set this exact variable name
                before the MCP server starts.
        """
        self.timeout_timer = timeout_timer
        try:
            self.workdir = os.environ["TESTBED_PATH"]
        except KeyError as e:
            raise RuntimeError(
                "Error: no environment variable TESTBED_PATH set."
            ) from e
        if not self.workdir:
            raise RuntimeError(
                "Error: environment variable TESTBED_PATH is empty."
            )

    def exec(
        self, command: str, workdir: str | None = None
    ) -> tuple[int | None, str | None, str | None]:
        """Run a shell command on the host under a timeout.

        Args:
            command: The shell command to run, executed as
                ``timeout {timeout_timer}s bash -c "<command>"``.
            workdir: Directory to run it from. Relative paths (including
                the implicit default) are resolved against `self.workdir`.

        Returns:
            A `(exit_code, stdout, stderr)` triplet — `stdout`/`stderr`
            are `None` when empty, not empty strings — matching
            `DockerManager.exec`.
        """
        if not workdir:
            workdir = self.workdir
        elif not PurePosixPath(workdir).is_absolute():
            workdir = str(PurePosixPath(self.workdir) / workdir)
        proc = subprocess.run(
            ["timeout", f"{self.timeout_timer}s", "bash", "-c", command],
            cwd=workdir,
            capture_output=True,
            check=False,
        )
        stdout = proc.stdout.decode(errors="replace") if proc.stdout else None
        stderr = proc.stderr.decode(errors="replace") if proc.stderr else None
        return (proc.returncode, stdout, stderr)

    def replace_file(self, path: str, content: bytes) -> None:
        """Overwrite a file on the host with `content`.

        Args:
            path: Destination path, absolute or resolved against
                `self.workdir` if relative.
            content: The new file content.
        """
        p = Path(path)
        if not p.is_absolute():
            p = Path(self.workdir) / p
        p.write_bytes(content)

    def cleanup(self) -> None:
        """No-op: nothing to tear down when running on the host."""
