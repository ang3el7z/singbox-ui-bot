from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from api.database import get_db, WebUser
from api.deps import verify_password, create_access_token, hash_password, get_current_web_user, audit

router = APIRouter()


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    username: str


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


@router.post("/login", response_model=LoginResponse)
async def login(body: LoginRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(WebUser).where(WebUser.username == body.username, WebUser.is_active == True)
    )
    user = result.scalar_one_or_none()
    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    token = create_access_token(user.username)
    await audit("web:login", "login", f"username={body.username}")
    return LoginResponse(access_token=token, username=user.username)


@router.get("/me")
async def me(current_user: WebUser = Depends(get_current_web_user)):
    return {"username": current_user.username, "id": current_user.id}


@router.post("/change-password")
async def change_password(
    body: ChangePasswordRequest,
    current_user: WebUser = Depends(get_current_web_user),
    db: AsyncSession = Depends(get_db),
):
    if not verify_password(body.current_password, current_user.password_hash):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Wrong current password")
    if len(body.new_password) < 8:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Password too short (min 8)")
    current_user.password_hash = hash_password(body.new_password)
    db.add(current_user)
    await db.commit()
    await audit(f"web:{current_user.username}", "change_password")
    return {"detail": "Password changed"}
