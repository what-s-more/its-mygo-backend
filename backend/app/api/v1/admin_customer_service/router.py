from fastapi import APIRouter, Depends

from app.core.dependencies import DbSession, get_current_admin
from app.models.user import AdminUser
from app.schemas.customer_service import CustomerServiceMessageCreateRequest
from app.services.customer_service import customer_service
from app.utils.response import ApiResponse, success

router = APIRouter()


@router.get("/conversations", response_model=ApiResponse[dict])
async def list_conversations(
    db: DbSession,
    current_admin: AdminUser = Depends(get_current_admin),
    status: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> ApiResponse[dict]:
    conversations, total = await customer_service.list_admin_conversations(
        db,
        current_admin,
        status=status,
        page=page,
        page_size=page_size,
    )
    return success({"list": [item.model_dump() for item in conversations], "page": page, "page_size": page_size, "total": total})


@router.get("/conversations/{conversation_id}/messages", response_model=ApiResponse[dict])
async def list_messages(
    conversation_id: int,
    db: DbSession,
    current_admin: AdminUser = Depends(get_current_admin),
    page: int = 1,
    page_size: int = 50,
) -> ApiResponse[dict]:
    messages, total = await customer_service.list_messages(
        db,
        conversation_id,
        admin=current_admin,
        page=page,
        page_size=page_size,
    )
    return success({"list": [item.model_dump() for item in messages], "page": page, "page_size": page_size, "total": total})


@router.post("/conversations/{conversation_id}/messages", response_model=ApiResponse[dict])
async def send_message(
    conversation_id: int,
    payload: CustomerServiceMessageCreateRequest,
    db: DbSession,
    current_admin: AdminUser = Depends(get_current_admin),
) -> ApiResponse[dict]:
    message = await customer_service.send_admin_message(db, current_admin, conversation_id, payload)
    return success(message.model_dump())


@router.post("/conversations/{conversation_id}/close", response_model=ApiResponse[dict])
async def close_conversation(
    conversation_id: int,
    db: DbSession,
    current_admin: AdminUser = Depends(get_current_admin),
) -> ApiResponse[dict]:
    conversation = await customer_service.close_conversation(db, current_admin, conversation_id)
    return success(conversation.model_dump())
