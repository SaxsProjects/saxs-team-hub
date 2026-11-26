"""Profile pictures for every signed-in user (founder and team)."""

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session, undefer

from ..avatars import MEDIA_TYPE, avatar_url, read_avatar_upload
from ..db import get_db, utcnow
from ..deps import current_user
from ..models import User
from ..services import audit

router = APIRouter(prefix="/api", tags=["profile pictures"])


@router.put("/me/avatar")
async def set_my_avatar(file: UploadFile = File(...), db: Session = Depends(get_db), user: User = Depends(current_user)):
    image = await read_avatar_upload(file)
    user.avatar = image
    user.avatar_updated_at = utcnow()
    audit(db, user.email, "user.avatar_set", "user", user.id, after={"bytes": len(image)})
    db.commit()
    return {"avatar_url": avatar_url(user)}


@router.delete("/me/avatar", status_code=204)
def remove_my_avatar(db: Session = Depends(get_db), user: User = Depends(current_user)):
    if user.avatar_updated_at is not None:
        user.avatar = None
        user.avatar_updated_at = None
        audit(db, user.email, "user.avatar_removed", "user", user.id)
        db.commit()


@router.get("/avatars/{user_id}")
def read_avatar(user_id: int, db: Session = Depends(get_db), _: User = Depends(current_user)):
    """Team pictures are visible to signed-in team members only (never public)."""
    target = db.scalars(select(User).options(undefer(User.avatar)).where(User.id == user_id, User.is_active)).first()
    if not target or not target.avatar:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No profile picture")
    return Response(
        target.avatar,
        media_type=MEDIA_TYPE,
        headers={"Cache-Control": "private, max-age=31536000, immutable", "Content-Disposition": "inline"},
    )
