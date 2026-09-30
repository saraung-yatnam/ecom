# app/api/v1/admin/content.py
"""Admin content blocks (requires content.manage).

Every create/update/delete writes an audit entry (entity "content" —
operational, visible to reports.view). Publish windows make campaigns
self-expiring; flipping ``is_active`` is the kill switch.
"""
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, status
from fastapi import UploadFile

import io

from app.api.deps import SessionDep, require_perm
from app.models.content_block import ContentBlock
from app.models.user import User
from app.repositories import audit as audit_repo
from app.repositories import content as content_repo
from app.schemas.content import (
    ContentBlockCreate,
    ContentBlockListResponse,
    ContentBlockRead,
    ContentBlockUpdate,
    ContentImageUploadResponse,
)

router = APIRouter(prefix="/admin/content", tags=["Admin Content"])

#: Per-slot image rules. Size is a hard cap (413 over); aspect is
#: warn-only — creative crops still save, the storefront crops the rest.
#: Unknown slots fall back to DEFAULT_IMAGE_SPEC.
SLOT_IMAGE_SPECS = {
    "announcement.bar": {
        "max_bytes": 1_000_000,
        "aspect": 10.0,
        "label": "800 × 80 px (10:1), ≤1 MB",
    },
    "home.hero": {
        "max_bytes": 5_000_000,
        "aspect": 16.0 / 6.0,
        "label": "1920 × 720 px (16:6), ≤5 MB",
    },
}
DEFAULT_IMAGE_SPEC = {"max_bytes": 5_000_000, "aspect": None, "label": "≤5 MB"}
ALLOWED_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
# Warn (don't block) when the aspect drifts this far from recommended.
ASPECT_TOLERANCE = 0.10


@router.get("/blocks", response_model=ContentBlockListResponse)
def list_blocks(
    session: SessionDep,
    current_user: User = Depends(require_perm("content.manage")),
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=50, ge=1, le=100),
):
    """All blocks incl. drafts/disabled/expired, newest first."""
    skip = (page - 1) * limit
    rows, total = content_repo.list_blocks_admin(session, skip=skip, limit=limit)
    return ContentBlockListResponse(
        items=[ContentBlockRead.model_validate(r) for r in rows],
        total=total,
        page=page,
        limit=limit,
        total_pages=(total + limit - 1) // limit if limit else 1,
    )


@router.post("/blocks", response_model=ContentBlockRead, status_code=status.HTTP_201_CREATED)
def create_block(
    payload: ContentBlockCreate,
    request: Request,
    session: SessionDep,
    current_user: User = Depends(require_perm("content.manage")),
):
    """Create a block. Keys are slot slugs (e.g. ``announcement.bar``) —
    several blocks may share a slot; they render ordered by sort_order."""
    _assert_window(payload.starts_at, payload.ends_at)
    block = ContentBlock(**payload.model_dump(), created_by=current_user.id)
    session.add(block)
    session.commit()
    session.refresh(block)
    audit_repo.log_and_commit(
        session,
        action="content.created",
        entity="content",
        entity_id=block.id,
        actor_id=current_user.id,
        after={"key": block.key, "title": block.title},
        ip_address=audit_repo.client_ip(request),
    )
    return ContentBlockRead.model_validate(block)


@router.put("/blocks/{block_id}", response_model=ContentBlockRead)
def update_block(
    block_id: UUID,
    payload: ContentBlockUpdate,
    request: Request,
    session: SessionDep,
    current_user: User = Depends(require_perm("content.manage")),
):
    """Partial update. Nulling a window bound re-opens that end."""
    block = content_repo.get_block_by_id(session, block_id)
    if block is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Content block not found"
        )
    data = payload.model_dump(exclude_unset=True)
    if not data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Nothing to update"
        )
    starts = data.get("starts_at", block.starts_at)
    ends = data.get("ends_at", block.ends_at)
    _assert_window(starts, ends)
    before = {"title": block.title, "is_active": block.is_active}
    for key, value in data.items():
        setattr(block, key, value)
    from datetime import datetime, timezone

    block.updated_at = datetime.now(timezone.utc)
    session.add(block)
    session.commit()
    session.refresh(block)
    audit_repo.log_and_commit(
        session,
        action="content.updated",
        entity="content",
        entity_id=block.id,
        actor_id=current_user.id,
        before=before,
        after={"title": block.title, "is_active": block.is_active},
        ip_address=audit_repo.client_ip(request),
    )
    return ContentBlockRead.model_validate(block)


@router.delete("/blocks/{block_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_block(
    block_id: UUID,
    request: Request,
    session: SessionDep,
    current_user: User = Depends(require_perm("content.manage")),
):
    """Delete a block. The slot falls back to hardcoded content (if any)."""
    block = content_repo.get_block_by_id(session, block_id)
    if block is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Content block not found"
        )
    snapshot = {"key": block.key, "title": block.title}
    session.delete(block)
    session.commit()
    audit_repo.log_and_commit(
        session,
        action="content.deleted",
        entity="content",
        entity_id=block_id,
        actor_id=current_user.id,
        before=snapshot,
        ip_address=audit_repo.client_ip(request),
    )
    return None


def _assert_window(starts_at, ends_at) -> None:
    if starts_at and ends_at and ends_at <= starts_at:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="ends_at must be after starts_at",
        )


@router.post("/images", response_model=ContentImageUploadResponse)
async def upload_content_image(
    request: Request,
    slot: str = Query(default=""),
    file: UploadFile = File(...),
    current_user: User = Depends(require_perm("content.manage")),
):
    """Upload a slot image (multipart). Returns an absolute URL for image_url.

    Size caps are enforced (413 over); aspect mismatches return a warning
    string but still succeed. Files land in ``uploads/content/`` (served at
    ``/uploads`` — back this dir up, it is user content, not code).
    """
    from pathlib import Path

    from PIL import Image, UnidentifiedImageError

    spec = SLOT_IMAGE_SPECS.get((slot or "").strip(), DEFAULT_IMAGE_SPEC)

    ext = Path(file.filename or "").suffix.lower()
    if (file.content_type or "") and not file.content_type.startswith("image/"):
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Only image uploads are accepted",
        )
    if ext not in ALLOWED_IMAGE_EXTS:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"Allowed types: {', '.join(sorted(ALLOWED_IMAGE_EXTS))}",
        )

    # Stream with a hard ceiling so a hostile upload can't fill memory.
    ceiling = spec["max_bytes"] + 1
    chunks: list[bytes] = []
    received = 0
    while True:
        piece = await file.read(1024 * 256)
        if not piece:
            break
        received += len(piece)
        if received > ceiling:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"Image exceeds {spec['max_bytes'] // 1_000_000 or 1} MB "
                f"(slot recommendation: {spec['label']})",
            )
        chunks.append(piece)
    blob = b"".join(chunks)

    try:
        with Image.open(io.BytesIO(blob)) as img:
            img.verify()
        with Image.open(io.BytesIO(blob)) as img:
            width, height = img.size
    except (UnidentifiedImageError, OSError):
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="File is not a readable image",
        )

    aspect_warning = None
    if spec["aspect"] and height > 0:
        drift = abs((width / height) - spec["aspect"]) / spec["aspect"]
        if drift > ASPECT_TOLERANCE:
            aspect_warning = (
                f"Image is {width}×{height} but this slot recommends "
                f"{spec['label']} — it will be cropped to fit."
            )

    # Downscale absurdly large files to display size: a 7000px-wide file
    # squeezed into a phone frame downsamples into mush and costs megabytes.
    # Cap at 1920px wide (covers the largest slot), keep aspect, optimize.
    # Small files pass through byte-identical.
    out_blob = blob
    with Image.open(io.BytesIO(blob)) as img:
        if img.width > 1920:
            resized = img.copy()
            resized.thumbnail((1920, 1920), Image.LANCZOS)
            buf = io.BytesIO()
            save_kwargs: dict = {"optimize": True}
            if ext in (".jpg", ".jpeg"):
                save_kwargs["quality"] = 82
            resized.save(buf, format=img.format or "PNG", **save_kwargs)
            out_blob = buf.getvalue()
            width, height = resized.size

    upload_dir = Path(__file__).resolve().parents[4] / "uploads" / "content"
    upload_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{uuid4().hex}{ext}"
    (upload_dir / filename).write_bytes(out_blob)

    base = str(request.base_url).rstrip("/")
    return ContentImageUploadResponse(
        url=f"{base}/uploads/content/{filename}",
        width=width,
        height=height,
        size_bytes=len(out_blob),
        aspect_warning=aspect_warning,
    )
