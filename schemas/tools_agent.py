from .llmclass import GeminiLLM, GroqLLM

AUTHORIZED_GROQ = [
    "openai/gpt-oss-20b",
    "openai/gpt-oss-120b",
    "qwen/qwen3.6-27b",
    "qwen/qwen3.8-27b",
    "groq/compound",
    "groq/compound-mini",
]
AUTHORIZED_GEMINI = [
    "gemini-3.7-flash", 
    "gemini-3.6-flash",
    "gemini-3.5-flash",
    "gemini-3.5-flash-lite",
    "gemini-3.1-flash-lite",
    "gemini-3-flash-preview",
    "gemini-flash-latest",
    "gemini-flash-lite-latest",
]

AUTHORIZED_LLM = AUTHORIZED_GROQ + AUTHORIZED_GEMINI



def extract_code(text: str) -> str | None:
    """Retourne le dernier bloc de code, ou None s'il n'y en a pas."""
    parts = text.split("```")

    if len(parts) < 3:
        return None

    return parts[-2].strip()


def check_llm(llm: GroqLLM | GeminiLLM, model: str):
    if model not in AUTHORIZED_LLM:
        raise ValueError(f"'{model}' is not an authorized model. Check AUTHORIZED_LLM for the allowed list.")

    if model in AUTHORIZED_GROQ:
        expected_provider = GroqLLM
    else:
        expected_provider = GeminiLLM

    if not isinstance(llm, expected_provider):
        raise ValueError(
            f"'{model}' belongs to {expected_provider.__name__}, but the llm passed in is a {type(llm).__name__}."
        )
