"""Authentication, subscriptions, and profile API."""

from __future__ import annotations

from typing import Annotated, Literal, Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field

from backend import auth_db
from core.billing.plans import PLAN_NORMAL, PLAN_PREMIUM, PlanKind

router = APIRouter(prefix="/api/auth", tags=["Auth"])


class RegisterRequest(BaseModel):
    email: str = Field(min_length=3)
    password: str = Field(min_length=6)
    display_name: str = Field(min_length=1, max_length=64)


class LoginRequest(BaseModel):
    email: str = Field(min_length=3)
    password: str


class AuthResponse(BaseModel):
    token: str
    user: dict


class SubscribeRequest(BaseModel):
    plan: Literal["normal", "premium"]


class RenewRequest(BaseModel):
    keep_boosted: bool = False


def _bearer_token(authorization: Optional[str]) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Not authenticated")
    return authorization[7:].strip()


def get_current_user(authorization: Annotated[Optional[str], Header()] = None) -> dict:
    token = _bearer_token(authorization)
    user = auth_db.user_from_token(token)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid or expired session")
    return user


def get_entitlements(user: dict = Depends(get_current_user)):
    return auth_db.get_entitlements(user["id"])


@router.get("/ping")
async def ping():
    return {"ok": True, "service": "aiedit-auth"}


@router.post("/register", response_model=AuthResponse)
async def register(body: RegisterRequest):
    try:
        user = auth_db.create_user(body.email, body.password, body.display_name)
    except Exception as exc:
        if "UNIQUE" in str(exc).upper():
            raise HTTPException(status_code=409, detail="Email already registered") from exc
        raise
    token = auth_db.create_session(user["id"])
    return AuthResponse(
        token=token,
        user={"id": user["id"], "email": user["email"], "display_name": user["display_name"]},
    )


@router.post("/login", response_model=AuthResponse)
async def login(body: LoginRequest):
    user = auth_db.authenticate(body.email, body.password)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid email or password")
    token = auth_db.create_session(user["id"])
    return AuthResponse(
        token=token,
        user={"id": user["id"], "email": user["email"], "display_name": user["display_name"]},
    )


@router.post("/logout")
async def logout(authorization: Annotated[Optional[str], Header()] = None):
    try:
        token = _bearer_token(authorization)
        auth_db.delete_session(token)
    except HTTPException:
        pass
    return {"ok": True}


@router.get("/me")
async def me(user: dict = Depends(get_current_user)):
    ent = auth_db.get_entitlements(user["id"])
    return ent.to_profile_dict()


@router.get("/profile")
async def profile(user: dict = Depends(get_current_user)):
    ent = auth_db.get_entitlements(user["id"])
    payments = auth_db.list_payments(user["id"])
    payload = ent.to_profile_dict()
    payload["payments"] = payments
    payload["offers"] = _offers_for(ent)
    return payload


def _offers_for(ent) -> dict:
    offers: dict = {}
    if ent.subscription_status == "none":
        offers["subscribe"] = {
            "normal_inr": 79,
            "premium_inr": 199,
            "message": "Pick a weekly plan to start editing.",
        }
    elif ent.limit_reached and ent.plan_kind == PLAN_NORMAL:
        offers["upgrade_to_premium"] = {
            "price_inr": 199,
            "new_daily_limit": 12,
            "message": "Convert your remaining week to Premium for more edits and code-gen.",
        }
    elif ent.limit_reached and ent.plan_kind == PLAN_PREMIUM:
        pay = ent.weekly_price_inr // 2
        new_price = ent.weekly_price_inr + pay
        new_limit = int(ent.daily_edit_limit * 1.5)
        offers["boost_50"] = {
            "immediate_payment_inr": pay,
            "new_weekly_price_inr": new_price,
            "new_daily_limit": new_limit,
            "message": f"Pay ₹{pay} now for +50% daily edits this week (Premium only).",
        }
    if ent.subscription_status == "expired":
        offers["renew"] = {"message": "Your weekly plan expired. Renew to continue editing."}
    if ent.boost_count > 0 and ent.subscription_status == "active":
        offers["week_end_choice"] = {
            "keep_boosted_price_inr": ent.weekly_price_inr,
            "keep_boosted_limit": ent.daily_edit_limit,
            "revert_price_inr": ent.base_weekly_price_inr,
            "revert_limit": ent.base_daily_limit,
            "message": "At week end you can keep boosted pricing or revert to your base plan.",
        }
    return offers


@router.post("/subscribe")
async def subscribe(body: SubscribeRequest, user: dict = Depends(get_current_user)):
    plan: PlanKind = PLAN_NORMAL if body.plan == "normal" else PLAN_PREMIUM
    ent = auth_db.subscribe(user["id"], plan)
    return ent.to_profile_dict()


@router.post("/upgrade/premium")
async def upgrade_premium(user: dict = Depends(get_current_user)):
    try:
        ent = auth_db.upgrade_to_premium(user["id"])
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ent.to_profile_dict()


@router.post("/boost/50")
async def boost_fifty(user: dict = Depends(get_current_user)):
    try:
        ent = auth_db.apply_premium_boost(user["id"])
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ent.to_profile_dict()


@router.post("/renew")
async def renew(body: RenewRequest, user: dict = Depends(get_current_user)):
    try:
        ent = auth_db.renew_subscription(user["id"], keep_boosted=body.keep_boosted)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ent.to_profile_dict()


@router.post("/revert-boost")
async def revert_boost(user: dict = Depends(get_current_user)):
    try:
        ent = auth_db.revert_boost_for_new_week(user["id"])
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ent.to_profile_dict()
