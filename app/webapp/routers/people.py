"""People route family — the contacts / assignees a task can point at.

    GET    /api/people          list (name order, with open-task counts)
    POST   /api/people          {name, email?, avatar_path?, external_id?} → 201
    GET    /api/people/{id}
    PATCH  /api/people/{id}     partial update
    DELETE /api/people/{id}     tasks that pointed here keep going with person_id = NULL
"""

from __future__ import annotations

import sqlite3
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from src import tasks_repo as repo
from src.db import get_db

router = APIRouter(prefix="/api/people", tags=["people"])


class PersonCreate(BaseModel):
    name: str
    email: str | None = None
    avatar_path: str | None = None
    external_id: str | None = None


class PersonUpdate(BaseModel):
    name: str | None = None
    email: str | None = None
    avatar_path: str | None = None
    external_id: str | None = None


@router.get("")
def list_people(db: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    items = repo.list_people(db)
    return {"items": items, "count": len(items)}


@router.post("", status_code=201)
def create_person(body: PersonCreate, db: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    return repo.create_person(
        db, body.name, email=body.email, avatar_path=body.avatar_path, external_id=body.external_id
    )


@router.get("/{person_id}")
def get_person(person_id: int, db: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    return repo.get_person(db, person_id)


@router.patch("/{person_id}")
def update_person(
    person_id: int, body: PersonUpdate, db: sqlite3.Connection = Depends(get_db)
) -> dict[str, Any]:
    return repo.update_person(db, person_id, **body.model_dump(exclude_unset=True))


@router.delete("/{person_id}")
def delete_person(person_id: int, db: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    repo.delete_person(db, person_id)
    return {"id": person_id, "deleted": 1}
