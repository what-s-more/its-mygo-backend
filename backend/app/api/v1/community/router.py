from fastapi import APIRouter, Depends

from app.core.dependencies import DbSession, get_current_user
from app.models.user import User
from app.schemas.community import (
    CommentCreateRequest,
    CommentResponse,
    LikeToggleResponse,
    PostCreateRequest,
    PostResponse,
)
from app.services.community_service import community_service
from app.utils.response import ApiResponse, success

router = APIRouter()


@router.get("/posts", response_model=ApiResponse[dict])
async def list_posts(
    db: DbSession,
    page: int = 1,
    page_size: int = 20,
) -> ApiResponse[dict]:
    posts, total = await community_service.list_posts(db, page=page, page_size=page_size)
    return success({"list": [post.model_dump() for post in posts], "page": page, "page_size": page_size, "total": total})


@router.get("/posts/{post_id}", response_model=ApiResponse[PostResponse])
async def get_post(post_id: int, db: DbSession) -> ApiResponse[PostResponse]:
    return success(await community_service.get_post(db, post_id))


@router.post("/posts", response_model=ApiResponse[PostResponse])
async def create_post(
    payload: PostCreateRequest,
    db: DbSession,
    current_user: User = Depends(get_current_user),
) -> ApiResponse[PostResponse]:
    return success(await community_service.create_post(db, current_user, payload))


@router.delete("/posts/{post_id}", response_model=ApiResponse[None])
async def delete_post(
    post_id: int,
    db: DbSession,
    current_user: User = Depends(get_current_user),
) -> ApiResponse[None]:
    await community_service.delete_own_post(db, current_user, post_id)
    return success(None)


@router.post("/posts/{post_id}/like", response_model=ApiResponse[LikeToggleResponse])
async def toggle_like(
    post_id: int,
    db: DbSession,
    current_user: User = Depends(get_current_user),
) -> ApiResponse[LikeToggleResponse]:
    result = await community_service.toggle_like(db, current_user, post_id)
    return success(LikeToggleResponse(**result))


@router.get("/posts/{post_id}/comments", response_model=ApiResponse[dict])
async def list_comments(
    post_id: int,
    db: DbSession,
    page: int = 1,
    page_size: int = 20,
) -> ApiResponse[dict]:
    comments, total = await community_service.list_comments(db, post_id, page=page, page_size=page_size)
    return success(
        {"list": [comment.model_dump() for comment in comments], "page": page, "page_size": page_size, "total": total}
    )


@router.post("/posts/{post_id}/comments", response_model=ApiResponse[CommentResponse])
async def create_comment(
    post_id: int,
    payload: CommentCreateRequest,
    db: DbSession,
    current_user: User = Depends(get_current_user),
) -> ApiResponse[CommentResponse]:
    return success(await community_service.create_comment(db, current_user, post_id, payload))
