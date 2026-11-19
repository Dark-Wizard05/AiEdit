"""Subscription plans, pricing (INR), and daily limits."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

PlanKind = Literal["normal", "premium"]

PLAN_NORMAL: PlanKind = "normal"
PLAN_PREMIUM: PlanKind = "premium"


@dataclass(frozen=True)
class PlanDefinition:
    kind: PlanKind
    name: str
    weekly_price_inr: int
    daily_edit_limit: int
    codegen_enabled: bool
    description: str


PLANS: dict[PlanKind, PlanDefinition] = {
    PLAN_NORMAL: PlanDefinition(
        kind=PLAN_NORMAL,
        name="Normal",
        weekly_price_inr=79,
        daily_edit_limit=5,
        codegen_enabled=False,
        description="Built-in edits: text, objects, hair, colors, atmosphere, commentary.",
    ),
    PLAN_PREMIUM: PlanDefinition(
        kind=PLAN_PREMIUM,
        name="Premium",
        weekly_price_inr=199,
        daily_edit_limit=12,
        codegen_enabled=True,
        description="Everything in Normal plus AI code-gen for open-ended timeline edits.",
    ),
}


def base_plan(kind: PlanKind) -> PlanDefinition:
    return PLANS[kind]


def boost_price_inr(current_weekly_price: int) -> int:
    """Immediate charge for +50% limit boost (half of current weekly price, floored)."""
    return current_weekly_price // 2


def apply_boost_to_subscription(
    current_weekly_price: int,
    current_daily_limit: int,
) -> tuple[int, int, int]:
    """
    Returns (immediate_payment_inr, new_weekly_price_inr, new_daily_limit).
    Price increases by payment amount; limit increases by 50% (integer floor).
    """
    payment = boost_price_inr(current_weekly_price)
    new_price = current_weekly_price + payment
    new_limit = int(current_daily_limit * 1.5)
    return payment, new_price, new_limit
