"""Razorpay service — thin wrapper around the Razorpay Python SDK.

All payment-related backend operations go through this service.
NEVER expose key_secret to client. NEVER auto-cancel subscriptions
from app code — cancellation is handled exclusively via support email.
"""

import hmac
import hashlib
from typing import Any

import razorpay
from razorpay.errors import SignatureVerificationError

from src.core.config import get_settings

settings = get_settings()


def _client() -> razorpay.Client:
    """Lazy-initialized Razorpay client. Returns a fresh client with current creds."""
    if not settings.razorpay_key_id or not settings.razorpay_key_secret:
        raise RuntimeError("Razorpay credentials not configured")
    client = razorpay.Client(
        auth=(settings.razorpay_key_id, settings.razorpay_key_secret)
    )
    client.set_app_details({"title": "TarotAI", "version": "1.0.0"})
    return client


# ─────────────────────────────────────────────────────────────
# Payment signature verification
# ─────────────────────────────────────────────────────────────


def verify_payment_signature(
    razorpay_order_id: str,
    razorpay_payment_id: str,
    razorpay_signature: str,
) -> bool:
    """Verify a one-time payment signature from Razorpay checkout.

    Returns True if signature is valid, False otherwise.
    Use after the user completes payment in the Razorpay frontend SDK.
    """
    try:
        params = {
            "razorpay_order_id": razorpay_order_id,
            "razorpay_payment_id": razorpay_payment_id,
            "razorpay_signature": razorpay_signature,
        }
        _client().utility.verify_payment_signature(params)
        return True
    except SignatureVerificationError:
        return False
    except Exception:
        return False


def verify_subscription_payment_signature(
    razorpay_subscription_id: str,
    razorpay_payment_id: str,
    razorpay_signature: str,
) -> bool:
    """Verify a subscription payment signature from Razorpay checkout.

    Subscription payments use a different signature format than one-time payments.
    """
    try:
        params = {
            "razorpay_subscription_id": razorpay_subscription_id,
            "razorpay_payment_id": razorpay_payment_id,
            "razorpay_signature": razorpay_signature,
        }
        _client().utility.verify_subscription_payment_signature(params)
        return True
    except SignatureVerificationError:
        return False
    except Exception:
        return False


# ─────────────────────────────────────────────────────────────
# Webhook signature verification
# ─────────────────────────────────────────────────────────────


def verify_webhook_signature(payload: bytes, signature: str) -> bool:
    """Verify a Razorpay webhook signature using HMAC-SHA256.

    payload: raw request body bytes
    signature: value of `X-Razorpay-Signature` header
    Returns True if valid, False otherwise.
    """
    if not settings.razorpay_webhook_secret:
        return False
    expected = hmac.new(
        settings.razorpay_webhook_secret.encode("utf-8"),
        payload,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


# ─────────────────────────────────────────────────────────────
# Subscription helpers (read-only / admin-only)
# ─────────────────────────────────────────────────────────────


def get_subscription(subscription_id: str) -> dict[str, Any]:
    """Fetch subscription details from Razorpay. Read-only."""
    return _client().subscription.fetch(subscription_id)


def get_payment(payment_id: str) -> dict[str, Any]:
    """Fetch payment details. Read-only."""
    return _client().payment.fetch(payment_id)


def cancel_subscription_admin_only(
    subscription_id: str, cancel_at_cycle_end: bool = True
) -> dict[str, Any]:
    """Cancel a subscription. ADMIN-ONLY — never call from user-facing routes.

    Per project policy, autopay/subscription cancellation is handled
    exclusively via support email. This helper exists only for the
    support team to use via direct backend access (e.g., /admin/* routes
    or one-off scripts).

    cancel_at_cycle_end: True = cancel at end of current period (recommended,
    user keeps access until period ends). False = cancel immediately.
    """
    return _client().subscription.cancel(
        subscription_id,
        {"cancel_at_cycle_end": 1 if cancel_at_cycle_end else 0},
    )
