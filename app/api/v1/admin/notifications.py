# app/api/v1/admin/notifications.py
"""
Admin endpoints for promotional broadcasts.

POST /admin/notifications/promotional  -> send a message to ALL active customers
GET  /admin/notifications/promotional  -> history of sent broadcasts
"""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from uuid import UUID

from app.api.deps import SessionDep
from app.api.deps import require_role
from app.models.user import User, UserRole
from app.repositories import notification as notification_repo
from app.schemas.notification import (
    PromotionBroadcastRequest,
    PromotionBroadcastResponse,
    PromotionHistoryItem,
    PromotionRetractResponse,
)

router = APIRouter(prefix="/admin/notifications", tags=["Admin Notifications"])


@router.post("/promotional", response_model=PromotionBroadcastResponse)
def send_promotional_broadcast(
    payload: PromotionBroadcastRequest,
    session: SessionDep,
    current_user: User = Depends(require_role(UserRole.manager, UserRole.admin)),
):
    """Send a promotional message to every active customer's notification feed."""
    broadcast_id, recipients = notification_repo.broadcast_promotion(
        session,
        title=payload.title.strip(),
        message=payload.message.strip(),
        link=payload.link,
    )
    session.commit()

    return PromotionBroadcastResponse(
        broadcast_id=broadcast_id,
        title=payload.title.strip(),
        message=payload.message.strip(),
        link=payload.link,
        recipients_count=recipients,
        created_at=datetime.now(timezone.utc),
    )


@router.get("/promotional", response_model=list[PromotionHistoryItem])
def promotional_history(
    session: SessionDep,
    current_user: User = Depends(require_role(UserRole.manager, UserRole.admin)),
    skip: int = 0,
    limit: int = 20,
):
    """History of promotional broadcasts (newest first)."""
    return notification_repo.promotion_history(session, skip=skip, limit=limit)


@router.delete("/promotional/{broadcast_id}", response_model=PromotionRetractResponse)
def retract_promotional_broadcast(
    broadcast_id: UUID,
    session: SessionDep,
    current_user: User = Depends(require_role(UserRole.manager, UserRole.admin)),
):
    """Retract a broadcast — delete it from every recipient's feed."""
    deleted = notification_repo.retract_broadcast(session, broadcast_id)
    if deleted == 0:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Promotional broadcast not found",
        )
    session.commit()
    return PromotionRetractResponse(deleted_count=deleted)