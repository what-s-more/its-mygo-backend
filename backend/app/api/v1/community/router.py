from fastapi import APIRouter, Depends
from fastapi.security import HTTPAuthorizationCredentials

from app.api.v1.merchants.router import optional_consumer_user_id
from app.core.dependencies import DbSession, bearer_scheme, get_current_user
from app.models.user import User
from app.schemas.community import (
    CommentCreateRequest,
    CommentResponse,
    CommunityUserProfileResponse,
    FavoritePostItem,
    FavoriteToggleResponse,
    LikeToggleResponse,
    PostCreateRequest,
    PostResponse,
    TopicResponse,
)
from app.services.community_service import community_service
from app.utils.response import ApiResponse, success

router = APIRouter()


@router.get("/posts", response_model=ApiResponse[dict])
async def list_posts(
    db: DbSession,
    section: str | None = None,
    author_id: int | None = None,
    topic: str | None = None,
    page: int = 1,
    page_size: int = 20,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> ApiResponse[dict]:
    current_user_id = optional_consumer_user_id(credentials)
    posts, total = await community_service.list_posts(
        db,
        section=section,
        author_id=author_id,
        topic=topic,
        current_user_id=current_user_id,
        page=page,
        page_size=page_size,
    )
    return success({"list": [post.model_dump() for post in posts], "page": page, "page_size": page_size, "total": total})


@router.get("/topics", response_model=ApiResponse[list[TopicResponse]])
async def list_topics(db: DbSession, limit: int = 20) -> ApiResponse[list[TopicResponse]]:
    return success(await community_service.list_topics(db, limit=limit))


@router.get("/users/{user_id}", response_model=ApiResponse[CommunityUserProfileResponse])
async def get_community_user_profile(user_id: int, db: DbSession) -> ApiResponse[CommunityUserProfileResponse]:
    return success(await community_service.get_user_profile(db, user_id))


@router.get("/users/{user_id}/posts", response_model=ApiResponse[dict])
async def list_community_user_posts(
    user_id: int,
    db: DbSession,
    section: str | None = None,
    topic: str | None = None,
    page: int = 1,
    page_size: int = 20,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> ApiResponse[dict]:
    current_user_id = optional_consumer_user_id(credentials)
    posts, total = await community_service.list_posts(
        db,
        section=section,
        author_id=user_id,
        topic=topic,
        current_user_id=current_user_id,
        page=page,
        page_size=page_size,
    )
    return success({"list": [post.model_dump() for post in posts], "page": page, "page_size": page_size, "total": total})


@router.get("/posts/{post_id}", response_model=ApiResponse[PostResponse])
async def get_post(
    post_id: int,
    db: DbSession,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> ApiResponse[PostResponse]:
    current_user_id = optional_consumer_user_id(credentials)
    return success(await community_service.get_post(db, post_id, current_user_id=current_user_id))


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


@router.post("/posts/{post_id}/favorite", response_model=ApiResponse[FavoriteToggleResponse])
async def toggle_favorite(
    post_id: int,
    db: DbSession,
    current_user: User = Depends(get_current_user),
) -> ApiResponse[FavoriteToggleResponse]:
    result = await community_service.toggle_favorite(db, current_user, post_id)
    return success(FavoriteToggleResponse(**result))


@router.get("/favorite-posts", response_model=ApiResponse[dict])
async def list_favorite_posts(
    db: DbSession,
    current_user: User = Depends(get_current_user),
    page: int = 1,
    page_size: int = 20,
) -> ApiResponse[dict]:
    items, total = await community_service.list_favorite_posts(db, current_user, page=page, page_size=page_size)
    return success(
        {
            "list": [item.model_dump() for item in items],
            "page": page,
            "page_size": page_size,
            "total": total,
        }
    )


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
