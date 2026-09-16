import io
import os
import sys
import tarfile
from pathlib import PurePosixPath
from typing import cast

from docker import DockerClient, errors, from_env


class DockerManager:
    def __init__(self, image: str, timeout_timer: int = 30):
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
        return self.client.containers.run(
            self.image, command="tail -f /dev/null", detach=True
        )

    def pull_image(self):
        try:
            self.client.images.pull(self.image)
        except errors.APIError as e:
            raise RuntimeError(
                f"Failed to pull Docker image {self.image}: {e}"
            ) from e

    def replace_file(self, path: str, content: bytes) -> None:
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
        if not workdir:
            workdir = self.workdir
        elif not PurePosixPath(workdir).is_absolute():
            # Docker's exec API rejects a relative Cwd outright ("Cwd must
            # be an absolute path") — resolve it against the testbed root
            # ourselves, the same way replace_file() already does.
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
        self.container.stop()

    def remove_container(self):
        self.container.remove()

    def cleanup(self):
        self.stop_container()
        self.remove_container()
