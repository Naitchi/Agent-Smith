"""MCP server exposing SWE-bench tools.

Bridges the 9 mandatory SWE-bench tools to the task's
repository — filesystem access, grep-like code search, test execution and
patch generation — exposed over MCP via stdio or streamable HTTP.

The repository is reached through one of two interchangeable backends:
a 'DockerManager' (a long-lived container started from the task's
'docker_image') when a task is given, or a 'LocalManager' (the host
filesystem rooted at `TESTBED_PATH`) when the server is started without
one — the way the moulinette exercises the tools in isolation.
"""

import argparse
import ast
import json
import shlex
import signal
import sys
from types import FrameType

from mcp.server import MCPServer

from schemas.swe_bench_task_input import SWEBenchTaskInput
from src.docker_manager import DockerManager
from src.local_manager import LocalManager


class MCPServerSWEBench:
    def __init__(
        self,
        task: SWEBenchTaskInput | None = None,
        timeout: int = 30,
        max_std_length: int = 10000,
    ):
        """Build the MCP server, start its repository backend, register tools.

        Args:
            task: The SWE-bench task this server solves, or None. When a
                task is given, its ``docker_image`` backs a `DockerManager`
                and its ``eval_script`` backs ``run_tests``. When it is
                None, a `LocalManager` runs the tools against the host
                repository at ``TESTBED_PATH`` (tools-in-isolation mode).
            timeout: Wall-clock limit, in seconds, for one command
                executed against the repository before it is killed.
            max_std_length: Maximum number of characters of captured
                stdout/stderr kept in a tool's result before truncation.

        Raises:
            RuntimeError: In isolation mode, if ``TESTBED_PATH`` is unset.
        """
        self.timeout_timer = timeout
        self.max_std_length = max_std_length
        self.task = task
        self.mcp = MCPServer("SWEBench-tools")
        self.repo: DockerManager | LocalManager
        if self.task:
            self.repo = DockerManager(self.task.docker_image, timeout)
        else:
            self.repo = LocalManager(timeout)
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

    @staticmethod
    def _python_syntax_error(filepath: str, content: str) -> str | None:
        """Return a syntax-error message if `content` is invalid Python.

        Args:
            filepath: Path of the file, used only to decide whether the
                content is Python (``.py``); non-Python files are skipped.
            content: The file's new content after an edit.

        Returns:
            A one-line ``SyntaxError`` description (message plus line
            number) when `filepath` is a ``.py`` file that no longer
            parses, or None otherwise.
        """
        if not filepath.endswith(".py"):
            return None
        try:
            ast.parse(content)
        except SyntaxError as e:
            return f"{e.msg} (line {e.lineno})"
        return None

    def register_tools(self) -> None:
        """Register the 9 mandatory SWE-bench MCP tools.

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
            path = shlex.quote(filepath)
            if end_line is None:
                return self._format_result(
                    *self.repo.exec(f"cat -n {path}")
                )
            else:
                return self._format_result(
                    *self.repo.exec(
                        f"cat -n {path} | sed -n "
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
                than once (ambiguous). When the edited file is Python and
                the change introduces a syntax error, the replacement is
                kept but the message flags the error.
            """
            _, file, _ = self.repo.exec(f"cat {shlex.quote(filepath)}")
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
            self.repo.replace_file(filepath, file.encode())
            message = (
                f"Successfully replaced '{old_str}' with '{new_str}' in"
                f" {filepath}."
            )
            syntax_error = self._python_syntax_error(filepath, file)
            if syntax_error:
                message += (
                    f"\nWarning: {filepath} now has a syntax error: "
                    f"{syntax_error}. Fix it before running the tests."
                )
            return message

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
            command = (
                f"find {shlex.quote(directory)} -name {shlex.quote(pattern)}"
            )
            return self._format_result(*self.repo.exec(command))

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
            root = shlex.quote(self.repo.workdir)
            return self._format_result(
                *self.repo.exec(
                    self._grep_to_spec_format(
                        f"grep -rnwI --exclude-dir=.git {shlex.quote(pattern)}"
                        f" --include={shlex.quote(file_pattern)} {root}"
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
            root = shlex.quote(self.repo.workdir)
            def_pat = shlex.quote(f"def {name}")
            class_pat = shlex.quote(f"class {name}")
            return self._format_result(
                *self.repo.exec(
                    self._grep_to_spec_format(
                        f"grep -rnwI --exclude-dir=.git -e {def_pat}"
                        f" -e {class_pat} --include='*.py' {root}"
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
            root = self.repo.workdir
            full_path = (
                filepath if filepath.startswith("/") else f"{root}/{filepath}"
            )
            exclude = shlex.quote(f"^{full_path}:{line}:")
            return self._format_result(
                *self.repo.exec(
                    self._grep_to_spec_format(
                        f"grep -rnwI --exclude-dir=.git {shlex.quote(name)}"
                        f" {shlex.quote(root)} | grep -v {exclude}"
                    )
                )
            )

        @self.mcp.tool()
        def run_tests() -> str:
            """Execute the task's evaluation script against the repository.

            Returns:
                The captured stdout/stderr and exit code of
                eval_script — a clean run typically means the fix (if
                any) resolved the issue. When the server was started
                without a task (isolation mode), there is no eval_script,
                so an explicit message is returned instead.
            """
            if not self.task:
                return (
                    "Error: run_tests is unavailable without a task "
                    "(no eval_script); the server was started in isolation "
                    "mode."
                )
            return self._format_result(
                *self.repo.exec(self.task.eval_script)
            )

        @self.mcp.tool()
        def get_patch() -> str:
            """Retrieve the unified git diff of all changes made so far.

            Returns:
                the git diff or ``"(no output)"`` if nothing has
                been changed yet.
            """
            return self._format_result(
                *self.repo.exec("git -c core.fileMode=false diff")
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
                *self.repo.exec(command, workdir=workdir)
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
        """Tear down the repository backend of this server.

        Safe to call more than once (`cleanup()` is idempotent). Wired to
        SIGTERM/SIGINT in ``__main__`` so container cleanup still runs when
        the process is force-killed mid-task; a no-op for
        the local backend.
        """
        repo = getattr(self, "repo", None)
        if repo is not None:
            repo.cleanup()


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
    try:
        server = MCPServerSWEBench(task=task)
    except RuntimeError as e:
        print(str(e), file=sys.stderr)
        sys.exit(1)

    def _handle_termination(signum: int, frame: FrameType | None) -> None:
        server.close()
        sys.exit(0)

    signal.signal(signal.SIGTERM, _handle_termination)
    signal.signal(signal.SIGINT, _handle_termination)
    try:
        if args.http:
            server.mcp.run("streamable-http", host=args.host, port=args.port)
        else:
            server.mcp.run()
    finally:
        server.close()
