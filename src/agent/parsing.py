

def extract_code(text: str) -> str | None:
    """Retourne le dernier bloc de code, ou None s'il n'y en a pas."""
    parts = text.split("```")

    if len(parts) < 3:
        return None

    return parts[-2].strip()
