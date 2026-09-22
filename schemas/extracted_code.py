"""Code extracted from an LLM response."""

from pydantic import BaseModel, Field


class ExtractedCode(BaseModel):
    """Python code taken from an LLM response, and how it was obtained."""

    code: str = Field(..., description="Python code ready for the sandbox")
    format: str = Field(..., description="Detected format: python, xml, "
                        "hermes, react")
    note: str | None = Field(default=None, description="Explanation sent "
                             "back to the LLM when the response was "
                             "converted or repaired")
