import os
from pathlib import Path

# Constantes globales du lot agent -- un seul endroit pour les regler.


PROJECT_ROOT = Path(__file__).resolve().parent.parent

MBPP_MAX_ITERATIONS = 10
MBPP_MAX_INPUT_TOKENS = 6_000
MBPP_MAX_OUTPUT_TOKENS = 1_500
MBPP_MAX_WALL_TIME_SECONDS = 120
MBPP_MCP_SERVER = PROJECT_ROOT / "mcp_tools_mbpp.py"


MAX_TOKENS_PAR_REQUETE = 2048

DEFAULT_TEMPERATURE = 0.0


MAX_CONSECUTIVE_ERRORS = 3
STATUS_BASCULE = {404, 408, 429, 500, 502, 503, 504}
MAX_MANUAL_CHARS = 700

LAST_ITER_INTACTS = 10
MAX_OBS_CHARS = 500
CHARS_PAR_TOKEN = 4
MARGE_BUDGET = 0.9

BACKUP_DIR = PROJECT_ROOT / "backup_memory"
BACKUP_FILE = BACKUP_DIR / "backup.json"


# FORCE_429_MODELS = {
#     m.strip() for m in os.environ.get("FORCE_429_MODELS", "").split(",") if m.strip()
# }
# DEBUG_BASCULE = os.environ.get("DEBUG_BASCULE", "") not in ("", "0")


SYSTEM_PROMPT = """You solve programming tasks by writing Python.
At each step, write a single Python code block inside a ```py fence.
Use print() to inspect intermediate values.
Variables persist from one step to the next.
When you have the definitive answer, call final_answer(value).
Always write in English.
"""


GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"


AUTHORIZED_GROQ = [
    "openai/gpt-oss-20b",
    "openai/gpt-oss-120b",
    "qwen/qwen3.8-27b",
    "groq/compound",
    "groq/compound-mini"
]
AUTHORIZED_GEMINI = [
    "gemini-3.7-flash", 
    "gemini-3.6-flash",
    "gemini-3.5-flash",
    "gemini-3.5-flash-lite"
]

AUTHORIZED_LLM = AUTHORIZED_GROQ + AUTHORIZED_GEMINI


RELAIS_MODELE = (
    "You are taking over an ongoing task from another model. "
    "The conversation above is your own history: continue from it, "
    "keep the same output format, and do not restart from scratch."
)



END_CODE = "<end_code>"
STOP_SEQUENCES = [END_CODE]


SYSTEM_PROMPT_MBPP = """\
You write one Python function, verify it against the given tests, and return \
its source. You work in a stateful Python sandbox: variables persist between \
your steps.

Reply with exactly one Thought line, then one code block. Nothing after the \
block. The sandbox runs the code and answers with an Observation.

Thought: <one line: what you do now and why>
Code:
```py
<python>
```<end_code>

Rules:
- You only see what you print(). Print every value you claim to check.
- Define the function first, then run the given tests in the same block.
- Call final_answer(src) only after you have SEEN the tests pass, where src \
is the function source as a string.
- On a failure, print the actual value beside the expected one, change only \
what that difference shows, and re-run. Never rewrite the whole function.

Example:
Thought: I define the function and run the two given tests.
Code:
```py
def add(a, b):
    return a + b
print(add(2, 3), add(-1, 1))
```<end_code>
Observation: 5 0
Thought: Both match what the tests expect, so I return the source.
Code:
```py
final_answer("def add(a, b):\\n    return a + b")
```<end_code>
"""

def create_newcontext(current_context: str, original_prompt: str, max_chars: int = 1200) -> str:
    ctx = current_context[-max_chars:]
    if len(current_context) > max_chars:
        ctx = "[...truncated...]\n" + ctx
    return (
        "You are taking over from another assistant that was interrupted mid-task.\n"
        f"Original task: {original_prompt}\n"
        f"Last output it produced (possibly incomplete):\n{ctx}\n"
        "Continue from there, in the same format. Do not restart from scratch "
        "and do not mention this handover."
    )


def extract_code(text: str) -> str | None:
    """Retourne le dernier bloc de code, ou None s'il n'y en a pas."""
    parts = text.split("```")

    if len(parts) < 3:
        return None

    block = parts[-2]

    first, sep, rest = block.partition("\n")
    if sep and first.strip().lower() in ("python", "py", "python3"):
        block = rest

    return block.strip()

