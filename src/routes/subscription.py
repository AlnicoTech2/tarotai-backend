"""Razorpay subscription management — create-order + verify.

All subscription/payment logic is backend-heavy. Frontend only gets
subscription_id + key_id, launches Razorpay checkout, and sends back
the signature for verification.

NEVER cancels autopay from this code. Cancellation is via support email only.
"""

import hashlib
import hmac
import logging
from datetime import datetime, timedelta, timezone

import httpx
from src.core.limiter import limiter
from fastapi import APIRouter, Depends, HTTPException, status, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import get_settings
from src.core.database import get_db
from src.middleware.auth import get_current_user
from src.models.user import User

log = logging.getLogger("subscription")
settings = get_settings()

router = APIRouter(prefix="/subscription", tags=["subscription"])

RAZORPAY_BASE = "https://api.razorpay.com/v1"


def _rz_auth():
    return (settings.razorpay_key_id, settings.razorpay_key_secret)


def _get_config():
    """Read APP_CONFIG from main module."""
    from main import APP_CONFIG
    return APP_CONFIG


def _build_plans(cfg: dict) -> dict:
    return {
        "trial": {
            "plan_id": cfg.get("razorpay_monthly_plan_id", ""),
            "label": "TarotAI Premium Trial",
            "total_count": cfg.get("razorpay_monthly_cycles", 131),
            "is_trial": True,
        },
        "monthly": {
            "plan_id": cfg.get("razorpay_monthly_plan_id", ""),
            "label": cfg.get("razorpay_monthly_label", "TarotAI Premium Monthly"),
            "total_count": cfg.get("razorpay_monthly_cycles", 131),
            "is_trial": False,
        },
        "yearly": {
            "plan_id": cfg.get("razorpay_yearly_plan_id", ""),
            "label": cfg.get("razorpay_yearly_label", "TarotAI Premium Yearly"),
            "total_count": cfg.get("razorpay_yearly_cycles", 10),
            "is_trial": False,
        },
    }


# ─────────────────────────────────────────────────
# CREATE ORDER
# ─────────────────────────────────────────────────


class CreateOrderRequest(BaseModel):
    plan: str  # "trial", "monthly", or "yearly"


class CreateOrderResponse(BaseModel):
    subscription_id: str
    key_id: str
    plan_label: str


@limiter.limit("5/minute")
@limiter.limit("10/minute")
@router.post("/create-order", response_model=CreateOrderResponse)
async def create_order(
    request: Request,
    body: CreateOrderRequest,
    firebase_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create Razorpay subscription. Returns subscription_id for frontend checkout."""
    cfg = _get_config()
    plans = _build_plans(cfg)
    plan = plans.get(body.plan)

    if not plan:
        raise HTTPException(status_code=400, detail=f"Invalid plan: {body.plan}")
    if not plan["plan_id"]:
        raise HTTPException(status_code=500, detail="Plan ID not configured")

    # Get user
    result = await db.execute(
        select(User).where(User.firebase_uid == firebase_user["uid"])
    )
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Trial spam guard
    if plan["is_trial"] and user.has_subscribed_before:
        raise HTTPException(
            status_code=400,
            detail="Trial already used. Please choose a monthly plan.",
        )

    async with httpx.AsyncClient(timeout=15.0) as client:
        # 1. Create/fetch Razorpay customer (fail_existing=0 returns existing)
        customer_resp = await client.post(
            f"{RAZORPAY_BASE}/customers",
            auth=_rz_auth(),
            json={
                "name": (user.name or user.email or "TarotAI User")[:50],
                "email": user.email or "",
                "contact": "+919999999999",
                "fail_existing": "0",
            },
        )
        if customer_resp.status_code != 200:
            log.error(f"Customer creation failed: {customer_resp.text}")
            raise HTTPException(status_code=500, detail="Customer creation failed")
        customer = customer_resp.json()

        # 2. Build subscription payload
        sub_body: dict = {
            "plan_id": plan["plan_id"],
            "customer_id": customer["id"],
            "total_count": plan["total_count"],
            "quantity": 1,
            "customer_notify": 1,
            "notes": {
                "userId": str(user.id),
                "plan": body.plan,
                "email": user.email or "",
            },
        }

        # 3. Trial: addon charge + delayed start
        if plan["is_trial"] and cfg.get("trial_enabled", False):
            trial_days = cfg.get("trial_days", 1)
            trial_price = cfg.get("trial_price", 5)
            start_at = int(datetime.now(timezone.utc).timestamp()) + (trial_days * 86400)
            sub_body["start_at"] = start_at
            sub_body["addons"] = [
                {
                    "item": {
                        "name": cfg.get("trial_addon_name", "Trial Access Fee"),
                        "amount": trial_price * 100,  # paise
                        "currency": "INR",
                    }
                }
            ]
            sub_body["notes"]["trial_days"] = str(trial_days)

        # 4. Create subscription on Razorpay
        sub_resp = await client.post(
            f"{RAZORPAY_BASE}/subscriptions",
            auth=_rz_auth(),
            json=sub_body,
        )
        if sub_resp.status_code not in (200, 201):
            log.error(f"Subscription creation failed: {sub_resp.text}")
            raise HTTPException(
                status_code=500,
                detail="Subscription creation failed. Please try again.",
            )
        subscription = sub_resp.json()

    return CreateOrderResponse(
        subscription_id=subscription["id"],
        key_id=settings.razorpay_key_id,
        plan_label=plan["label"],
    )


# ─────────────────────────────────────────────────
# VERIFY PAYMENT
# ─────────────────────────────────────────────────


class VerifyRequest(BaseModel):
    razorpay_payment_id: str
    razorpay_subscription_id: str
    razorpay_signature: str


class VerifyResponse(BaseModel):
    success: bool
    tier: str
    subscription_end: str | None


@router.post("/verify", response_model=VerifyResponse)
async def verify_payment(
    request: Request,
    body: VerifyRequest,
    firebase_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Verify Razorpay subscription payment signature and upgrade user."""
    cfg = _get_config()

    # 1. Verify signature: HMAC-SHA256(payment_id|subscription_id, key_secret)
    expected = hmac.new(
        settings.razorpay_key_secret.encode("utf-8"),
        f"{body.razorpay_payment_id}|{body.razorpay_subscription_id}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(expected, body.razorpay_signature):
        raise HTTPException(status_code=400, detail="Invalid payment signature")

    # 2. Get user
    result = await db.execute(
        select(User).where(User.firebase_uid == firebase_user["uid"])
    )
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # 3. Fetch subscription from Razorpay to get current_end
    subscription_end: str | None = None
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            sub_resp = await client.get(
                f"{RAZORPAY_BASE}/subscriptions/{body.razorpay_subscription_id}",
                auth=_rz_auth(),
            )
            if sub_resp.status_code == 200:
                sub = sub_resp.json()

                # Ownership check
                sub_user_id = (sub.get("notes") or {}).get("userId")
                if sub_user_id and sub_user_id != str(user.id):
                    raise HTTPException(
                        status_code=403,
                        detail="Subscription does not belong to this user",
                    )

                # Calculate end date
                if sub.get("current_end"):
                    subscription_end = datetime.fromtimestamp(
                        sub["current_end"], tz=timezone.utc
                    ).isoformat()
                elif (sub.get("notes") or {}).get("plan") == "trial":
                    # Trial: current_end is null until start_at
                    trial_days = int(
                        (sub.get("notes") or {}).get("trial_days", cfg.get("trial_days", 1))
                    )
                    subscription_end = (
                        datetime.now(timezone.utc) + timedelta(days=trial_days)
                    ).isoformat()
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Failed to fetch subscription: {e}")
        # Continue anyway — signature is verified, upgrade the user

    # 4. Upgrade user
    user.is_premium = True
    user.razorpay_subscription_id = body.razorpay_subscription_id
    # Detect plan from subscription notes
    plan_type = (sub.get("notes") or {}).get("plan", "monthly") if sub else "monthly"
    user.subscription_plan = plan_type if plan_type in ("monthly", "yearly") else "monthly"
    user.has_subscribed_before = True
    if subscription_end:
        user.subscription_expires_at = datetime.fromisoformat(subscription_end)

    await db.commit()

    log.info(
        f"Payment verified: user={user.id} sub={body.razorpay_subscription_id} "
        f"ends={subscription_end}"
    )

    return VerifyResponse(
        success=True,
        tier="premium",
        subscription_end=subscription_end,
    )
