"""Docker container lifecycle for the SWE-bench MCP tools.

Wraps the docker-py SDK: starts one long-lived container per task and
execs shell commands into it repeatedly, rather than spinning up a new
container per tool call — the whole point is that filesystem/git state
(edits, history) has to persist across an entire agent session.
"""

import io
import os
import sys
import tarfile
from pathlib import PurePosixPath
from typing import cast

from docker import DockerClient, errors, from_env


class DockerManager:
    """Owns one Docker container for the lifetime of a SWE-bench MCP server.

    Attributes:
        client: The docker-py client for the local Docker daemon.
        image: Image the container is (re)started from.
        timeout_timer: Wall-clock limit, in seconds, applied to every
            command run via `exec()`.
        container: The container instance backing this manager.
        workdir: Absolute path to the repository root inside the
            container, read from the `TESTBED_PATH` environment variable.
    """

    def __init__(self, image: str, timeout_timer: int = 30):
        """Start the container and resolve the repository root.

        Args:
            image: Docker image to run — typically
                ``task.docker_image`` from a `SWEBenchTaskInput`.
            timeout_timer: Wall-clock limit, in seconds, for one
                `exec()` call before it is killed.

        Raises:
            RuntimeError: If the container can't be started even after
                an explicit `pull_image()` retry, or if the
                `TESTBED_PATH` environment variable is unset or empty —
                the subject requires the moulinette to set this exact
                variable name before the MCP server starts.
        """
        self.client: DockerClient = from_env()
        self.image: str = image
        self.timeout_timer = timeout_timer
        try:
            self.container = self.run_container()
        except errors.APIError as e:
            print(
                f"Error starting Docker container: {e}."
                " Attempting to pull the image and retry.",
                file=sys.stderr,
            )
            try:
                self.pull_image()
                self.container = self.run_container()
            except errors.APIError as e:
                raise RuntimeError(
                    f"Error: Even after retry, failed to start container: {e}"
                ) from e
        try:
            self.workdir = os.environ["TESTBED_PATH"]
            if not self.workdir:
                raise RuntimeError(
                    "Error: environment variable TESTBED_PATH is empty."
                )
        except KeyError as e:
            raise RuntimeError(
                "Error: no environment variable TESTBED_PATH set."
            ) from e

    def run_container(self):
        """Start a new detached container from `self.image`.

        Returns:
            The running `Container`, kept alive with a `tail -f
            /dev/null` no-op command so it can be exec'd into
            repeatedly instead of restarted per tool call.
        """
        return self.client.containers.run(
            self.image, command="tail -f /dev/null", detach=True
        )

    def pull_image(self):
        """Explicitly pull `self.image` from its registry.

        Called as a fallback when starting the container fails because
        the image isn't present locally yet — kept separate from
        `run_container`'s own implicit pull so a restart triggered by
        `exec()` doesn't re-pull a multi-GB image every time.

        Raises:
            RuntimeError: If the pull itself fails.
        """
        try:
            self.client.images.pull(self.image)
        except errors.APIError as e:
            raise RuntimeError(
                f"Failed to pull Docker image {self.image}: {e}"
            ) from e

    def replace_file(self, path: str, content: bytes) -> None:
        """Overwrite a file inside the container with `content`.

        Args:
            path: Destination path, absolute or resolved against
                `self.workdir` if relative.
            content: The new file content.

        Writes via `container.put_archive` (a single-file tar uploaded
        over the Docker API) rather than a shell command — arbitrary
        source code routinely contains quotes/newlines that break naive
        shell interpolation, and `put_archive` has no notion of a
        working directory the way `exec_run` does, so the destination
        must already be resolved to an absolute path before calling it.
        """
        p = PurePosixPath(path)
        if not p.is_absolute():
            p = PurePosixPath(self.workdir) / p

        tar_buffer = io.BytesIO()
        with tarfile.open(fileobj=tar_buffer, mode="w") as tar:
            info = tarfile.TarInfo(p.name)
            info.size = len(content)
            tar.addfile(info, io.BytesIO(content))

        tar_buffer.seek(0)
        self.container.put_archive(str(p.parent), tar_buffer)

    def exec(
        self, command: str, workdir: str | None = None
    ) -> tuple[int | None, str | None, str | None]:
        """Run a shell command inside the container under a timeout.

        Args:
            command: The shell command to run, executed as
                ``timeout {timeout_timer}s bash -c "<command>"``.
            workdir: Directory to run it from. Relative paths (including
                the implicit default) are resolved against
                `self.workdir` — Docker's exec API rejects a relative
                `Cwd` outright.

        Returns:
            A `(exit_code, stdout, stderr)` triplet — `stdout`/`stderr`
            are `None` when empty, not empty strings.

        Raises:
            RuntimeError: If the command still fails with `APIError`
                after one restart-container-and-retry. That retry is a
                last resort, not a routine recovery path: it wipes any
                uncommitted state in the testbed, so it only fires on
                `APIError` (the container itself is gone/not running),
                never on a merely-failing command (which surfaces as a
                normal non-zero exit code instead).
        """
        if not workdir:
            workdir = self.workdir
        elif not PurePosixPath(workdir).is_absolute():
            workdir = str(PurePosixPath(self.workdir) / workdir)
        code: int | None = None
        stderr: str | None = None
        stdout: str | None = None
        try:
            code, stdio = cast(
                tuple[int | None, tuple[bytes | None, bytes | None]],
                self.container.exec_run(
                    [
                        "timeout",
                        f"{self.timeout_timer}s",
                        "bash",
                        "-c",
                        command,
                    ],
                    workdir=workdir,
                    demux=True,
                ),
            )
        except errors.APIError as e:
            print(
                f"Error executing command '{command}' in container: {e}."
                " Restarting the container from image and retrying."
                " (All previous modifications will be lost)",
                file=sys.stderr,
            )
            try:
                self.container = self.run_container()
                code, stdio = cast(
                    tuple[int | None, tuple[bytes | None, bytes | None]],
                    self.container.exec_run(
                        [
                            "timeout",
                            f"{self.timeout_timer}s",
                            "bash",
                            "-c",
                            command,
                        ],
                        workdir=workdir,
                        demux=True,
                    ),
                )
            except errors.APIError as e:
                raise RuntimeError(
                    f"Error: Even after retry, failed to execute {command} in"
                    f" container: {e}"
                ) from e

        if stdio[0]:
            stdout = stdio[0].decode()
        if stdio[1]:
            stderr = stdio[1].decode()
        return (code, stdout, stderr)

    def stop_container(self):
        """Stop the running container (does not remove it)."""
        self.container.stop()

    def remove_container(self):
        """Remove the (stopped) container."""
        self.container.remove()

    def cleanup(self):
        """Stop and remove the container.

        Safe to call from a signal handler — see
        `MCPServerSWEBench.close()`, which the subject requires to run
        even when the process is force-killed on timeout.
        """
        self.stop_container()
        self.remove_container()
