"""Time route family — the time tracker behind the Time tab (#457).

    GET    /api/time/meta                 people, areas + categories, compare area,
                                          long-timer threshold, the server's today / now
    GET    /api/time/timers               {items, now} — every running timer
    POST   /api/time/timers               {person, category_id, switch?} → 201 {timer, entry}
                                          (409 timer_running unless switch)
    POST   /api/time/timers/{person}/stop {minutes?} → the saved entry (409 no_timer)
    DELETE /api/time/timers/{person}      discard, nothing saved → 204 (409 no_timer)
    GET    /api/time/entries?q=&limit=&offset=      History, newest first
    POST   /api/time/entries              {person, category_id, day, minutes, start?, note?} → 201
    PATCH  /api/time/entries/{id}         any field above; 404 if deleted meanwhile
    DELETE /api/time/entries/{id}         → 204
    GET    /api/time/entries.csv?period=|from=&to=&area=&person=
    GET    /api/time/recent?person=       the person's last five categories (ids)
    GET    /api/time/summary?period=&area=&person=
    GET    /api/time/guesses/{person}     yours, and the others' once yours is in
    PUT    /api/time/guesses/{person}     {pct}
    POST   /api/time/areas                {name} → 201
    PATCH  /api/time/areas/{id}           {name?, position?, archived?}
    POST   /api/time/categories           {area_id, name, hint?} → 201
    PATCH  /api/time/categories/{id}      {name?, hint?, position?, area_id?, archived?}

Every rule is in ``src/time_repo.py``; the routes only hand it the configured
people (``config.time``). Gated by ``AuthMiddleware`` like every ``/api/``
route — the person a device picks is a label, never a credential. Named
``time_tracker`` so the module can never shadow the stdlib ``time``.
"""

from __future__ import annotations

import sqlite3
from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import BaseModel, Field

from src import clock
from src import time_repo as repo
from src.config import TimeConfig
from src.db import get_db
from src.tasks_repo import ValidationError

router = APIRouter(prefix="/api/time", tags=["time"])


def _time(request: Request) -> TimeConfig:
    return request.app.state.config.time


def _names(cfg: TimeConfig) -> dict[str, str]:
    return {p.id: p.name for p in cfg.people}


class TimerStart(BaseModel):
    person: str = Field(min_length=1)
    category_id: int
    switch: bool = False


class TimerStop(BaseModel):
    minutes: int | None = None


class EntryCreate(BaseModel):
    person: str = Field(min_length=1)
    category_id: int
    day: str
    minutes: int
    start: str | None = None
    note: str | None = None


class EntryUpdate(BaseModel):
    person: str | None = None
    category_id: int | None = None
    day: str | None = None
    minutes: int | None = None
    start: str | None = None
    note: str | None = None


class GuessBody(BaseModel):
    pct: int


class AreaCreate(BaseModel):
    name: str


class AreaUpdate(BaseModel):
    name: str | None = None
    position: int | None = Field(default=None, ge=0)
    archived: bool | None = None


class CategoryCreate(BaseModel):
    area_id: int
    name: str
    hint: str = ""


class CategoryUpdate(BaseModel):
    name: str | None = None
    hint: str | None = None
    position: int | None = Field(default=None, ge=0)
    area_id: int | None = None
    archived: bool | None = None


@router.get("/meta")
def meta(request: Request, db: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    """Everything the tab needs before its first render — the day comes from here, never the browser."""
    cfg = _time(request)
    return {
        "people": [{"id": p.id, "name": p.name} for p in cfg.people],
        "compare_area": cfg.compare_area,
        "long_timer_minutes": cfg.long_timer_minutes,
        "max_minutes": repo.MAX_MINUTES,
        "periods": list(repo.PERIODS),
        "areas": repo.list_areas(db),
        "today": clock.today().isoformat(),
        "now": clock.now_iso(),
    }


@router.get("/timers")
def list_timers(db: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    return {"items": repo.list_timers(db), "now": clock.now_iso()}


@router.post("/timers", status_code=201)
def start_timer(body: TimerStart, request: Request, db: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    return repo.start_timer(db, body.person, body.category_id, people=_time(request).ids, switch=body.switch)


@router.post("/timers/{person}/stop")
def stop_timer(person: str, body: TimerStop | None = None, db: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    return repo.stop_timer(db, person, minutes=body.minutes if body else None)


@router.delete("/timers/{person}", status_code=204)
def discard_timer(person: str, db: sqlite3.Connection = Depends(get_db)) -> Response:
    repo.discard_timer(db, person)
    return Response(status_code=204)


@router.get("/entries")
def list_entries(
    request: Request,
    q: str | None = None,
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: sqlite3.Connection = Depends(get_db),
) -> dict[str, Any]:
    return repo.list_entries(db, names=_names(_time(request)), q=q, limit=limit, offset=offset)


@router.post("/entries", status_code=201)
def create_entry(body: EntryCreate, request: Request, db: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    return repo.create_entry(
        db, person=body.person, category_id=body.category_id, day=body.day, minutes=body.minutes,
        start=body.start, note=body.note, people=_time(request).ids,
    )


def _day_param(value: str | None, name: str) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise ValidationError(f"{name} {value!r} is not a YYYY-MM-DD date") from None


@router.get("/entries.csv")
def entries_csv(
    request: Request,
    period: str | None = None,
    from_: str | None = Query(default=None, alias="from"),
    to: str | None = None,
    area: str | None = None,
    person: str | None = None,
    db: sqlite3.Connection = Depends(get_db),
) -> Response:
    """The entries Totals sums for the same ``period`` (or an explicit ``from``/``to``)."""
    cfg = _time(request)
    from_day = repo.period_start(period, clock.today()) if period else _day_param(from_, "from")
    text = repo.entries_csv(
        db, people=cfg.ids, names=_names(cfg), from_day=from_day,
        to_day=None if period else _day_param(to, "to"), area=area or None, person=person or None,
    )
    return Response(
        text, media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="time-entries.csv"'},
    )


@router.patch("/entries/{entry_id}")
def update_entry(
    entry_id: int, body: EntryUpdate, request: Request, db: sqlite3.Connection = Depends(get_db)
) -> dict[str, Any]:
    return repo.update_entry(db, entry_id, people=_time(request).ids, **body.model_dump(exclude_unset=True))


@router.delete("/entries/{entry_id}", status_code=204)
def delete_entry(entry_id: int, db: sqlite3.Connection = Depends(get_db)) -> Response:
    repo.delete_entry(db, entry_id)
    return Response(status_code=204)


@router.get("/recent")
def recent(person: str, db: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    return {"person": person, "category_ids": repo.recent_categories(db, person)}


@router.get("/summary")
def summary(
    request: Request,
    period: str = "7",
    area: str | None = None,
    person: str | None = None,
    db: sqlite3.Connection = Depends(get_db),
) -> dict[str, Any]:
    return repo.summary(db, people=_time(request).ids, period=period, area=area or None, person=person or None)


@router.get("/guesses/{person}")
def get_guesses(person: str, request: Request, db: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    return repo.get_guesses(db, person, people=_time(request).ids)


@router.put("/guesses/{person}")
def set_guess(person: str, body: GuessBody, request: Request, db: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    return repo.set_guess(db, person, body.pct, people=_time(request).ids)


@router.post("/areas", status_code=201)
def create_area(body: AreaCreate, db: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    return repo.create_area(db, body.name)


@router.patch("/areas/{area_id}")
def update_area(area_id: int, body: AreaUpdate, db: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    return repo.update_area(db, area_id, **body.model_dump(exclude_unset=True))


@router.post("/categories", status_code=201)
def create_category(body: CategoryCreate, db: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    return repo.create_category(db, body.area_id, body.name, body.hint)


@router.patch("/categories/{category_id}")
def update_category(category_id: int, body: CategoryUpdate, db: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    return repo.update_category(db, category_id, **body.model_dump(exclude_unset=True))
