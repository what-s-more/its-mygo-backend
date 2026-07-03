import json

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException, ForbiddenException
from app.models.community import CommunityComment, CommunityLike, CommunityPost
from app.models.order import Order, OrderItem
from app.models.user import User
from app.schemas.community import (
    AuthorSummary,
    CommentCreateRequest,
    CommentResponse,
    PostCreateRequest,
    PostResponse,
)


class CommunityService:
    async def create_post(self, db: AsyncSession, user: User, payload: PostCreateRequest) -> PostResponse:
        product_ids = list(dict.fromkeys(payload.product_ids))
        post = CommunityPost(
            user_id=user.id,
            type=payload.type,
            title=payload.title,
            content=payload.content,
            image_urls=json.dumps(payload.image_urls, ensure_ascii=False),
            product_ids=json.dumps(product_ids, ensure_ascii=False),
            topic_tags=json.dumps(payload.topic_tags, ensure_ascii=False),
            status="published",
        )
        db.add(post)
        await db.commit()
        await db.refresh(post)
        return await self._post_to_response(db, post)

    async def list_posts(
        self,
        db: AsyncSession,
        *,
        status: str = "published",
        page: int,
        page_size: int,
    ) -> tuple[list[PostResponse], int]:
        statement = select(CommunityPost).where(CommunityPost.status == status).order_by(CommunityPost.created_at.desc())
        all_result = await db.execute(statement)
        all_posts = list(all_result.scalars())
        result = await db.execute(statement.offset((page - 1) * page_size).limit(page_size))
        posts = list(result.scalars())
        return [await self._post_to_response(db, post) for post in posts], len(all_posts)

    async def get_post(self, db: AsyncSession, post_id: int) -> PostResponse:
        post = await self._get_post(db, post_id)
        if post.status != "published":
            raise AppException(40004, "帖子不存在", 404)
        return await self._post_to_response(db, post)

    async def delete_own_post(self, db: AsyncSession, user: User, post_id: int) -> None:
        post = await self._get_post(db, post_id)
        if post.user_id != user.id:
            raise ForbiddenException()
        post.status = "hidden"
        await db.commit()

    async def audit_post(self, db: AsyncSession, post_id: int, approved: bool) -> PostResponse:
        post = await self._get_post(db, post_id)
        post.status = "published" if approved else "hidden"
        await db.commit()
        await db.refresh(post)
        return await self._post_to_response(db, post)

    async def hide_post(self, db: AsyncSession, post_id: int) -> PostResponse:
        post = await self._get_post(db, post_id)
        post.status = "hidden"
        await db.commit()
        await db.refresh(post)
        return await self._post_to_response(db, post)

    async def toggle_like(self, db: AsyncSession, user: User, post_id: int) -> dict:
        post = await self._get_post(db, post_id)
        if post.status != "published":
            raise AppException(40008, "当前帖子状态不允许点赞")
        result = await db.execute(
            select(CommunityLike).where(CommunityLike.post_id == post_id, CommunityLike.user_id == user.id)
        )
        like = result.scalar_one_or_none()
        liked = like is None
        if like is None:
            db.add(CommunityLike(post_id=post_id, user_id=user.id))
        else:
            await db.delete(like)
        await db.commit()
        return {"liked": liked, "like_count": await self._count_likes(db, post_id)}

    async def create_comment(
        self,
        db: AsyncSession,
        user: User,
        post_id: int,
        payload: CommentCreateRequest,
    ) -> CommentResponse:
        post = await self._get_post(db, post_id)
        if post.status != "published":
            raise AppException(40008, "当前帖子状态不允许评论")
        comment = CommunityComment(post_id=post_id, user_id=user.id, content=payload.content, status="published")
        db.add(comment)
        await db.commit()
        await db.refresh(comment)
        return await self._comment_to_response(db, comment)

    async def list_comments(
        self,
        db: AsyncSession,
        post_id: int | None,
        *,
        status: str = "published",
        page: int,
        page_size: int,
    ) -> tuple[list[CommentResponse], int]:
        statement = select(CommunityComment).where(CommunityComment.status == status)
        if post_id is not None:
            statement = statement.where(CommunityComment.post_id == post_id)
        statement = statement.order_by(CommunityComment.created_at.desc())
        all_result = await db.execute(statement)
        all_comments = list(all_result.scalars())
        result = await db.execute(statement.offset((page - 1) * page_size).limit(page_size))
        comments = list(result.scalars())
        return [await self._comment_to_response(db, comment) for comment in comments], len(all_comments)

    async def audit_comment(self, db: AsyncSession, comment_id: int, approved: bool) -> CommentResponse:
        comment = await self._get_comment(db, comment_id)
        comment.status = "published" if approved else "hidden"
        await db.commit()
        await db.refresh(comment)
        return await self._comment_to_response(db, comment)

    async def hide_comment(self, db: AsyncSession, comment_id: int) -> CommentResponse:
        comment = await self._get_comment(db, comment_id)
        comment.status = "hidden"
        await db.commit()
        await db.refresh(comment)
        return await self._comment_to_response(db, comment)

    async def _ensure_user_bought_products(self, db: AsyncSession, user_id: int, product_ids: list[int]) -> None:
        statement = (
            select(OrderItem.product_id)
            .join(Order, OrderItem.order_id == Order.id)
            .where(Order.user_id == user_id, Order.status == "completed", OrderItem.product_id.in_(product_ids))
        )
        result = await db.execute(statement)
        bought_product_ids = set(result.scalars())
        if not set(product_ids).issubset(bought_product_ids):
            raise AppException(40005, "种草帖只能关联已完成订单中的商品")

    async def _get_post(self, db: AsyncSession, post_id: int) -> CommunityPost:
        post = await db.get(CommunityPost, post_id)
        if post is None:
            raise AppException(40004, "帖子不存在", 404)
        return post

    async def _get_comment(self, db: AsyncSession, comment_id: int) -> CommunityComment:
        comment = await db.get(CommunityComment, comment_id)
        if comment is None:
            raise AppException(40004, "评论不存在", 404)
        return comment

    async def _post_to_response(self, db: AsyncSession, post: CommunityPost) -> PostResponse:
        author = await db.get(User, post.user_id)
        return PostResponse(
            id=post.id,
            type=post.type,
            title=post.title,
            content=post.content,
            image_urls=json.loads(post.image_urls or "[]"),
            product_ids=json.loads(post.product_ids or "[]"),
            topic_tags=json.loads(post.topic_tags or "[]"),
            status=post.status,
            author=self._author_to_summary(author),
            like_count=await self._count_likes(db, post.id),
            comment_count=await self._count_comments(db, post.id),
            created_at=post.created_at,
        )

    async def _comment_to_response(self, db: AsyncSession, comment: CommunityComment) -> CommentResponse:
        author = await db.get(User, comment.user_id)
        return CommentResponse(
            id=comment.id,
            post_id=comment.post_id,
            author=self._author_to_summary(author),
            content=comment.content,
            status=comment.status,
            created_at=comment.created_at,
        )

    def _author_to_summary(self, author: User | None) -> AuthorSummary:
        if author is None:
            return AuthorSummary(id=0, nickname="已注销用户", avatar_url=None)
        return AuthorSummary(id=author.id, nickname=author.nickname, avatar_url=author.avatar_url)

    async def _count_likes(self, db: AsyncSession, post_id: int) -> int:
        result = await db.execute(select(func.count(CommunityLike.id)).where(CommunityLike.post_id == post_id))
        return int(result.scalar_one())

    async def _count_comments(self, db: AsyncSession, post_id: int) -> int:
        result = await db.execute(
            select(func.count(CommunityComment.id)).where(
                CommunityComment.post_id == post_id,
                CommunityComment.status == "published",
            )
        )
        return int(result.scalar_one())


community_service = CommunityService()
