from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, File, UploadFile

from app.core.config import settings
from app.core.exceptions import AppException
from app.utils.response import ApiResponse, success

router = APIRouter()

ALLOWED_IMAGE_TYPES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}


@router.post("/image", response_model=ApiResponse[dict])
async def upload_image(file: UploadFile = File(...)) -> ApiResponse[dict]:
    suffix = ALLOWED_IMAGE_TYPES.get(file.content_type or "")
    if suffix is None:
        raise AppException(40009, "文件类型不合法")

    content = await file.read()
    max_size = settings.upload_max_size_mb * 1024 * 1024
    if len(content) > max_size:
        raise AppException(40009, "文件大小超出限制")

    upload_dir = Path(settings.upload_dir)
    if not upload_dir.is_absolute():
        upload_dir = Path(__file__).resolve().parents[4] / settings.upload_dir
    upload_dir.mkdir(parents=True, exist_ok=True)

    filename = f"{uuid4().hex}{suffix}"
    target = upload_dir / filename
    target.write_bytes(content)
    return success({"url": f"/static/uploads/{filename}"})
