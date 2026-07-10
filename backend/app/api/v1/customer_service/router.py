from fastapi import APIRouter, Depends

from app.core.dependencies import DbSession, get_current_user
from app.models.user import User
from app.schemas.customer_service import CustomerServiceConversationCreateRequest, CustomerServiceMessageCreateRequest
from app.services.customer_service import customer_service
from app.utils.response import ApiResponse, success

router = APIRouter()


@router.post("/conversations", response_model=ApiResponse[dict])
async def create_conversation(
    payload: CustomerServiceConversationCreateRequest,
    db: DbSession,
    current_user: User = Depends(get_current_user),
) -> ApiResponse[dict]:
    conversation = await customer_service.create_or_get_conversation(db, current_user, payload)
    return success(conversation.model_dump())


@router.get("/conversations", response_model=ApiResponse[dict])
async def list_conversations(
    db: DbSession,
    current_user: User = Depends(get_current_user),
    status: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> ApiResponse[dict]:
    conversations, total = await customer_service.list_user_conversations(
        db,
        current_user,
        status=status,
        page=page,
        page_size=page_size,
    )
    return success({"list": [item.model_dump() for item in conversations], "page": page, "page_size": page_size, "total": total})


@router.get("/conversations/{conversation_id}/messages", response_model=ApiResponse[dict])
async def list_messages(
    conversation_id: int,
    db: DbSession,
    current_user: User = Depends(get_current_user),
    page: int = 1,
    page_size: int = 50,
) -> ApiResponse[dict]:
    messages, total = await customer_service.list_messages(
        db,
        conversation_id,
        user=current_user,
        page=page,
        page_size=page_size,
    )
    return success({"list": [item.model_dump() for item in messages], "page": page, "page_size": page_size, "total": total})


@router.post("/conversations/{conversation_id}/messages", response_model=ApiResponse[dict])
async def send_message(
    conversation_id: int,
    payload: CustomerServiceMessageCreateRequest,
    db: DbSession,
    current_user: User = Depends(get_current_user),
) -> ApiResponse[dict]:
    message = await customer_service.send_user_message(db, current_user, conversation_id, payload)
    return success(message.model_dump())


@router.delete("/conversations/{conversation_id}", response_model=ApiResponse[dict])
async def delete_conversation(
    conversation_id: int,
    db: DbSession,
    current_user: User = Depends(get_current_user),
) -> ApiResponse[dict]:
    await customer_service.delete_user_conversation(db, current_user, conversation_id)
    return success({"id": conversation_id})
