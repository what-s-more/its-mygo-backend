from fastapi import APIRouter

from app.schemas.ai_assistant import AiAssistantChatRequest
from app.services.ai_assistant_service import ai_assistant_service
from app.utils.response import ApiResponse, success

router = APIRouter()


@router.post("/chat", response_model=ApiResponse[dict])
async def chat(payload: AiAssistantChatRequest) -> ApiResponse[dict]:
    response = await ai_assistant_service.chat(payload)
    return success(response.model_dump())

