"""SQLite persistence for users, sessions, subscriptions, and usage."""

from __future__ import annotations

import hashlib
import os
import secrets
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, Generator, Optional

from core.billing.plans import PLAN_NORMAL, PLAN_PREMIUM, PlanKind
from core.billing.service import (
    UserEntitlements,
    boost_fields,
    entitlements_from_row,
    new_subscription_fields,
    premium_upgrade_fields,
    renew_week_fields,
    revert_to_base_fields,
)

_DB_PATH = Path(os.getenv("AIEDIT_AUTH_DB", "data/aiedit_auth.db"))


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _hash_password(password: str, salt: Optional[bytes] = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 120_000)
    return f"pbkdf2_sha256${salt.hex()}${digest.hex()}"


def _verify_password(password: str, stored: str) -> bool:
    try:
        _, salt_hex, digest_hex = stored.split("$", 2)
        salt = bytes.fromhex(salt_hex)
        check = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 120_000)
        return secrets.compare_digest(check.hex(), digest_hex)
    except (ValueError, AttributeError):
        return False


@contextmanager
def _conn() -> Generator[sqlite3.Connection, None, None]:
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(_DB_PATH))
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with _conn() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                email TEXT UNIQUE NOT NULL,
                display_name TEXT NOT NULL,
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS sessions (
                token TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id)
            );
            CREATE TABLE IF NOT EXISTS subscriptions (
                user_id TEXT PRIMARY KEY,
                plan_kind TEXT NOT NULL,
                weekly_price_inr INTEGER NOT NULL,
                daily_limit INTEGER NOT NULL,
                codegen_enabled INTEGER NOT NULL,
                base_plan_kind TEXT NOT NULL,
                base_weekly_price_inr INTEGER NOT NULL,
                base_daily_limit INTEGER NOT NULL,
                boost_count INTEGER NOT NULL DEFAULT 0,
                week_started_at TEXT NOT NULL,
                week_ends_at TEXT NOT NULL,
                active INTEGER NOT NULL DEFAULT 1,
                FOREIGN KEY (user_id) REFERENCES users(id)
            );
            CREATE TABLE IF NOT EXISTS daily_usage (
                user_id TEXT NOT NULL,
                usage_date TEXT NOT NULL,
                edit_count INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (user_id, usage_date)
            );
            CREATE TABLE IF NOT EXISTS payments (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                amount_inr INTEGER NOT NULL,
                payment_type TEXT NOT NULL,
                note TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id)
            );
            """
        )


def create_user(email: str, password: str, display_name: str) -> Dict[str, Any]:
    init_db()
    uid = str(uuid.uuid4())
    with _conn() as conn:
        conn.execute(
            "INSERT INTO users (id, email, display_name, password_hash, created_at) VALUES (?, ?, ?, ?, ?)",
            (uid, email.lower().strip(), display_name.strip(), _hash_password(password), _utc_now_iso()),
        )
    return {"id": uid, "email": email.lower().strip(), "display_name": display_name.strip()}


def authenticate(email: str, password: str) -> Optional[Dict[str, Any]]:
    init_db()
    with _conn() as conn:
        row = conn.execute("SELECT * FROM users WHERE email = ?", (email.lower().strip(),)).fetchone()
        if not row or not _verify_password(password, row["password_hash"]):
            return None
        return dict(row)


def create_session(user_id: str, hours: int = 72) -> str:
    token = secrets.token_urlsafe(32)
    created = datetime.now(timezone.utc)
    expires = created.replace(hour=created.hour)  # noqa — use timedelta
    from datetime import timedelta

    expires = created + timedelta(hours=hours)
    with _conn() as conn:
        conn.execute(
            "INSERT INTO sessions (token, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
            (token, user_id, created.isoformat(), expires.isoformat()),
        )
    return token


def user_from_token(token: str) -> Optional[Dict[str, Any]]:
    init_db()
    with _conn() as conn:
        sess = conn.execute("SELECT * FROM sessions WHERE token = ?", (token,)).fetchone()
        if not sess:
            return None
        if datetime.fromisoformat(sess["expires_at"]) < datetime.now(timezone.utc):
            conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
            return None
        user = conn.execute("SELECT * FROM users WHERE id = ?", (sess["user_id"],)).fetchone()
        return dict(user) if user else None


def delete_session(token: str) -> None:
    with _conn() as conn:
        conn.execute("DELETE FROM sessions WHERE token = ?", (token,))


def _today() -> str:
    return date.today().isoformat()


def _edits_today(conn: sqlite3.Connection, user_id: str) -> int:
    row = conn.execute(
        "SELECT edit_count FROM daily_usage WHERE user_id = ? AND usage_date = ?",
        (user_id, _today()),
    ).fetchone()
    return int(row["edit_count"]) if row else 0


def get_entitlements(user_id: str) -> UserEntitlements:
    init_db()
    with _conn() as conn:
        user = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        if not user:
            raise KeyError(user_id)
        sub = conn.execute("SELECT * FROM subscriptions WHERE user_id = ?", (user_id,)).fetchone()
        edits = _edits_today(conn, user_id)
        return entitlements_from_row(dict(user), dict(sub) if sub else None, edits)


def subscribe(user_id: str, plan_kind: PlanKind) -> UserEntitlements:
    fields = new_subscription_fields(plan_kind)
    with _conn() as conn:
        conn.execute(
            """
            INSERT INTO subscriptions (
                user_id, plan_kind, weekly_price_inr, daily_limit, codegen_enabled,
                base_plan_kind, base_weekly_price_inr, base_daily_limit, boost_count,
                week_started_at, week_ends_at, active
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                plan_kind=excluded.plan_kind,
                weekly_price_inr=excluded.weekly_price_inr,
                daily_limit=excluded.daily_limit,
                codegen_enabled=excluded.codegen_enabled,
                base_plan_kind=excluded.base_plan_kind,
                base_weekly_price_inr=excluded.base_weekly_price_inr,
                base_daily_limit=excluded.base_daily_limit,
                boost_count=excluded.boost_count,
                week_started_at=excluded.week_started_at,
                week_ends_at=excluded.week_ends_at,
                active=excluded.active
            """,
            (
                user_id,
                fields["plan_kind"],
                fields["weekly_price_inr"],
                fields["daily_limit"],
                1 if fields["codegen_enabled"] else 0,
                fields["base_plan_kind"],
                fields["base_weekly_price_inr"],
                fields["base_daily_limit"],
                fields["boost_count"],
                fields["week_started_at"],
                fields["week_ends_at"],
                fields["active"],
            ),
        )
        plan = fields["plan_kind"]
        price = fields["weekly_price_inr"]
        conn.execute(
            "INSERT INTO payments (id, user_id, amount_inr, payment_type, note, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (str(uuid.uuid4()), user_id, price, "subscribe", f"weekly_{plan}", _utc_now_iso()),
        )
    return get_entitlements(user_id)


def upgrade_to_premium(user_id: str) -> UserEntitlements:
    with _conn() as conn:
        sub = conn.execute("SELECT * FROM subscriptions WHERE user_id = ? AND active = 1", (user_id,)).fetchone()
        if not sub:
            raise ValueError("No active subscription")
        if sub["plan_kind"] == PLAN_PREMIUM:
            raise ValueError("Already on Premium")
        fields = premium_upgrade_fields(dict(sub))
        conn.execute(
            """
            UPDATE subscriptions SET
                plan_kind = ?, weekly_price_inr = ?, daily_limit = ?,
                codegen_enabled = ?, base_plan_kind = ?, base_weekly_price_inr = ?,
                base_daily_limit = ?, boost_count = ?
            WHERE user_id = ?
            """,
            (
                fields["plan_kind"],
                fields["weekly_price_inr"],
                fields["daily_limit"],
                1,
                fields["base_plan_kind"],
                fields["base_weekly_price_inr"],
                fields["base_daily_limit"],
                fields["boost_count"],
                user_id,
            ),
        )
        # Charge difference for remainder of week (simplified: full premium price stub)
        conn.execute(
            "INSERT INTO payments (id, user_id, amount_inr, payment_type, note, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (
                str(uuid.uuid4()),
                user_id,
                fields["weekly_price_inr"],
                "upgrade_to_premium",
                "normal_to_premium_midweek",
                _utc_now_iso(),
            ),
        )
    return get_entitlements(user_id)


def apply_premium_boost(user_id: str) -> UserEntitlements:
    with _conn() as conn:
        sub = conn.execute("SELECT * FROM subscriptions WHERE user_id = ? AND active = 1", (user_id,)).fetchone()
        if not sub:
            raise ValueError("No active subscription")
        if sub["plan_kind"] != PLAN_PREMIUM:
            raise ValueError("+50% boost is only for Premium subscribers")
        payment, fields = boost_fields(dict(sub))
        conn.execute(
            "UPDATE subscriptions SET weekly_price_inr = ?, daily_limit = ?, boost_count = ? WHERE user_id = ?",
            (fields["weekly_price_inr"], fields["daily_limit"], fields["boost_count"], user_id),
        )
        conn.execute(
            "INSERT INTO payments (id, user_id, amount_inr, payment_type, note, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (
                str(uuid.uuid4()),
                user_id,
                payment,
                "boost_50",
                f"limit_{fields['daily_limit']}_price_{fields['weekly_price_inr']}",
                _utc_now_iso(),
            ),
        )
    return get_entitlements(user_id)


def renew_subscription(user_id: str, keep_boosted: bool) -> UserEntitlements:
    with _conn() as conn:
        sub = conn.execute("SELECT * FROM subscriptions WHERE user_id = ?", (user_id,)).fetchone()
        if not sub:
            raise ValueError("No subscription")
        sub_d = dict(sub)
        fields = renew_week_fields(sub_d, keep_boosted=keep_boosted)
        if keep_boosted:
            price = int(sub_d["weekly_price_inr"])
            conn.execute(
                """
                UPDATE subscriptions SET
                    week_started_at = ?, week_ends_at = ?, active = 1
                WHERE user_id = ?
                """,
                (fields["week_started_at"], fields["week_ends_at"], user_id),
            )
        else:
            rev = revert_to_base_fields(sub_d)
            price = rev["weekly_price_inr"]
            conn.execute(
                """
                UPDATE subscriptions SET
                    week_started_at = ?, week_ends_at = ?, active = 1,
                    weekly_price_inr = ?, daily_limit = ?, codegen_enabled = ?, boost_count = ?
                WHERE user_id = ?
                """,
                (
                    fields["week_started_at"],
                    fields["week_ends_at"],
                    rev["weekly_price_inr"],
                    rev["daily_limit"],
                    1 if rev["codegen_enabled"] else 0,
                    rev["boost_count"],
                    user_id,
                ),
            )
        conn.execute(
            "INSERT INTO payments (id, user_id, amount_inr, payment_type, note, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (
                str(uuid.uuid4()),
                user_id,
                int(price),
                "renew_week",
                "keep_boosted" if keep_boosted else "revert_base",
                _utc_now_iso(),
            ),
        )
    return get_entitlements(user_id)


def revert_boost_for_new_week(user_id: str) -> UserEntitlements:
    with _conn() as conn:
        sub = conn.execute("SELECT * FROM subscriptions WHERE user_id = ?", (user_id,)).fetchone()
        if not sub:
            raise ValueError("No subscription")
        fields = revert_to_base_fields(dict(sub))
        conn.execute(
            """
            UPDATE subscriptions SET
                weekly_price_inr = ?, daily_limit = ?, codegen_enabled = ?, boost_count = ?
            WHERE user_id = ?
            """,
            (
                fields["weekly_price_inr"],
                fields["daily_limit"],
                1 if fields["codegen_enabled"] else 0,
                fields["boost_count"],
                user_id,
            ),
        )
    return get_entitlements(user_id)


def record_edit(user_id: str) -> UserEntitlements:
    today = _today()
    with _conn() as conn:
        conn.execute(
            """
            INSERT INTO daily_usage (user_id, usage_date, edit_count) VALUES (?, ?, 1)
            ON CONFLICT(user_id, usage_date) DO UPDATE SET edit_count = edit_count + 1
            """,
            (user_id, today),
        )
    return get_entitlements(user_id)


def list_payments(user_id: str, limit: int = 20) -> list[dict]:
    with _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM payments WHERE user_id = ? ORDER BY created_at DESC LIMIT ?",
            (user_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]
