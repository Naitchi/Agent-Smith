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
    "qwen/qwen3.6-27b",
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

