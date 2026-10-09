"""Name-and-password sessions. Each user only sees their own meetings."""

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field

from sten import db

router = APIRouter(prefix="/api/auth")

COOKIE = "sten_session"
_MAX_AGE = 60 * 60 * 24 * 30


class Credentials(BaseModel):
    name: str = Field(min_length=1, max_length=40)
    password: str = Field(min_length=6, max_length=200)


def _clean_name(name: str) -> str:
    cleaned = " ".join(name.split())
    if not cleaned or len(cleaned) > 40:
        raise HTTPException(status_code=400, detail="Укажите имя")
    return cleaned


def user_from_request(request: Request) -> dict | None:
    token = request.cookies.get(COOKIE, "")
    if not token:
        header = request.headers.get("authorization", "")
        if header.lower().startswith("bearer "):
            token = header[7:].strip()
    return db.get_user_by_session(token)


def require_user(request: Request) -> dict:
    user = user_from_request(request)
    if user is None:
        raise HTTPException(status_code=401, detail="Нужно войти")
    return user


def _public_user(user: dict) -> dict:
    return {"id": user["id"], "name": user["name"]}


def _start_session(response: Response, user_id: int) -> dict:
    token = db.create_session(user_id)
    response.set_cookie(
        COOKIE,
        token,
        max_age=_MAX_AGE,
        httponly=True,
        samesite="lax",
        path="/",
    )
    user = db.get_user_by_session(token)
    assert user is not None
    return _public_user(user)


@router.post("/register")
def register(body: Credentials, response: Response) -> dict:
    name = _clean_name(body.name)
    try:
        user = db.create_user(name, body.password)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail="Такое имя уже занято") from exc
    return _start_session(response, user["id"])


@router.post("/login")
def login(body: Credentials, response: Response) -> dict:
    name = _clean_name(body.name)
    user = db.authenticate(name, body.password)
    if user is None:
        raise HTTPException(status_code=401, detail="Неверное имя или пароль")
    return _start_session(response, user["id"])


@router.post("/logout")
def logout(request: Request, response: Response) -> dict:
    token = request.cookies.get(COOKIE, "")
    if token:
        db.delete_session(token)
    response.delete_cookie(COOKIE, path="/")
    return {"ok": True}


@router.get("/me")
def me(request: Request) -> dict:
    user = require_user(request)
    return _public_user(user)
