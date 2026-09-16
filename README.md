*This project has been created as part of the 42 curriculum by mobenais, bclairot.*

# Agent Smith

## Description

Agent Smith is an autonomous coding agent, built and evaluated against two benchmarks:

- **MBPP** (Mostly Basic Python Problems) — small, self-contained Python programming
  exercises validated by a test suite.
- **SWE-bench** — real GitHub issues from real open-source repositories, evaluated
  inside the project's own Docker environment.

The agent runs a **Thought → Code → Observation** loop: an LLM writes a block of
Python code, that code executes inside an isolated **sandbox**, and the result is
fed back to the LLM as the next observation. The sandbox exposes a set of tools
(reading/editing files, searching code, running tests, etc.) as ordinary Python
functions, without the agent's prompt or code ever hardcoding what those tools are
— they are discovered dynamically from whichever **MCP (Model Context Protocol)**
server is connected, so the system works against an MCP server it has never seen
before.

The project is split into two independent halves behind one interface contract:

- **Agent side** (mobenais) — the LLM providers, code extraction, the
  Thought/Code/Observation loop, the benchmark CLIs.
- **Execution side** (bclairot) — the sandbox (security, isolation, the
  `final_answer()` mechanism), the MCP client, and the MCP tool servers for both
  benchmarks (including the Docker bridge for SWE-bench).

## Instructions

### Install

```bash
make install        # uv sync, then creates .env from .env.example
```

or manually:

```bash
uv sync
cp .env.example .env
```

Fill in `.env` with your LLM provider API key(s) (see [Agent Loop](#agent-loop)
below for which environment variables are read).

### Run the sandbox on its own (no LLM)

```bash
uv run sandbox                                              # bare REPL, no MCP server
uv run sandbox sandbox_template.json                        # with a config file
uv run sandbox --mcp-stdio "python mcp_tools_mbpp.py"       # connect an MCP server over stdio
uv run sandbox --mcp-server http://localhost:8080           # connect one over HTTP
```

Each line typed is executed and remembered across the session (variables persist,
the same way the agent's code blocks do). `exit` or Ctrl+D to leave.

### Run an MCP tool server on its own

```bash
uv run python mcp_tools_mbpp.py --task-file cache/mbpp_task.json
uv run python mcp_tools_swebench.py --task-file cache/swebench_task.json
```

Both support `--http --host --port` for streamable HTTP instead of stdio. The
SWE-bench server additionally needs a **`TESTBED_PATH`** environment variable set
to the repository root before it starts (see `.env.example`) — the moulinette sets
this itself when testing the tools in isolation.

To try the SWE-bench tools against a local throwaway container instead of pulling a
real multi-GB SWE-bench image:

```bash
uv run python ./scripts/docker_testbed.py start
uv run python ./scripts/test_mcp_swebench.py
```

### Run the agent loop

A minimal demo entry point exists today:

```bash
uv run -m src                    # runs a default task through AgentLoop + Gemini
uv run -m src "your task here"
```

> **TODO (mobenais):** the subject-mandated CLIs (`agent_mbpp`/`agent_swebench`,
> with `--task-file`/`--output`/`--model-name`/`--provider-url`, driven by the
> moulinette's `dump`/`validate` flow) are not built yet — only the underlying
> `AgentLoop` engine and this ad-hoc `src/__main__.py` demo exist so far.

### Run the exam scripts

`exam_mbpp.sh`/`exam_swebench.sh`/`exam_sandbox.sh` are provided by the evaluation
harness (not part of this repository) and invoked as:

```bash
./exam_TYPE.sh --student-path ./student --moulinette-path ./moulinette --env-file /path/to/.env
```

## Resources

- [Sandbox design](https://www.youtube.com/watch?v=sL_syMmRkoU)
- [`multiprocessing`](https://docs.python.org/3/library/multiprocessing.html) —
  process isolation and IPC for the sandbox
- [`pickle`](https://docs.python.org/3/library/pickle.html) /
  [`dill`](https://pypi.org/project/dill/) — namespace persistence between
  `execute()` calls
- [Model Context Protocol](https://modelcontextprotocol.io/) — the tool/resource/
  prompt protocol the sandbox speaks to the MCP servers
- [SWE-bench](https://www.swebench.com/) — the benchmark and its harness
  (`swebench` package, used by `moulinette/swebench/interact.py`)

### AI usage

On the **execution side (bclairot)**, AI was used as a search engine for documentation and code examples. It also helped me to test a lot, understanding the requirements, the constraints and  to be sure nothing was forgotten for the mandatory tasks of the project. Also generated a first draft of the README.md file, which was then improved and completed by me.

> **TODO (mobenais):** describe AI usage on the agent-loop / LLM-provider /
> benchmark side (which tasks, which parts).

## System Architecture

```
   ┌───────────────── Agent side (mobenais) ──────────┐   ┌──────── Execution side (bclairot) ────┐
   │                                                  │   │                                       │
   │  agent_mbpp / agent_swebench (CLI)               │   │   Sandbox                             │
   │             │                                    │   │    ├─ security (imports, FS,          │
   │  AgentLoop ─┼─ LLM provider (Gemini / Groq)      │   │    │   network, timeout, RAM)         │
   │             ├─ extract_code()                    │   │    ├─ final_answer()                  │
   │             └─ system prompt                     │   │    ├─ REPL `uv run sandbox`           │
   │                                                  │   │    ├─ get_manual()                    │
   │             ┌────── interface contract ──────────┼───┤    └─ MCPClient (stdio + HTTP)        │
   │             │                                    │   │                                       │
   │   sandbox.execute(code) ─────────────────────────┼──►│   mcp_tools_mbpp.py                   │
   │   sandbox.get_manual() ──────────────────────────┼──►│   mcp_tools_swebench.py               │
   │   ◄──────────────────────────── ExecutionResult  │   │   DockerManager                       │
   └──────────────────────────────────────────────────┘   └───────────────────────────────────────┘
```

The two sides only ever talk to each other through `Sandbox.execute()`,
`Sandbox.get_manual()`, and `Sandbox.close()` — the agent loop never knows which
MCP server is connected or what tools it exposes; the sandbox's manual (fed into
the LLM's system prompt) is generated dynamically from the connected server's
`list_tools()` at runtime.

## Agent Loop

`src/agent_loop.py`'s `AgentLoop.run(task_id, benchmark, user_prompt)` drives the
Thought → Code → Observation loop:

1. Sends the conversation so far to the current LLM provider (`GeminiLLM` or
   `GroqLLM`, `schemas/llmclass.py`).
2. Extracts the last fenced ` ```python ` block from the response
   (`extract_code`, `schemas/tools_agent.py`).
3. Runs it through `sandbox.execute(code)` and appends the result as the next
   `observation` message.
4. Stops when `execute()` returns a `final_answer`, or when a limit is hit
   (`check_budget`: input/output tokens, wall time; iteration count in the `for`
   loop itself) — each stop condition raises a dedicated `AgentLoopError` subclass
   that `run()` turns into a `SolutionOutput(success=False, error=...)` instead of
   crashing.
5. On a `429` from the provider, rotates through multiple API keys
   (`GEMINI_API_KEYS`/`GROQ_API_KEYS`, comma-separated) before falling back to a
   different model in the same provider's pool, then the other provider.
6. On `Ctrl+C` or an unexpected exception mid-loop, backs up token counters and the
   running context to `backup_memory/backup.json` before propagating/recording the
   error, so a crashed run's usage isn't silently lost.

Every step is recorded as a `StepMetrics` (`llm_output`, `sandbox_input`,
`sandbox_output`, token counts, timing, retries), and the whole run is returned as
a `SolutionOutput` — this is the trace the evaluator inspects to confirm the agent
solved the task through genuine tool use rather than a memorized answer.

**TODO (mobenais): A remplir**

## Sandbox Design

`src/sandbox/` (`core.py`, `security.py`, `namespace.py`, `mcp_bridge.py`, `cli.py`)
implements `class Sandbox`, satisfying the shared `SandboxProtocol`:
`execute(code) -> ExecutionResult`, `get_manual() -> str`, `close()`.

**Isolation choice: a fresh `multiprocessing.Process` per `execute()` call**, not
in-process `exec()`. In-process execution makes a hard timeout and memory limit
hard to enforce cleanly (you can't reliably interrupt arbitrary running Python from
outside itself); a real OS process gives a real boundary — `SIGTERM` on timeout, a
hard `RLIMIT_AS`/`RLIMIT_NPROC`/`RLIMIT_NOFILE` via `resource.setrlimit` — at the
cost of having to carry state across calls explicitly. That state (the Python
namespace) is serialized with `dill` (handles closures/functions `pickle` can't)
and restored into the next process, which is how "variables persist between
`execute()` calls" is implemented despite each call being a brand-new process.

**Security layers, all stdlib-only** (no `RestrictedPython` or similar, as
required):
- **Imports** — `_restricted_import` (`security.py`) replaces `__import__` with an
  allowlist check (`SandboxConfig.authorized_imports`, supporting `"pkg.*"`
  wildcards), and strips unauthorized submodules pulled in via `from x import y`.
- **Filesystem** — `_restricted_open` wraps `open()`: resolves the path with
  `os.path.realpath` *before* comparing it against `allowed_directories`, so a
  traversal like `/testbed/../etc/passwd` can't escape the allowlist.
- **Network** — `socket.socket` is replaced with a call that always raises, inside
  the worker process only.
- **Builtins** — the child's namespace only exposes an explicit allowlist of
  builtins (`namespace.py`); dangerous ones (`eval`, `exec`, `compile`, `open`,
  `__import__`, `input`, `breakpoint`, `globals`, `help`) are removed or
  overridden, and attribute-based sandbox escapes (e.g.
  `().__class__.__bases__[0].__subclasses__()`) are rejected at parse time.
- **Timeout / memory** — enforced by the parent (`p.join(timeout=...)`, then
  `terminate()`/`kill()`) and by `resource.setrlimit(RLIMIT_AS, ...)` inside the
  child, respectively.
- `KeyboardInterrupt`/`SystemExit` are always re-raised, never swallowed by the
  generic error handler.

**`final_answer(value)`** is injected into every sandbox namespace regardless of
which MCP server is connected — it is *not* an MCP tool. It works by raising an
internal `_FinalAnswer` exception that `execute()` catches and turns into
`ExecutionResult.final_answer`.

**MCP bridge** (`mcp_bridge.py`): the MCP client (`src/mcp_client.py`,
`src/mcp_sync_client.py`) and its event loop live in the **parent** process, never
in the sandboxed child — tool calls cross a `Queue` to a bridge thread in the
parent, which is why MCP tool actions are *not* subject to the sandbox's own
timeout (a tool like `run_command` can legitimately take longer than the code that
called it). Each request/response pair is tagged with a `generation_nb` so a
response arriving after its child was already killed on timeout can't be
misrouted into the next call. Every tool from the connected server becomes a
Python function in the sandbox namespace via `_make_tool_proxy`, with no tool name
ever hardcoded — connecting a different MCP server changes the available
functions and the generated manual (`get_manual()`) automatically.

> **TODO (bclairot):**
> - Only `open()` is wrapped for filesystem access — `os.open`, `pathlib.Path.open`
>   and `shutil.*` can still bypass the directory allowlist.
> - Only `socket.socket` is neutralized for network access — not yet verified
>   whether `socket.create_connection` is covered as a side effect.
> - 2 of the 5 mandatory `ExecutionResult.error` feedback cases aren't wired up
>   yet ("no valid code block found", "malformed block interpreted anyway").

## Tool Implementation Details

### MBPP (`mcp_tools_mbpp.py`)

One mandatory tool, `run_tests(code, test_list=None)`: runs the candidate solution
against each assertion in a separate `multiprocessing.Process` (same isolation
rationale as the sandbox itself), under a wall-clock timeout via `SIGTERM`, and
returns `{"success": bool, "output": str}` as JSON — `output` holds the first
failing assertion plus captured stdout/stderr, truncated with an explicit notice
past `max_std_length`. A `check_syntax(code)` tool is included as an extra, so the
agent can catch a `SyntaxError` before spending an iteration on a failed test run.

### SWE-bench (`mcp_tools_swebench.py` + `src/docker_manager.py`)

All 9 mandatory tools, backed by one long-lived Docker container per server
instance (`DockerManager`, `containers.run(image, command="tail -f /dev/null",
detach=True)`), so state — file edits, git history — persists across the whole
task the same way it would inside a real terminal session:

- **Filesystem**: `read_file`/`edit_file`/`list_files`. `read_file` mirrors
  `cat -n`. `edit_file` requires `old_str` to occur in the file exactly once
  (counted in Python on the raw file content, not a regex substitution), and
  writes back via `container.put_archive` (a tar archive over the Docker API) —
  not a shell command — since arbitrary source code routinely contains characters
  that break naive shell quoting.
- **Search**: `search_code`/`search_function_or_class_definition_in_code`/
  `find_references`, all `grep`-based, run from the repository root so paths come
  out absolute, exclude `.git/` and binary files, and reformat grep's
  `path:line:content` into the subject's required `path:line content`.
  `find_references` searches the whole repository and excludes only the exact
  `file:line` of the definition site, not just any line sharing that number.
- **Execution**: `run_tests()` runs the task's `eval_script` (its literal bash
  content, not a path to it); `get_patch()` is exactly
  `git -c core.fileMode=false diff` (the `-c core.fileMode=false` avoids
  Docker-induced file-permission noise polluting the diff); `run_command(command,
  workdir)` returns stdout, stderr and exit code together.
- Every command inside the container runs as
  `timeout {N}s bash -c "<command>"` — a relative `workdir` (including the
  implicit default) is resolved against the repository root before being sent to
  Docker, which otherwise rejects a relative working directory outright.
- The repository root itself is read from the **`TESTBED_PATH`** environment
  variable (set by the moulinette before the server starts, per the subject), not
  guessed from the Docker image.
- `cleanup()` (stop + remove the container) is wired to `SIGTERM`/`SIGINT` so it
  still runs if the evaluator force-kills the process on timeout, not just on a
  clean exit.

The local `docker/testbed.Dockerfile` + `scripts/docker_testbed.py` build a
throwaway stand-in image (a tiny git repo with one seeded bug) so the 9 tools can
be developed and smoke-tested (`scripts/test_mcp_swebench.py`) without pulling a
multi-GB real SWE-bench image.

## Benchmark Results and Analysis

> **TODO (mobenais, ablation bclairot): A remplir**
