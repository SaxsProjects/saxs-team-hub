"""Saxs Assistant: what needs doing next, for whoever is signed in (see app/assistant.py)."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..assistant import briefing
from ..db import get_db
from ..deps import current_user
from ..models import User

router = APIRouter(prefix="/api", tags=["assistant"])


@router.get("/assistant")
def assistant(db: Session = Depends(get_db), user: User = Depends(current_user)):
    return briefing(db, user)
