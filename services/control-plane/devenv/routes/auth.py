from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel

from .. import auth

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginIn(BaseModel):
    username: str = "admin"
    password: str


class PasswordIn(BaseModel):
    current: str
    new: str


@router.post("/login")
def login(body: LoginIn, request: Request, response: Response):
    token = auth.login(request.app.state.db, body.username, body.password)
    if not token:
        raise HTTPException(401, "Wrong username or password")
    response.set_cookie(auth.SESSION_COOKIE, token, httponly=True, samesite="strict", max_age=auth.SESSION_TTL)
    user = request.app.state.db.one("SELECT must_change FROM users WHERE username = ?", body.username)
    return {"ok": True, "must_change_password": bool(user["must_change"])}


@router.post("/logout")
def logout(request: Request, response: Response):
    cookie = request.cookies.get(auth.SESSION_COOKIE)
    if cookie:
        request.app.state.db.run("DELETE FROM sessions WHERE token_hash = ?", auth.sha(cookie))
    response.delete_cookie(auth.SESSION_COOKIE)
    return {"ok": True}


@router.get("/me")
def me(request: Request, p: auth.Principal = Depends(auth.current_principal)):
    must = False
    if p.kind == "admin":
        row = request.app.state.db.one("SELECT must_change FROM users WHERE username = ?", p.name)
        must = bool(row and row["must_change"])
    return {"kind": p.kind, "name": p.name, "must_change_password": must}


@router.post("/password")
def change_password(body: PasswordIn, request: Request, p: auth.Principal = Depends(auth.admin_only)):
    db = request.app.state.db
    user = db.one("SELECT password_hash FROM users WHERE username = ?", p.name)
    if not user or not auth.verify_password(body.current, user["password_hash"]):
        raise HTTPException(400, "Current password is wrong")
    auth.change_password(db, request.app.state.cfg.state_dir, p.name, body.new)
    return {"ok": True}
