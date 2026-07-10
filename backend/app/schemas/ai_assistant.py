from pydantic import BaseModel, Field


class AiAssistantChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=1000)
    history: list[dict[str, str]] = Field(default_factory=list, max_length=20)


class AiAssistantChatResponse(BaseModel):
    reply: str
    provider: str = "preset"

