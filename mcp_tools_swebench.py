"""MCP server exposing SWE-bench tools.

Bridges the 9 mandatory SWE-bench tools (subject V.5) to a long-lived
Docker container holding the task's repository: filesystem access,
grep-like code search, test execution, and patch generation, exposed
over MCP via stdio or streamable HTTP.
"""

import argparse
import json
import signal
import sys
from types import FrameType

from mcp.server import MCPServer

from schemas.swe_bench_task_input import SWEBenchTaskInput
from src.docker_manager import DockerManager


class MCPServerSWEBench:
    def __init__(
        self,
        task: SWEBenchTaskInput | None = None,
        timeout: int = 30,
        max_std_length: int = 10000,
    ):
        """Build the MCP server, start its Docker container, register tools.

        Args:
            task: The SWE-bench task this server solves. Required: its
                ``docker_image`` is used to start the container the
                tools run against, and its ``eval_script`` backs
                ``run_tests``.
            timeout: Wall-clock limit, in seconds, for one command
                executed inside the container before it is killed.
            max_std_length: Maximum number of characters of captured
                stdout/stderr kept in a tool's result before truncation.

        Raises:
            ValueError: If no task was provided — there is no Docker
                image to build the container from.
        """
        self.timeout_timer = timeout
        self.max_std_length = max_std_length
        self.task = task
        self.mcp = MCPServer("SWEBench-tools")
        if self.task:
            self.docker_manager = DockerManager(
                self.task.docker_image,
            )
        else:
            raise ValueError("Task must be provided to initialize the server.")
        self.register_tools()
        self.register_resources()
        self.register_prompts()

    def _truncate(self, text: str) -> str:
        """Cut text to max_std_length chars, flagging it clearly when trimmed.

        Args:
            text: The text to truncate (typically a command's captured
                stdout or stderr).

        Returns:
            text unchanged if within max_std_length, otherwise the
            first max_std_length characters followed by a truncation
            notice.
        """
        if len(text) > self.max_std_length:
            return (
                text[: self.max_std_length]
                + f"... (truncated, {len(text)} chars total)"
            )
        return text

    def _format_result(
        self,
        code: int | None,
        stdout: str | None,
        stderr: str | None,
    ) -> str:
        """Fold a DockerManager.exec() triplet into one string for the agent.

        Args:
            code: The command's exit code, or None if it never
                produced one.
            stdout: Captured standard output, or None if empty.
            stderr: Captured standard error, or None if empty.

        Returns:
            stdout (truncated) followed by a clearly separated stderr
            section when present, and the exit code when it signals
            failure. ``"(no output)"`` when there is nothing to report.
        """
        parts: list[str] = []
        if stdout:
            parts.append(self._truncate(stdout))
        if stderr:
            parts.append(f"---- stderr ----\n{self._truncate(stderr)}")
        if code not in (0, None):
            parts.append(f"(exit code {code})")
        return "\n".join(parts) if parts else "(no output)"

    @staticmethod
    def _grep_to_spec_format(grep_command: str) -> str:
        """Pipe a grep command's output into the format the subject imposes.

        Args:
            grep_command: A shell command whose stdout is grep's
                ``path:line_number:line_content``, one match per line.

        Returns:
            The same command with a ``sed`` stage appended that turns
            the colon right after the line number into a space,
            producing ``path:line_number line_content``.
        """
        return grep_command + " | sed -E 's/^([^:]+:[0-9]+):/\\1 /'"

    def register_tools(self) -> None:
        """Register the 9 mandatory SWE-bench MCP tools (subject V.5).

        Registers:
            read_file: Read a file's content with line numbers (cat -n).
            edit_file: Replace an exact, unique string in a file.
            list_files: List files in a directory matching a pattern.
            search_code: grep-like search across the repository.
            search_function_or_class_definition_in_code: Find a def
                or class definition.
            find_references: Find usages of a symbol, excluding its
                own definition site.
            run_tests: Execute the task's eval_script.
            get_patch: Return the unified git diff of all changes made.
            run_command: Execute an arbitrary shell command.
        """

        @self.mcp.tool()
        def read_file(
            filepath: str, start_line: int = 0, end_line: int | None = None
        ) -> str:
            """Read a file's content with line numbers, ``cat -n``-style.

            Args:
                filepath: Path to the file, absolute or relative to
                    the repository root.
                start_line: First line to include when end_line is set.
                end_line: Last line to include. When None, the whole
                    file is returned.

            Returns:
                Each requested line as ``<line_number>\tline_content``,
                or an error message (with exit code/stderr) if the
                file is missing.
            """
            if end_line is None:
                return self._format_result(
                    *self.docker_manager.exec(f"cat -n {filepath}")
                )
            else:
                return self._format_result(
                    *self.docker_manager.exec(
                        f"cat -n {filepath} | sed -n "
                        f"'{start_line},{end_line}p'"
                    )
                )

        @self.mcp.tool()
        def edit_file(filepath: str, old_str: str, new_str: str) -> str:
            """Replace an exact, unique string in a file.

            Args:
                filepath: Path to the file to edit.
                old_str: The exact substring to replace. Must occur
                    exactly once in the file — see Returns for the
                    alternative.
                new_str: The text to put in its place.

            Returns:
                A success message naming the replacement made, or an
                explicit error message if the file is missing, if
                old_str does not occur in it, or if it occurs more
                than once (ambiguous).
            """
            _, file, _ = self.docker_manager.exec(f"cat {filepath}")
            if file is None:
                return f"Error: File {filepath} not found."
            occurence = file.count(old_str)
            if occurence == 0:
                return f"Error: String '{old_str}' not found in {filepath}."
            if occurence > 1:
                return (
                    f"Error: String '{old_str}' found {occurence} times in "
                    f"{filepath}. Please specify a unique string to replace."
                )
            file = file.replace(old_str, new_str)
            self.docker_manager.replace_file(filepath, file.encode())
            return (
                f"Successfully replaced '{old_str}' with '{new_str}' in"
                f" {filepath}."
            )

        @self.mcp.tool()
        def list_files(directory: str, pattern: str = "*") -> str:
            """List files in a directory matching a glob pattern.

            Args:
                directory: Directory to search, absolute or relative
                    to the repository root.
                pattern: A ``find -name`` glob pattern (e.g. ``"*.py"``).

            Returns:
                One matching path per line, or an error message on
                failure.
            """
            return self._format_result(
                *self.docker_manager.exec(
                    f"find {directory} -name '{pattern}'"
                )
            )

        @self.mcp.tool()
        def search_code(pattern: str, file_pattern: str = "*") -> str:
            """Perform a grep-like search across the repository.

            Args:
                pattern: The whole-word pattern to search for.
                file_pattern: Only search files matching this glob
                    (e.g. ``"*.py"``). Defaults to every file.

            Returns:
                One match per line as
                ``/absolute/path.py:<line_number> <line_content>``,
                or an error message if nothing matched.
            """
            root = self.docker_manager.workdir
            return self._format_result(
                *self.docker_manager.exec(
                    self._grep_to_spec_format(
                        f"grep -rnwI --exclude-dir=.git '{pattern}'"
                        f" --include='{file_pattern}' {root}"
                    )
                )
            )

        @self.mcp.tool()
        def search_function_or_class_definition_in_code(name: str) -> str:
            """Find the definition of a function or a class.

            Args:
                name: The function or class name to look for (matches
                    both ``def name`` and ``class name`` in Python
                    files).

            Returns:
                One match per line, in the same format as
                search_code, or an error message if no definition
                was found.
            """
            root = self.docker_manager.workdir
            return self._format_result(
                *self.docker_manager.exec(
                    self._grep_to_spec_format(
                        f"grep -rnwI --exclude-dir=.git -e 'def {name}'"
                        f" -e 'class {name}' --include='*.py' {root}"
                    )
                )
            )

        @self.mcp.tool()
        def find_references(name: str, filepath: str, line: int) -> str:
            """Find all usages of a symbol, excluding its own definition.

            Args:
                name: The symbol (function or class name) to look for.
                filepath: Path to the file where the symbol is defined.
                line: The line number of the definition, so it can be
                    excluded from the results.

            Returns:
                One match per line, in the same format as
                search_code, or an error message if no reference was
                found.
            """
            root = self.docker_manager.workdir
            full_path = (
                filepath
                if filepath.startswith("/")
                else f"{root}/{filepath}"
            )
            return self._format_result(
                *self.docker_manager.exec(
                    self._grep_to_spec_format(
                        f"grep -rnwI --exclude-dir=.git '{name}' {root}"
                        f" | grep -v '^{full_path}:{line}:'"
                    )
                )
            )

        @self.mcp.tool()
        def run_tests() -> str:
            """Execute the task's evaluation script inside the container.

            Returns:
                The captured stdout/stderr and exit code of
                eval_script — a clean run typically means the fix (if
                any) resolved the issue.

            Raises:
                ValueError: If the server was built without a task.
            """
            if not self.task:
                raise ValueError("Task must be provided to run tests.")
            return self._format_result(
                *self.docker_manager.exec(self.task.eval_script)
            )

        @self.mcp.tool()
        def get_patch() -> str:
            """Retrieve the unified git diff of all changes made so far.

            Returns:
                The output of ``git -c core.fileMode=false diff`` —
                exactly the format the subject requires for a
                submitted patch — or ``"(no output)"`` if nothing has
                been changed yet.
            """
            return self._format_result(
                *self.docker_manager.exec("git -c core.fileMode=false diff")
            )

        @self.mcp.tool()
        def run_command(command: str, workdir: str | None = None) -> str:
            """Execute an arbitrary shell command inside the container.

            Args:
                command: The shell command to run.
                workdir: Directory to run it from, absolute or
                    relative to the repository root. Defaults to the
                    repository root.

            Returns:
                The command's stdout, stderr, and exit code, folded
                into one string.
            """
            return self._format_result(
                *self.docker_manager.exec(command, workdir=workdir)
            )

    def register_resources(self) -> None:
        """Register the ``swebench://task`` resource.

        Exposes the current task as a JSON document, or ``"{}"`` when
        the server was started without a task.
        """

        @self.mcp.resource(
            "swebench://task", name="task", mime_type="application/json"
        )
        def get_task() -> str:
            """The SWE-bench task the server is solving, as a JSON object.

            Returns the serialized ``SWEBenchTaskInput`` (instance_id,
            problem_statement, docker_image, eval_script, hints_text,
            repo), or ``"{}"`` when the server was started without a
            task.
            """
            if self.task:
                return self.task.model_dump_json()
            return "{}"

    def register_prompts(self) -> None:
        """Register the MCP prompt that guides an LLM through a task.

        The prompt describes the Thought -> Code -> Observation loop,
        the available tools, and how to submit a solution with
        ``final_answer``.
        """

        @self.mcp.prompt()
        def swebench_methodology() -> str:
            """Give a prompt about the methodology to solve SWE-bench tasks"""
            return (
                "You are solving a SWE-bench task, using the Thought -> "
                "Code -> Observation loop.\n\n"
                '1. Fetch the task with get_resource("swebench://task"). '
                "It returns the problem statement and repository info.\n"
                "2. Explore the codebase: list_files, search_code, "
                "search_function_or_class_definition_in_code and "
                "find_references to find where the issue lives.\n"
                "3. Read the relevant files with read_file before editing "
                "anything.\n"
                "4. Make your fix with edit_file(filepath, old_str, "
                "new_str) — old_str must match exactly once in the file.\n"
                "5. Validate with run_tests(). If it fails, use the "
                "output to revise your edit and try again.\n"
                "6. You can inspect your accumulated changes at any time "
                "with get_patch().\n"
                "7. Once run_tests() passes, submit your final answer by "
                "calling final_answer(get_patch()) — pass the raw git "
                "diff, not an explanation.\n\n"
                "Repeat Thought (what to try next), Code (what you send "
                "to the sandbox), and Observation (the tool's output) "
                "until the tests pass."
            )

    def close(self) -> None:
        """Tear down the Docker container backing this server.

        Safe to call more than once. Wired to SIGTERM/SIGINT in
        ``__main__`` so cleanup still runs when the process is
        force-killed mid-task (subject VI.1.1).
        """
        if getattr(self, "docker_manager", None) is not None:
            self.docker_manager.cleanup()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(prog="server-SWEBench")
    parser.add_argument(
        "--task-file",
        default=None,
        help="Path to a JSON task file.",
    )
    parser.add_argument(
        "--http",
        default=False,
        action="store_true",
        help="Command to launch an MCP server with http.",
    )
    parser.add_argument(
        "--host",
        default="localhost",
        help="host to bind the server to (default: localhost)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8080,
        help="Config the port to bind the server to (default: 8080).",
    )
    args = parser.parse_args()

    task = None
    if args.task_file:
        try:
            with open(args.task_file) as f:
                task_data = json.load(f)
            task = SWEBenchTaskInput.model_validate(task_data)
        except Exception as e:
            print(f"Error loading task file: {e}", file=sys.stderr)
            sys.exit(1)
    server = MCPServerSWEBench(task=task)

    def _handle_termination(signum: int, frame: FrameType | None) -> None:
        server.close()
        sys.exit(0)

    signal.signal(signal.SIGTERM, _handle_termination)
    signal.signal(signal.SIGINT, _handle_termination)

    if args.http:
        server.mcp.run("streamable-http", host=args.host, port=args.port)
    else:
        server.mcp.run()
