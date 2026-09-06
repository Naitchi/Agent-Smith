SYSTEM_PROMPT = """Tu résous des tâches de programmation en écrivant du Python.
À chaque étape, écris un unique bloc de code Python dans une fence ```py.
Utilise print() pour observer les valeurs intermédiaires.
Les variables persistent d'une étape à l'autre.
Quand tu as la réponse définitive, appelle final_answer(valeur) toute tres reponse doivent etre en anglais.
"""


GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"

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

def create_newcontext(current_context: str, original_prompt: str) -> str:
    return (f"You the  next one llm that i use the original prompt is '{original_prompt}'\
            can you complete that reponse from previous llm :{current_context}. \
                take his behaviour and don't add parasite words")



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

