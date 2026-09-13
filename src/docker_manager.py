import sys
from typing import cast

import docker as d
from docker import errors


class DockerManager:
    def __init__(self, image: str, timeout_timer: int = 30):
        self.client: d.DockerClient = d.from_env()
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

    def exec(
        self, command: str, workdir: str
    ) -> tuple[int | None, str | None, str | None]:
        code: int | None = None
        stderr: str | None = None
        stdout: str | None = None
        try:
            code, stdio = cast(
                tuple[int | None, tuple[bytes | None, bytes | None]],
                self.container.exec_run(
                    f"timeout {self.timeout_timer}s {command}",
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
                        f"timeout {self.timeout_timer}s {command}",
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
