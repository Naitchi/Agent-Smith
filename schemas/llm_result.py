from pydantic import BaseModel


class LLMResult(BaseModel):
    """Result of a single LLM completion call."""

    text: str
    input_tokens: int
    output_tokens: int
    latency_ms: float
    model_name: str = ""
    api_url: str = ""
