"""User subscription state, quotas, and billing actions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, Literal, Optional

from core.billing.plans import (
    PLAN_NORMAL,
    PLAN_PREMIUM,
    PlanKind,
    apply_boost_to_subscription,
    base_plan,
)

SubscriptionStatus = Literal["none", "active", "expired"]


@dataclass
class UserEntitlements:
    user_id: str
    email: str
    display_name: str
    subscription_status: SubscriptionStatus
    plan_kind: Optional[PlanKind]
    weekly_price_inr: int
    daily_edit_limit: int
    base_plan_kind: Optional[PlanKind]
    base_weekly_price_inr: int
    base_daily_limit: int
    boost_count: int
    week_started_at: Optional[str]
    week_ends_at: Optional[str]
    edits_today: int
    edits_remaining_today: int
    codegen_enabled: bool
    can_edit: bool
    limit_reached: bool

    def to_profile_dict(self) -> Dict[str, Any]:
        return {
            "user_id": self.user_id,
            "email": self.email,
            "display_name": self.display_name,
            "subscription_status": self.subscription_status,
            "plan": {
                "kind": self.plan_kind,
                "name": base_plan(self.plan_kind).name if self.plan_kind else None,
                "weekly_price_inr": self.weekly_price_inr,
                "daily_edit_limit": self.daily_edit_limit,
                "codegen_enabled": self.codegen_enabled,
                "boost_count": self.boost_count,
                "base_plan_kind": self.base_plan_kind,
                "base_weekly_price_inr": self.base_weekly_price_inr,
                "base_daily_limit": self.base_daily_limit,
                "week_started_at": self.week_started_at,
                "week_ends_at": self.week_ends_at,
            },
            "usage": {
                "edits_today": self.edits_today,
                "edits_remaining_today": self.edits_remaining_today,
                "limit_reached": self.limit_reached,
            },
            "permissions": {
                "can_edit": self.can_edit,
                "codegen_enabled": self.codegen_enabled,
            },
            "pricing_inr": {
                "normal_weekly": base_plan(PLAN_NORMAL).weekly_price_inr,
                "premium_weekly": base_plan(PLAN_PREMIUM).weekly_price_inr,
            },
        }


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def week_end_from_start(start: datetime) -> datetime:
    return start + timedelta(days=7)


def entitlements_from_row(user_row: dict, sub_row: Optional[dict], edits_today: int) -> UserEntitlements:
    uid = user_row["id"]
    email = user_row["email"]
    name = user_row.get("display_name") or email.split("@")[0]

    if not sub_row or not sub_row.get("active"):
        return UserEntitlements(
            user_id=uid,
            email=email,
            display_name=name,
            subscription_status="none",
            plan_kind=None,
            weekly_price_inr=0,
            daily_edit_limit=0,
            base_plan_kind=None,
            base_weekly_price_inr=0,
            base_daily_limit=0,
            boost_count=0,
            week_started_at=None,
            week_ends_at=None,
            edits_today=edits_today,
            edits_remaining_today=0,
            codegen_enabled=False,
            can_edit=False,
            limit_reached=True,
        )

    week_end = datetime.fromisoformat(sub_row["week_ends_at"])
    if _utc_now() > week_end:
        return UserEntitlements(
            user_id=uid,
            email=email,
            display_name=name,
            subscription_status="expired",
            plan_kind=sub_row["plan_kind"],
            weekly_price_inr=sub_row["weekly_price_inr"],
            daily_edit_limit=sub_row["daily_limit"],
            base_plan_kind=sub_row["base_plan_kind"],
            base_weekly_price_inr=sub_row["base_weekly_price_inr"],
            base_daily_limit=sub_row["base_daily_limit"],
            boost_count=sub_row.get("boost_count") or 0,
            week_started_at=sub_row["week_started_at"],
            week_ends_at=sub_row["week_ends_at"],
            edits_today=edits_today,
            edits_remaining_today=0,
            codegen_enabled=bool(sub_row.get("codegen_enabled")),
            can_edit=False,
            limit_reached=True,
        )

    daily_limit = int(sub_row["daily_limit"])
    remaining = max(0, daily_limit - edits_today)
    plan_kind = sub_row["plan_kind"]
    return UserEntitlements(
        user_id=uid,
        email=email,
        display_name=name,
        subscription_status="active",
        plan_kind=plan_kind,
        weekly_price_inr=int(sub_row["weekly_price_inr"]),
        daily_edit_limit=daily_limit,
        base_plan_kind=sub_row["base_plan_kind"],
        base_weekly_price_inr=int(sub_row["base_weekly_price_inr"]),
        base_daily_limit=int(sub_row["base_daily_limit"]),
        boost_count=int(sub_row.get("boost_count") or 0),
        week_started_at=sub_row["week_started_at"],
        week_ends_at=sub_row["week_ends_at"],
        edits_today=edits_today,
        edits_remaining_today=remaining,
        codegen_enabled=bool(sub_row.get("codegen_enabled")),
        can_edit=remaining > 0,
        limit_reached=remaining <= 0,
    )


def new_subscription_fields(plan_kind: PlanKind) -> dict:
    plan = base_plan(plan_kind)
    start = _utc_now()
    end = week_end_from_start(start)
    return {
        "plan_kind": plan_kind,
        "weekly_price_inr": plan.weekly_price_inr,
        "daily_limit": plan.daily_edit_limit,
        "codegen_enabled": plan.codegen_enabled,
        "base_plan_kind": plan_kind,
        "base_weekly_price_inr": plan.weekly_price_inr,
        "base_daily_limit": plan.daily_edit_limit,
        "boost_count": 0,
        "week_started_at": start.isoformat(),
        "week_ends_at": end.isoformat(),
        "active": 1,
    }


def premium_upgrade_fields(current_sub: dict) -> dict:
    """Normal → Premium for remainder of current week."""
    plan = base_plan(PLAN_PREMIUM)
    return {
        "plan_kind": PLAN_PREMIUM,
        "weekly_price_inr": plan.weekly_price_inr,
        "daily_limit": plan.daily_edit_limit,
        "codegen_enabled": True,
        "base_plan_kind": PLAN_PREMIUM,
        "base_weekly_price_inr": plan.weekly_price_inr,
        "base_daily_limit": plan.daily_edit_limit,
        "boost_count": 0,
        # keep week_started_at / week_ends_at unchanged
    }


def boost_fields(current_sub: dict) -> tuple[int, dict]:
    pay, new_price, new_limit = apply_boost_to_subscription(
        int(current_sub["weekly_price_inr"]),
        int(current_sub["daily_limit"]),
    )
    return pay, {
        "weekly_price_inr": new_price,
        "daily_limit": new_limit,
        "boost_count": int(current_sub.get("boost_count") or 0) + 1,
    }


def revert_to_base_fields(current_sub: dict) -> dict:
    """End-of-week: return to base plan price/limit without cancelling plan kind."""
    base_kind = current_sub["base_plan_kind"]
    plan = base_plan(base_kind)
    return {
        "weekly_price_inr": plan.weekly_price_inr,
        "daily_limit": plan.daily_edit_limit,
        "codegen_enabled": plan.codegen_enabled,
        "boost_count": 0,
    }


def renew_week_fields(current_sub: dict, *, keep_boosted: bool) -> dict:
    start = _utc_now()
    end = week_end_from_start(start)
    fields = {
        "week_started_at": start.isoformat(),
        "week_ends_at": end.isoformat(),
        "active": 1,
    }
    if not keep_boosted:
        fields.update(revert_to_base_fields(current_sub))
    return fields
