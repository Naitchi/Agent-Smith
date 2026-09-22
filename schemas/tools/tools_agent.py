import ast
import json
import keyword
import os
from typing import Any

from ..extracted_code import ExtractedCode
from .prompts import END_CODE

# Logique partagee du lot agent, modeles autorises et drapeaux de debug.
# Les budgets sont dans `limits.py`, les prompts dans `prompts.py`.


FORCE_429_MODELS = {
    m.strip() for m in os.environ.get("FORCE_429_MODELS", "").split(",") if m.strip()
}
DEBUG_BASCULE = os.environ.get("DEBUG_BASCULE", "") not in ("", "0")
NO_BASCULE = os.environ.get("NO_BASCULE", "") not in ("", "0")


GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
MISTRAL_API_URL = "https://api.mistral.ai/v1/chat/completions"


# Modeles de texte accessibles en offre gratuite, verifies par un appel reel
# le 2026-09-22. Ecartes : groq/compound* (404), allam-2-7b (contexte 4k),
# gpt-oss-safeguard (classifieur), gemini-2.5-* (fermes aux nouveaux
# comptes), *-pro* (pas de quota gratuit), alias *-latest (doublons mouvants).
AUTHORIZED_GROQ = [
    "qwen/qwen3.8-27b",
    "openai/gpt-oss-120b",
    "openai/gpt-oss-20b",
]
AUTHORIZED_GEMINI = [
    "gemini-3.8-flash",
    "gemini-3.7-flash",
    "gemini-3.6-flash",
    "gemini-3.5-flash",
    "gemini-3.5-flash-lite",
    "gemini-3-flash-preview",
    "gemini-3.1-flash-lite",
    "gemma-4-31b-it",
    "gemma-4-26b-a4b-it",
]

# Mistral (offre gratuite Experiment), versions figees plutot que les alias
# *-latest. Ecartes : mistral-medium / mistral-small (429 sur toutes les cles,
# meme apres pause), leanstral (preuves Lean), voxtral (audio).
AUTHORIZED_MISTRAL = [
    "codestral-2508",
    "ministral-14b-2512",
    "ministral-8b-2512",
    "ministral-3b-2512",
]


# Ordre de bascule (src/agent_loop.py) : du plus fort au plus faible, dans
# chaque liste puis Groq, Gemini, Mistral.
AUTHORIZED_LLM = AUTHORIZED_GROQ + AUTHORIZED_GEMINI + AUTHORIZED_MISTRAL


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


PYTHON_FENCE_LANGS = {"", "python", "py", "python3", "py3", "ipython", "tool_code"}


def _fence_open(line: str) -> tuple[str, str] | None:
    """Ligne qui ouvre un bloc de code : (fence, langage), sinon None.

    "```python"       -> ("```", "python")
    "~~~~ py main.py" -> ("~~~~", "py")    le reste de la ligne est ignore
    """
    stripped = line.strip()
    char = stripped[:1]
    if char not in ("`", "~"):
        return None
    fence = char * (len(stripped) - len(stripped.lstrip(char)))
    if len(fence) < 3:
        return None
    words = stripped[len(fence):].split()
    return fence, (words[0].lower() if words else "")


def _label(line: str, label: str) -> str | None:
    """Texte apres `label:` si la ligne commence par ce label, sinon None.

    "Action: read_file"   avec "Action"       -> "read_file"
    "  Action  Input : x" avec "Action Input" -> "x"
    """
    head, colon, rest = line.partition(":")
    if colon and " ".join(head.split()) == label:
        return rest.strip()
    return None


def _named_tag(text: str, tag: str, pos: int) -> tuple[str, int] | None:
    """Prochaine balise `<tag name="...">` a partir de `pos`.

    Returns: (valeur de name, position juste apres le `>`), ou None.
    """
    while (start := text.find("<" + tag, pos)) != -1:
        pos = start + len(tag) + 1
        close = text.find(">", pos)
        if close == -1:
            return None
        attrs = text[pos:close]  # ' name="read_file"'
        key, equal, value = attrs.partition("=")
        value = value.strip()
        if (attrs[:1].isspace() and key.strip() == "name" and equal
                and len(value) >= 2 and value[0] == value[-1] == '"'):
            return value[1:-1], close + 1
    return None


def to_python_call(name: str, args: Any = None) -> str:
    """Traduit un appel d'outil en Python, resultat affiche.

    `result = read_file(filepath="/testbed/f.py")` suivi de `print(result)` :
    le modele ne voit que ce qui est imprime. `args` : dict -> arguments
    nommes, list -> positionnels, autre valeur -> un seul positionnel.
    `repr()` rend des litteraux Python valides pour tout ce que `json.loads`
    produit (True/None, et non true/null).

    Raises:
        ValueError: nom d'outil ou d'argument qui n'est pas un identifiant.
    """
    name = name.rsplit(".", 1)[-1]  # functions.read_file -> read_file
    if not name.isidentifier() or keyword.iskeyword(name):
        raise ValueError(f"invalid tool name: {name!r}")
    if args is None:
        parts: list[str] = []
    elif isinstance(args, dict):
        for key in args:
            if not str(key).isidentifier():
                raise ValueError(f"invalid argument name: {key!r}")
        parts = [f"{k}={v!r}" for k, v in args.items()]
    elif isinstance(args, list):
        parts = [repr(v) for v in args]
    else:
        parts = [repr(args)]
    return f"result = {name}({', '.join(parts)})\nprint(result)"


def _json_value(raw: str) -> Any:
    """Valeur d'un parametre XML : JSON si ca en est, sinon la chaine brute.

    Convention Anthropic : les chaines sont ecrites telles quelles, le reste
    (nombres, booleens, listes, objets) en JSON.
    """
    stripped = raw.strip()
    if stripped[:1] in "[{-0123456789" or stripped in ("true", "false", "null"):
        try:
            return json.loads(stripped)
        except ValueError:
            pass
    return raw.strip("\n")


def _tool_json(obj: Any) -> tuple[str, Any] | None:
    """(nom, arguments) d'un objet d'appel JSON, ou None si ce n'en est pas un.

    Accepte `arguments` ou `parameters`, en objet ou en chaine JSON (forme
    OpenAI, ou l'argument est serialise deux fois).
    """
    if not isinstance(obj, dict) or not isinstance(obj.get("name"), str):
        return None
    args = obj.get("arguments", obj.get("parameters"))
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except ValueError:
            pass
    return obj["name"], args


def _parses(code: str) -> bool:
    try:
        ast.parse(code)
    except SyntaxError:
        return False
    return True


def _extract_python(text: str) -> ExtractedCode | None:
    """Dernier bloc Python balise ; tolere un bloc non ferme en fin de texte."""
    blocks: list[tuple[str, str, bool]] = []  # (lang, code, ferme)
    lines = text.splitlines(keepends=True)
    i = 0
    while i < len(lines):
        opening = _fence_open(lines[i])
        if opening is None:
            i += 1
            continue
        fence, lang = opening
        start = i + 1
        ends = [j for j in range(start, len(lines)) if lines[j].strip() == fence]
        if not ends:
            blocks.append((lang, "".join(lines[start:]), False))
            break
        # Une ligne ``` peut vivre dans une chaine du code (src = '''...''') :
        # si le bloc ne se parse pas, on essaie la fence fermante suivante.
        end = ends[0]
        if lang in PYTHON_FENCE_LANGS:
            end = next((j for j in ends if _parses("".join(lines[start:j]))), end)
        blocks.append((lang, "".join(lines[start:end]), True))
        i = end + 1

    for lang, code, closed in reversed(blocks):
        if lang in PYTHON_FENCE_LANGS and code.strip():
            note = None
            if not closed:
                note = ("Your code block was not closed; everything after the "
                        "opening fence was run as Python.")
            return ExtractedCode(code=code.strip("\n"), format="python", note=note)


    for lang, code, _ in reversed(blocks):
        if lang == "json":
            try:
                call = _tool_json(json.loads(code))
            except ValueError:
                call = None
            if call is not None:
                try:
                    return ExtractedCode(
                        code=to_python_call(*call), format="hermes",
                        note="Your ```json block was read as a tool call and "
                             "converted to a Python call.")
                except ValueError:
                    pass
    return None


def _extract_xml(text: str) -> ExtractedCode | None:
    """`<invoke name=..><parameter name=..>..</parameter></invoke>`, un ou plusieurs."""
    calls = []
    pos = 0
    while (invoke := _named_tag(text, "invoke", pos)) is not None:
        name, body_start = invoke
        body_end = text.find("</invoke>", body_start)
        if body_end == -1: 
            body_end = len(text)
        body = text[body_start:body_end]
        pos = body_end + len("</invoke>")

        args = {}
        p = 0
        while (param := _named_tag(body, "parameter", p)) is not None:
            param_name, value_start = param
            value_end = body.find("</parameter>", value_start)
            if value_end == -1:
                break
            args[param_name] = _json_value(body[value_start:value_end])
            p = value_end + len("</parameter>")
        try:
            calls.append(to_python_call(name, args))
        except ValueError:
            return None
    if not calls:
        return None
    return ExtractedCode(code="\n".join(calls), format="xml",
                         note="Your XML <invoke> tool call was converted to a "
                              "Python call.")


def _extract_hermes(text: str) -> ExtractedCode | None:
    """`<tool_call>{"name": .., "arguments": {..}}</tool_call>`, un ou plusieurs.

    `raw_decode` lit un objet JSON et s'arrete a sa fin : la balise fermante
    peut manquer (coupee par la stop sequence `</tool_call>`).
    """
    decoder = json.JSONDecoder()
    calls = []
    pos = 0
    while (start := text.find("<tool_call>", pos)) != -1:
        pos = start + len("<tool_call>")
        json_start = len(text) - len(text[pos:].lstrip())  # saute les blancs
        try:
            obj, _ = decoder.raw_decode(text, json_start)
        except ValueError:
            continue
        call = _tool_json(obj)
        if call is None:
            continue
        try:
            calls.append(to_python_call(*call))
        except ValueError:
            return None
    if not calls:
        return None
    return ExtractedCode(code="\n".join(calls), format="hermes",
                         note="Your <tool_call> JSON was converted to a Python "
                              "call.")


def _extract_react(text: str) -> ExtractedCode | None:
    """Dernier `Action: outil` / `Action Input: ...` : JSON, sinon une chaine."""
    lines = text.splitlines()
    found = None  # (nom, input) du dernier appel
    for i in range(len(lines) - 1):
        name = _label(lines[i], "Action")
        first = _label(lines[i + 1], "Action Input")
        if not name or first is None or not name.replace(".", "_").isidentifier():
            continue
        # L'input continue jusqu'au prochain label ReAct ou la fin du texte.
        body = [first]
        for line in lines[i + 2:]:
            if any(_label(line, l) is not None for l in ("Observation", "Thought", "Action")):
                break
            body.append(line)
        found = (name, "\n".join(body))
    if found is None:
        return None
    name, raw = found
    raw = raw.strip()
    if raw.startswith("```"):  # Action Input: ```json {...} ```
        raw = raw.strip("`").removeprefix("json").strip()
    try:
        args = json.loads(raw) if raw else None
    except ValueError:
        args = raw
    try:
        code = to_python_call(name, args)
    except ValueError:
        return None
    return ExtractedCode(code=code, format="react",
                         note="Your ReAct Action / Action Input was converted to "
                              "a Python call.")


def _extract_unfenced(text: str) -> ExtractedCode | None:
    """`Code:` suivi de Python sans fence : repris seulement s'il se parse."""
    lines = text.splitlines(keepends=True)
    label = next((i for i, line in enumerate(lines) if _label(line, "Code") == ""), None)
    if label is None:
        return None
    code = "".join(lines[label + 1:]).strip("\n")
    if not code.strip() or not _parses(code):
        return None
    return ExtractedCode(code=code, format="python",
                         note="No code fence found; the text after 'Code:' was "
                              "run as Python. Wrap your code in ```py ... ```.")


def extract_code(text: str) -> ExtractedCode | None:
    """Tire le code a executer d'une reponse LLM, quel que soit son format.

    Formats du sujet : (a) bloc Python + `<end_code>`, (b) XML Anthropic,
    (c) JSON/Hermes, (d) ReAct ; plus ```tool_code (Gemini), ```json
    d'appel, bloc non ferme et `Code:` sans fence en secours.

    Returns:
        Le code et son format, avec une `note` pour le LLM des qu'il y a eu
        conversion ou interpretation ; None si rien d'exploitable.
    """
    text = text.replace(END_CODE, "")
    for extractor in (_extract_python, _extract_xml, _extract_hermes,
                      _extract_react, _extract_unfenced):
        extracted = extractor(text)
        if extracted is not None:
            return extracted
    return None
