"""Razorpay webhook handler.

Listens for subscription + payment events from Razorpay.
Endpoint: POST /api/v1/razorpay/webhook
Public (no Firebase auth). HMAC-SHA256 signature verified against webhook secret.

IMPORTANT:
- This endpoint does NOT initiate any cancellation. Per project policy,
  autopay cancellation is handled exclusively via support email.
- The webhook REACTS to Razorpay/bank-initiated events — it doesn't trigger them.
"""

import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy import select

from src.core.database import get_db
from src.models.user import User
from src.services.razorpay_service import verify_webhook_signature

log = logging.getLogger("razorpay.webhook")
log.setLevel(logging.INFO)

router = APIRouter(prefix="/razorpay", tags=["razorpay"])


# Plan ID → plan tier mapping. Add entries here when you create plans in dashboard.
# Example: PLAN_TIER_MAP = {"plan_ABCXYZ": "weekly", "plan_DEF123": "monthly", ...}
PLAN_TIER_MAP: dict[str, str] = {}

# Heuristic duration per plan tier — used if a subscription.activated event
# doesn't contain explicit next_billed_at. Adjust when you create plans.
PLAN_DURATION_DAYS: dict[str, int] = {
    "weekly": 7,
    "monthly": 30,
    "yearly": 365,
}


def _parse_razorpay_epoch(epoch: int | None) -> datetime | None:
    if not epoch:
        return None
    try:
        return datetime.fromtimestamp(int(epoch), tz=timezone.utc)
    except Exception:
        return None


async def _find_user_by_subscription_id(
    session, subscription_id: str
) -> User | None:
    result = await session.execute(
        select(User).where(User.razorpay_subscription_id == subscription_id)
    )
    return result.scalar_one_or_none()


async def _find_user_by_email(session, email: str | None) -> User | None:
    if not email:
        return None
    result = await session.execute(select(User).where(User.email == email))
    return result.scalar_one_or_none()


@router.post("/webhook", status_code=status.HTTP_200_OK)
async def razorpay_webhook(request: Request):
    """Receive Razorpay webhook. Verify signature, update user subscription state."""

    # 1. Read raw body (required for signature verification)
    raw_body = await request.body()
    signature = request.headers.get("x-razorpay-signature", "")

    if not signature:
        log.warning("webhook: missing X-Razorpay-Signature header")
        raise HTTPException(status_code=400, detail="Missing signature")

    if not verify_webhook_signature(raw_body, signature):
        log.warning("webhook: invalid signature")
        raise HTTPException(status_code=400, detail="Invalid signature")

    # 2. Parse payload
    try:
        import json

        payload = json.loads(raw_body.decode("utf-8"))
    except Exception as e:
        log.error(f"webhook: bad JSON — {e}")
        raise HTTPException(status_code=400, detail="Invalid JSON")

    event_type = payload.get("event", "unknown")
    event_id = request.headers.get("x-razorpay-event-id", "")
    created_at = payload.get("created_at", 0)
    log.info(f"webhook event received: {event_type} id={event_id}")

    # Replay protection: reject events older than 72 hours
    if created_at and (int(datetime.now(timezone.utc).timestamp()) - created_at) > 259200:
        log.warning(f"webhook: stale event={event_type} — dropped")
        return {"status": "ok", "event": event_type, "note": "stale"}

    # 3. Process event — wrap in get_db generator
    gen = get_db()
    session = await anext(gen)
    try:
        await _dispatch_event(session, event_type, payload)
        await session.commit()
    except HTTPException:
        raise
    except Exception as e:
        log.exception(f"webhook: error handling {event_type} — {e}")
        # Return 200 anyway so Razorpay doesn't retry indefinitely.
        # We've logged the error for investigation.
    finally:
        try:
            await anext(gen)
        except StopAsyncIteration:
            pass

    return {"status": "ok", "event": event_type}


async def _dispatch_event(session, event_type: str, payload: dict):
    """Dispatch to event-specific handler. Unknown events are logged and no-op."""
    entity = payload.get("payload", {})

    # ─── SUBSCRIPTION EVENTS ───
    if event_type in {
        "subscription.activated",
        "subscription.authenticated",
    }:
        await _handle_subscription_active(session, entity)
    elif event_type == "subscription.charged":
        await _handle_subscription_charged(session, entity)
    elif event_type in {
        "subscription.cancelled",
        "subscription.completed",
        "subscription.halted",
        "subscription.paused",
        "subscription.expired",
    }:
        await _handle_subscription_inactive(session, entity, event_type)

    # ─── PAYMENT EVENTS (one-time purchases, optional) ───
    elif event_type == "payment.captured":
        await _handle_payment_captured(session, entity)
    elif event_type == "payment.failed":
        log.info(f"webhook: payment failed — {entity.get('payment', {}).get('entity', {}).get('id')}")

    # ─── UNKNOWN ───
    else:
        log.info(f"webhook: unhandled event — {event_type}")


async def _handle_subscription_active(session, entity: dict):
    """Subscription is active or just charged — grant premium access."""
    sub = entity.get("subscription", {}).get("entity", {})
    sub_id = sub.get("id")
    plan_id = sub.get("plan_id")
    customer_id = sub.get("customer_id")
    current_end = _parse_razorpay_epoch(sub.get("current_end"))
    notes = sub.get("notes") or {}
    user_email = notes.get("user_email") or notes.get("email")

    if not sub_id:
        log.warning(f"sub active: missing subscription id — sub={sub}")
        return

    # Locate user: first by stored subscription_id, else by email in notes
    user = await _find_user_by_subscription_id(session, sub_id)
    if not user and user_email:
        user = await _find_user_by_email(session, user_email)
        if user:
            user.razorpay_subscription_id = sub_id

    if not user:
        log.warning(f"sub active: user not found for sub={sub_id}, email={user_email}")
        return

    # Determine tier from plan ID mapping
    tier = PLAN_TIER_MAP.get(plan_id or "", user.subscription_plan or "monthly")

    # Compute expiry: prefer Razorpay's current_end, fall back to duration heuristic
    if current_end:
        expires_at = current_end
    else:
        days = PLAN_DURATION_DAYS.get(tier, 30)
        expires_at = datetime.now(timezone.utc) + timedelta(days=days)

    user.is_premium = True
    user.subscription_plan = tier
    user.subscription_expires_at = expires_at
    user.razorpay_subscription_id = sub_id

    log.info(
        f"sub active: user={user.id} sub={sub_id} plan={tier} "
        f"expires={expires_at.isoformat()}"
    )


async def _handle_subscription_charged(session, entity: dict):
    """Subscription charged — detect trial addon vs regular recurring charge."""
    from main import APP_CONFIG
    sub = entity.get("subscription", {}).get("entity", {})
    payment = entity.get("payment", {}).get("entity", {})
    sub_id = sub.get("id")
    notes = sub.get("notes") or {}
    user_email = notes.get("email")

    trial_price_paise = APP_CONFIG.get("trial_price", 5) * 100
    is_addon_charge = (
        payment
        and payment.get("amount", 0) <= trial_price_paise
        and not sub.get("current_end")
    )

    user = await _find_user_by_subscription_id(session, sub_id) if sub_id else None
    if not user and user_email:
        user = await _find_user_by_email(session, user_email)
    if not user:
        log.warning(f"sub charged: user not found for sub={sub_id}")
        return

    if is_addon_charge:
        # Trial addon — upgrade with trial-specific end date
        trial_days = int(notes.get("trial_days", APP_CONFIG.get("trial_days", 1)))
        trial_end = datetime.now(timezone.utc) + timedelta(days=trial_days)
        user.is_premium = True
        user.has_subscribed_before = True
        user.razorpay_subscription_id = sub_id
        user.subscription_plan = "monthly"
        user.subscription_expires_at = trial_end
        log.info(f"sub charged (trial addon): user={user.id} trial_end={trial_end.isoformat()}")
    else:
        # Regular recurring charge
        current_end = _parse_razorpay_epoch(sub.get("current_end"))
        expires_at = current_end or (datetime.now(timezone.utc) + timedelta(days=30))
        user.is_premium = True
        user.has_subscribed_before = True
        user.razorpay_subscription_id = sub_id
        user.subscription_plan = "monthly"
        user.subscription_expires_at = expires_at
        log.info(f"sub charged (recurring): user={user.id} expires={expires_at.isoformat()}")


async def _handle_subscription_inactive(session, entity: dict, event_type: str):
    """Subscription ended — let access expire naturally at current_end.

    We do NOT flip is_premium=False immediately. User already paid for the
    current period; they keep premium until expires_at passes. A scheduled
    job (daily cron) should sweep expired subs and downgrade them.

    Exception: subscription.halted = payment failure → revoke immediately.
    """
    sub = entity.get("subscription", {}).get("entity", {})
    sub_id = sub.get("id")

    user = await _find_user_by_subscription_id(session, sub_id) if sub_id else None
    if not user:
        log.info(f"sub {event_type}: user not found for sub={sub_id}")
        return

    if event_type == "subscription.halted":
        user.is_premium = False
        user.subscription_expires_at = datetime.now(timezone.utc)
        log.info(f"sub halted: user={user.id} premium revoked due to payment failure")
    else:
        # cancelled / completed / paused / expired — keep premium until expires_at.
        # subscription.cancelled with cancel_at_cycle_end=0 will have current_end=now,
        # so the natural expiry sweeper will downgrade them on next run.
        log.info(
            f"sub {event_type}: user={user.id} sub={sub_id} — premium retained "
            f"until {user.subscription_expires_at}"
        )


async def _handle_payment_captured(session, entity: dict):
    """One-time payment captured. Useful for one-off IAP (e.g., yearly forecast PDF)."""
    payment = entity.get("payment", {}).get("entity", {})
    payment_id = payment.get("id")
    amount = payment.get("amount")  # in paise
    notes = payment.get("notes") or {}
    user_email = notes.get("user_email") or notes.get("email")
    purpose = notes.get("purpose")  # e.g., "yearly_forecast_pdf"

    log.info(
        f"payment captured: id={payment_id} amount={amount} "
        f"email={user_email} purpose={purpose}"
    )
    # No automatic user update yet — add logic here when one-time products exist.
