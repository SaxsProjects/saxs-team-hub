"""The notification bell: every signed-in user reads and clears only their own notifications."""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import current_user
from ..models import Notification, User
from ..notifications import mark_read, unread_count
from ..schemas import ORM

router = APIRouter(prefix="/api/notifications", tags=["notifications"])


class NotificationOut(ORM):
    id: int
    kind: str
    title: str
    body: str | None
    link: str | None
    created_at: datetime
    read_at: datetime | None


class NotificationList(BaseModel):
    unread: int
    items: list[NotificationOut]


class ReadIn(BaseModel):
    ids: list[int] = Field(min_length=1, max_length=200)


@router.get("", response_model=NotificationList)
def list_notifications(
    unread_only: bool = False,
    limit: int = Query(30, ge=1, le=100),
    before_id: int | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    stmt = select(Notification).where(Notification.user_id == user.id)
    if unread_only:
        stmt = stmt.where(Notification.read_at.is_(None))
    if before_id is not None:
        stmt = stmt.where(Notification.id < before_id)
    items = db.scalars(stmt.order_by(Notification.id.desc()).limit(limit)).all()
    return NotificationList(unread=unread_count(db, user.id), items=items)


@router.get("/unread-count")
def get_unread_count(db: Session = Depends(get_db), user: User = Depends(current_user)):
    return {"unread": unread_count(db, user.id)}


@router.post("/read")
def read_some(body: ReadIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    owned = db.scalars(select(Notification.id).where(Notification.user_id == user.id, Notification.id.in_(body.ids))).all()
    if len(set(owned)) != len(set(body.ids)):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Notification not found")
    mark_read(db, user.id, body.ids)
    db.commit()
    return {"unread": unread_count(db, user.id)}


@router.post("/read-all")
def read_all(db: Session = Depends(get_db), user: User = Depends(current_user)):
    mark_read(db, user.id)
    db.commit()
    return {"unread": 0}
