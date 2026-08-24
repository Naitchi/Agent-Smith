"""Boucle ReAct : générer du code, l'exécuter, observer, recommencer."""
from .llm import groq_complete
from .parsing import extract_code
from schemas import SandboxConfig
from scripts.fake_sandbox import FakeSandbox as Sandbox


SYSTEM = """Tu résous des tâches de programmation en écrivant du Python.
À chaque étape, écris un unique bloc de code Python dans une fence ```py.
Utilise print() pour observer les valeurs intermédiaires.
Les variables persistent d'une étape à l'autre.
Quand tu as la réponse définitive, appelle final_answer(valeur).
"""

MODEL = "openai/gpt-oss-20b"


def run(task: str, max_steps: int = 6):
    sandbox = Sandbox(SandboxConfig())
    messages = [{"role": "user", "content": task}]
    try:
        for step in range(1, max_steps + 1):
            reply = groq_complete(MODEL, SYSTEM, messages)
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
    print(run("Calcule la somme des nombres premiers < 100."))
