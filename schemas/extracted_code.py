from pydantic import BaseModel, Field


class ExtractedCode(BaseModel):
    """Code Python tire d'une reponse LLM, et comment il a ete obtenu."""

    code: str = Field(..., description="Python pret pour la sandbox")
    format: str = Field(..., description="Format reconnu : python, xml, "
                        "hermes, react")
    note: str | None = Field(default=None, description="Explication a "
                             "renvoyer au LLM quand la reponse a ete "
                             "convertie ou interpretee malgre un defaut")
