"""Boucle ReAct : générer du code, l'exécuter, observer, recommencer."""
from .parsing import extract_code
from schemas import GeminiLLM, GroqLLM, SandboxConfig
from ..sandbox import Sandbox
import httpx

SYSTEM = """Tu résous des tâches de programmation en écrivant du Python.
À chaque étape, écris un unique bloc de code Python dans une fence ```py.
Utilise print() pour observer les valeurs intermédiaires.
Les variables persistent d'une étape à l'autre.
Quand tu as la réponse définitive, appelle final_answer(valeur).
"""

# MODEL_GROQ = "openai/gpt-oss-20b"
# MODEL_GEMINI = "gemini-3.5-flash-lite"

# Listes verifiees le 2026-08-28 par un vrai appel /chat/completions.
# Attention : l'endpoint /models liste des modeles qui repondent 404 a
# l'usage ("no longer available to new users"), il ne fait pas foi.
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

AUTHORIZED_LLM: list[str] = []
AUTHORIZED_LLM.extend(AUTHORIZED_GROQ)
AUTHORIZED_LLM.extend(AUTHORIZED_GEMINI)


def run(task: str, llm: GroqLLM | GeminiLLM, model: str, max_steps: int = 6):
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

    sandbox = Sandbox(SandboxConfig())
    messages = [{"role": "user", "content": task}]
    try:
        for step in range(1, max_steps + 1):
            reply = llm(SYSTEM, messages)
            messages.append({"role": "assistant", "content": reply.text})

            code = extract_code(reply.text)
            if code is None:
                messages.append({
                    "role": "user",
                    "content": "Réponds avec un bloc de code ```py.",
                })
                continue

            print(f"--- step {step} ---\n{code}\n")
            result = sandbox.execute(code)

            if result.final_answer is not None:
                return result.final_answer

            observation = result.stdout or result.error or "(aucune sortie)"
            messages.append({
                "role": "user",
                "content": f"Observation:\n{observation}",
            })

        return None
    except httpx.HTTPStatusError as e:
        print(f"Appel LLM échoué ({e.response.status_code}): {e.response.text}")
    finally:
        sandbox.close()


if __name__ == "__main__":
    llm = GroqLLM(MODEL_GROQ)
    print(run(
        "Calcule la somme des nombres premiers < 100.",
        llm=llm,
        model=MODEL_GROQ,
    ))
