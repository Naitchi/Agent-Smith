"""Authorized models, debug flags and extraction of code from LLM answers."""

import ast
import json
import keyword
import os
from typing import Any

from ..extracted_code import ExtractedCode
from .prompts import END_CODE

FORCE_429_MODELS = {
    model.strip()
    for model in os.environ.get("FORCE_429_MODELS", "").split(",")
    if model.strip()
}
DEBUG_FALLBACK = os.environ.get("DEBUG_FALLBACK", "") not in ("", "0")
NO_FALLBACK = os.environ.get("NO_FALLBACK", "") not in ("", "0")

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
GEMINI_API_URL = ("https://generativelanguage.googleapis.com/v1beta/openai/"
                  "chat/completions")
MISTRAL_API_URL = "https://api.mistral.ai/v1/chat/completions"

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
AUTHORIZED_MISTRAL = [
    "codestral-2508",
    "ministral-14b-2512",
    "ministral-8b-2512",
    "ministral-3b-2512",
]
AUTHORIZED_LLM = AUTHORIZED_GROQ + AUTHORIZED_GEMINI + AUTHORIZED_MISTRAL

PYTHON_FENCE_LANGS = {
    "", "python", "py", "python3", "py3", "ipython", "tool_code"}


def create_newcontext(current_context: str, original_prompt: str,
                      max_chars: int = 1200) -> str:
    """Build the handover note given to a model taking over the task."""
    tail = current_context[-max_chars:]
    if len(current_context) > max_chars:
        tail = "[...truncated...]\n" + tail
    return (
        "You are taking over from another assistant that was interrupted "
        "mid-task.\n"
        f"Original task: {original_prompt}\n"
        f"Last output it produced (possibly incomplete):\n{tail}\n"
        "Continue from there, in the same format. Do not restart from scratch "
        "and do not mention this handover."
    )


def fence_open(line: str) -> tuple[str, str] | None:
    """Return (fence, language) if `line` opens a code block, else None."""
    stripped = line.strip()
    char = stripped[:1]
    if char not in ("`", "~"):
        return None
    fence = char * (len(stripped) - len(stripped.lstrip(char)))
    if len(fence) < 3:
        return None
    words = stripped[len(fence):].split()
    return fence, (words[0].lower() if words else "")


def read_label(line: str, label: str) -> str | None:
    """Return the text after `label:` when the line starts with it."""
    head, colon, rest = line.partition(":")
    if colon and " ".join(head.split()) == label:
        return rest.strip()
    return None


def find_named_tag(text: str, tag: str, pos: int) -> tuple[str, int] | None:
    """Find the next <tag name="..."> from `pos`; return (name, end)."""
    while (start := text.find("<" + tag, pos)) != -1:
        pos = start + len(tag) + 1
        close = text.find(">", pos)
        if close == -1:
            return None
        attrs = text[pos:close]
        key, equal, value = attrs.partition("=")
        value = value.strip()
        if (attrs[:1].isspace() and key.strip() == "name" and equal
                and len(value) >= 2 and value[0] == value[-1] == '"'):
            return value[1:-1], close + 1
    return None


def to_python_call(name: str, args: Any = None) -> str:
    """Turn a tool call into Python that prints its result."""
    name = name.rsplit(".", 1)[-1]
    if not name.isidentifier() or keyword.iskeyword(name):
        raise ValueError(f"invalid tool name: {name!r}")
    if args is None:
        parts: list[str] = []
    elif isinstance(args, dict):
        for key in args:
            if not str(key).isidentifier():
                raise ValueError(f"invalid argument name: {key!r}")
        parts = [f"{key}={value!r}" for key, value in args.items()]
    elif isinstance(args, list):
        parts = [repr(value) for value in args]
    else:
        parts = [repr(args)]
    return f"result = {name}({', '.join(parts)})\nprint(result)"


def xml_param_value(raw: str) -> Any:
    """Parse an XML parameter as JSON when possible, else keep the string."""
    stripped = raw.strip()
    if (stripped[:1] in "[{-0123456789"
            or stripped in ("true", "false", "null")):
        try:
            return json.loads(stripped)
        except ValueError:
            pass
    return raw.strip("\n")


def tool_call_from_json(obj: Any) -> tuple[str, Any] | None:
    """Return (name, arguments) of a JSON tool call, or None."""
    if not isinstance(obj, dict) or not isinstance(obj.get("name"), str):
        return None
    args = obj.get("arguments", obj.get("parameters"))
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except ValueError:
            pass
    return obj["name"], args


def is_valid_python(code: str) -> bool:
    try:
        ast.parse(code)
    except SyntaxError:
        return False
    return True


def split_blocks(text: str) -> list[tuple[str, str, bool]]:
    """Return every fenced block as (language, code, closed)."""
    blocks = []
    lines = text.splitlines(keepends=True)
    i = 0
    while i < len(lines):
        opening = fence_open(lines[i])
        if opening is None:
            i += 1
            continue
        fence, lang = opening
        start = i + 1
        ends = [j for j in range(start, len(lines))
                if lines[j].strip() == fence]
        if not ends:
            blocks.append((lang, "".join(lines[start:]), False))
            break
        end = ends[0]
        if lang in PYTHON_FENCE_LANGS:
            end = next((j for j in ends
                        if is_valid_python("".join(lines[start:j]))), end)
        blocks.append((lang, "".join(lines[start:end]), True))
        i = end + 1
    return blocks


def extract_python_block(text: str) -> ExtractedCode | None:
    """Last Python block, an unclosed one, or a ```json tool call."""
    blocks = split_blocks(text)
    for lang, code, closed in reversed(blocks):
        if lang in PYTHON_FENCE_LANGS and code.strip():
            note = None
            if not closed:
                note = ("Your code block was not closed; everything after "
                        "the opening fence was run as Python.")
            return ExtractedCode(code=code.strip("\n"), format="python",
                                 note=note)

    for lang, code, _ in reversed(blocks):
        if lang != "json":
            continue
        try:
            call = tool_call_from_json(json.loads(code))
        except ValueError:
            call = None
        if call is None:
            continue
        try:
            return ExtractedCode(
                code=to_python_call(*call), format="hermes",
                note="Your ```json block was read as a tool call and "
                     "converted to a Python call.")
        except ValueError:
            pass
    return None


def extract_xml_call(text: str) -> ExtractedCode | None:
    """Convert every <invoke name=...> XML tool call to Python."""
    calls = []
    pos = 0
    while (invoke := find_named_tag(text, "invoke", pos)) is not None:
        name, body_start = invoke
        body_end = text.find("</invoke>", body_start)
        if body_end == -1:
            body_end = len(text)
        body = text[body_start:body_end]
        pos = body_end + len("</invoke>")

        args = {}
        param_pos = 0
        while (param := find_named_tag(body, "parameter",
                                       param_pos)) is not None:
            param_name, value_start = param
            value_end = body.find("</parameter>", value_start)
            if value_end == -1:
                break
            args[param_name] = xml_param_value(body[value_start:value_end])
            param_pos = value_end + len("</parameter>")
        try:
            calls.append(to_python_call(name, args))
        except ValueError:
            return None
    if not calls:
        return None
    return ExtractedCode(code="\n".join(calls), format="xml",
                         note="Your XML <invoke> tool call was converted to "
                              "a Python call.")


def extract_hermes_call(text: str) -> ExtractedCode | None:
    """Convert every <tool_call>{json}</tool_call> to Python."""
    decoder = json.JSONDecoder()
    calls = []
    pos = 0
    while (start := text.find("<tool_call>", pos)) != -1:
        pos = start + len("<tool_call>")
        json_start = len(text) - len(text[pos:].lstrip())
        try:
            obj, _ = decoder.raw_decode(text, json_start)
        except ValueError:
            continue
        call = tool_call_from_json(obj)
        if call is None:
            continue
        try:
            calls.append(to_python_call(*call))
        except ValueError:
            return None
    if not calls:
        return None
    return ExtractedCode(code="\n".join(calls), format="hermes",
                         note="Your <tool_call> JSON was converted to a "
                              "Python call.")


def extract_react_call(text: str) -> ExtractedCode | None:
    """Convert the last ReAct Action / Action Input pair to Python."""
    lines = text.splitlines()
    found = None
    for i in range(len(lines) - 1):
        name = read_label(lines[i], "Action")
        first = read_label(lines[i + 1], "Action Input")
        if (not name or first is None
                or not name.replace(".", "_").isidentifier()):
            continue
        body = [first]
        for line in lines[i + 2:]:
            if any(read_label(line, label) is not None
                   for label in ("Observation", "Thought", "Action")):
                break
            body.append(line)
        found = (name, "\n".join(body))
    if found is None:
        return None
    name, raw = found
    raw = raw.strip()
    if raw.startswith("```"):
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
                         note="Your ReAct Action / Action Input was "
                              "converted to a Python call.")


def extract_unfenced_code(text: str) -> ExtractedCode | None:
    """Python written after a bare `Code:` line, if it parses."""
    lines = text.splitlines(keepends=True)
    label = next((i for i, line in enumerate(lines)
                  if read_label(line, "Code") == ""), None)
    if label is None:
        return None
    code = "".join(lines[label + 1:]).strip("\n")
    if not code.strip() or not is_valid_python(code):
        return None
    return ExtractedCode(code=code, format="python",
                         note="No code fence found; the text after 'Code:' "
                              "was run as Python. Wrap your code in "
                              "```py ... ```.")


def extract_code(text: str) -> ExtractedCode | None:
    """Extract the code to run from an LLM answer, whatever its format."""
    text = text.replace(END_CODE, "")
    for extractor in (extract_python_block, extract_xml_call,
                      extract_hermes_call, extract_react_call,
                      extract_unfenced_code):
        extracted = extractor(text)
        if extracted is not None:
            return extracted
    return None
