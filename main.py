from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from src.core.limiter import limiter

from src.core.config import get_settings
from src.core.firebase import init_firebase
from src.routes import auth, readings, cards, horoscope, daily_card, razorpay_webhook, subscription, cron, chat

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    init_firebase()
    yield
    # Shutdown


_is_prod = settings.app_env == "production"

app = FastAPI(
    title="TarotAI API",
    version="0.1.0",
    lifespan=lifespan,
    docs_url=None if _is_prod else "/docs",
    redoc_url=None if _is_prod else "/redoc",
    openapi_url=None if _is_prod else "/openapi.json",
)

# ── Rate limiting (denial-of-wallet protection) ──
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


# ── Security headers (defense-in-depth) ──
@app.middleware("http")
async def security_headers(request, call_next):
    response = await call_next(request)
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
    return response

ALLOWED_ORIGINS = [
    "https://tarotai.alnicotech.com",
]

app.add_middleware(ProxyHeadersMiddleware, trusted_hosts="*")

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routes
app.include_router(auth.router, prefix="/api/v1")
app.include_router(readings.router, prefix="/api/v1")
app.include_router(cards.router, prefix="/api/v1")
app.include_router(horoscope.router, prefix="/api/v1")
app.include_router(daily_card.router, prefix="/api/v1")
app.include_router(razorpay_webhook.router, prefix="/api/v1")
app.include_router(subscription.router, prefix="/api/v1")
app.include_router(cron.router, prefix="/api/v1")
app.include_router(chat.router, prefix="/api/v1")


@app.get("/health")
async def health():
    return {"status": "ok", "version": "0.1.0"}


# ── App config (no auth required) ──
# Change these values to update app behavior without a rebuild
APP_CONFIG = {
    # Splash + quotas
    "splash_duration_ms": 3000,
    "free_readings_per_month": 3,

    # Version control
    "min_app_version": "1.0.0",
    "latest_app_version": "1.0.0",
    "play_store_url": "https://play.google.com/store/apps/details?id=com.alnico.tarotai",
    "update_force_title": "Update Required",
    "update_force_message": "A new version of TarotAI is available. Please update to continue.",
    "update_alert_title": "Update Available",
    "update_alert_message": "A new version of TarotAI is available with improvements.",
    "update_now_text": "Update Now",
    "update_later_text": "Later",

    # Maintenance mode
    "maintenance_mode": False,
    "maintenance_title": "Under Maintenance",
    "maintenance_message": "TarotAI is under maintenance. We'll be back shortly!",

    # Reviewer/admin login
    "admin_tap_count": 10,
    "admin_tap_reset_ms": 3000,

    # In-app review prompt
    "review_first_prompt_at": 3,
    "review_repeat_prompt_at": 10,
    "review_high_rating_cooldown_days": 60,
    "review_low_rating_cooldown_days": 30,
    "review_prompt_delay_ms": 2500,

    # Razorpay (public — key_id only, NEVER expose key_secret)
    "razorpay_key_id": "rzp_live_Sdkr8O1jCrVrFN",
    "razorpay_currency": "INR",

    # Razorpay plan config (backend-only IDs stripped from client response)
    "razorpay_monthly_plan_id": "plan_SeT3dDCJkLFfgL",
    "razorpay_monthly_label": "TarotAI Premium Monthly",
    "razorpay_monthly_cycles": 131,
    "razorpay_yearly_plan_id": "plan_SeT3dfYsfBbKWc",
    "razorpay_yearly_label": "TarotAI Premium Yearly",
    "razorpay_yearly_cycles": 10,

    # Trial config
    "trial_enabled": True,
    "trial_price": 5,
    "trial_days": 1,
    "trial_addon_name": "Trial Access Fee",
    "trial_title": "Premium Trial",
    "trial_description": "",
    "trial_gateway_text": "(Pay only Gateway Charges)",
    "trial_save_text": "Save 95%",

    # Paywall display prices
    "subscription_monthly_price": "\u20b999",
    "subscription_yearly_price": "\u20b9999",
    "subscription_yearly_save_percent": 22,

    # Paywall plan visibility (config-driven toggle)
    "paywall_new_user_plans": ["trial"],
    "paywall_returning_user_plans": ["monthly"],
}


@app.get("/api/v1/config")
async def get_app_config():
    return APP_CONFIG


LEGAL_PAGE_STYLE = """
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
         background: #0a0a0f; color: #e0e0e0; line-height: 1.7; padding: 40px 20px; }
  .container { max-width: 720px; margin: 0 auto; }
  h1 { color: #c8a84e; font-size: 28px; margin-bottom: 8px; }
  .subtitle { color: #888; font-size: 14px; margin-bottom: 32px; }
  h2 { color: #c8a84e; font-size: 18px; margin-top: 28px; margin-bottom: 12px; }
  p, li { font-size: 15px; margin-bottom: 12px; }
  ul { padding-left: 20px; }
  a { color: #c8a84e; }
  .footer { margin-top: 40px; padding-top: 20px; border-top: 1px solid #222; color: #666; font-size: 13px; }
</style>
"""

APP_NAME = "TarotAI - Free Kundli"
COMPANY = "Alnico Tech Private Limited"
SUPPORT_EMAIL = "support@alnicotech.com"


@app.get("/privacy", response_class=HTMLResponse)
async def privacy_policy():
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Privacy Policy — Tarot AI – Kundali App</title>{LEGAL_PAGE_STYLE}</head><body><div class="container">
<h1>Privacy Policy</h1>
<p class="subtitle">Tarot AI – Kundali App by {COMPANY} | Effective: January 23, 2025</p>

<p>This Privacy Policy applies to the Tarot AI – Kundali App ("Application"), developed and operated by {COMPANY} ("Service Provider", "we", "our", or "us"). The Application is provided as a free service and is intended for use on an "AS IS" basis.</p>

<h2>Information We Collect</h2>
<p>When you install and use the Application, we may collect certain information automatically, including:</p>
<ul>
<li>Device IP address</li>
<li>Device type and operating system</li>
<li>App usage behavior such as features accessed and time spent</li>
<li>Session duration and interaction patterns</li>
</ul>
<p>Additionally, to provide personalized astrology and tarot readings, you may be asked to enter certain information such as:</p>
<ul>
<li>Name</li>
<li>Date of birth</li>
<li>Time of birth (optional)</li>
<li>Location (optional)</li>
</ul>
<p>This information is used solely to generate accurate predictions and improve user experience.</p>

<h2>How We Use Your Information</h2>
<p>We use the collected data to:</p>
<ul>
<li>Provide tarot readings and kundali (astrology) insights</li>
<li>Personalize user experience and content</li>
<li>Improve app performance and features</li>
<li>Send important updates or notifications</li>
<li>Ensure security and prevent misuse</li>
</ul>

<h2>Location Information</h2>
<p>We do not collect precise GPS location. However, approximate location data may be used (if provided by the user) to enhance astrology calculations and improve accuracy.</p>

<h2>AI &amp; Content Processing</h2>
<p>The Application may use AI-based systems to generate tarot insights and astrology predictions.</p>
<p>All outputs are generated automatically and are intended for informational and entertainment purposes only.</p>

<h2>Information Sharing</h2>
<p>We do not sell or rent your personal data. However, we may share information:</p>
<ul>
<li>To comply with legal obligations or requests</li>
<li>To protect rights, safety, or investigate fraud</li>
<li>With trusted third-party services that help operate the Application under strict confidentiality</li>
</ul>

<h2>User Control &amp; Opt-Out</h2>
<p>You can stop all data collection by uninstalling the Application from your device.</p>
<p>You may also choose not to provide optional personal information, though some features may not function properly.</p>

<h2>Data Retention</h2>
<p>We retain your data only as long as necessary to provide our services and for legitimate business purposes.</p>
<p>To request deletion of your data, contact us at: <a href="mailto:{SUPPORT_EMAIL}">📧 {SUPPORT_EMAIL}</a></p>
<p>We will process your request within a reasonable timeframe.</p>

<h2>Children's Privacy</h2>
<p>This Application is not intended for users under the age of 18.</p>
<p>We do not knowingly collect personal information from children. If such data is identified, it will be deleted immediately.</p>

<h2>Security</h2>
<p>We implement appropriate technical and organizational measures to safeguard your information from unauthorized access, loss, or misuse.</p>

<h2>Third-Party Services</h2>
<p>The Application may use third-party tools (such as analytics or ads) that may collect limited information in accordance with their own privacy policies.</p>

<h2>Changes to This Policy</h2>
<p>We may update this Privacy Policy from time to time. Any changes will be reflected within the Application or on this page.</p>

<h2>Effective Date</h2>
<p>January 23, 2025</p>

<h2>Your Consent</h2>
<p>By using the Tarot AI – Kundali App, you agree to the collection and use of information as outlined in this Privacy Policy.</p>

<h2>Contact Us</h2>
<p>If you have any questions regarding this Privacy Policy, please contact us at: <a href="mailto:{SUPPORT_EMAIL}">📧 {SUPPORT_EMAIL}</a></p>

<div class="footer">&copy; 2025 {COMPANY}. All rights reserved.</div>
</div></body></html>"""


@app.get("/terms", response_class=HTMLResponse)
async def terms_and_conditions():
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Terms & Conditions — {APP_NAME}</title>{LEGAL_PAGE_STYLE}</head><body><div class="container">
<h1>Terms &amp; Conditions</h1>
<p class="subtitle">{APP_NAME} by {COMPANY} | Effective: January 23, 2025</p>

<h2>1. Acceptance of Terms</h2>
<p>By downloading, installing, or using {APP_NAME} ("the Application"), you agree to be bound by these Terms and Conditions. If you do not agree, please do not use the Application.</p>

<h2>2. Description of Service</h2>
<p>The Application provides AI-generated tarot card readings and Vedic astrology (Kundli) insights. All content is generated using artificial intelligence and is for <strong>entertainment and informational purposes only</strong>.</p>

<h2>3. Eligibility</h2>
<p>You must be at least 18 years of age to use this Application. If you are under 18, you must have the consent of a parent or legal guardian.</p>

<h2>4. Disclaimer</h2>
<p>Readings and astrological insights provided by this Application should not be considered a substitute for professional legal, medical, financial, or psychological guidance. You are solely responsible for any decisions made based on the Application's insights.</p>

<h2>5. User Obligations</h2>
<p>You agree to:</p>
<ul>
<li>Use the Application only for lawful purposes.</li>
<li>Not input false or misleading information.</li>
<li>Not attempt to disrupt, hack, or reverse-engineer the Application.</li>
<li>Not use the Application to harass, defame, or harm others.</li>
</ul>

<h2>6. Accounts & Authentication</h2>
<p>You may sign in using Google Sign-In or phone OTP via Firebase Authentication. You are responsible for maintaining the security of your account credentials.</p>

<h2>7. Subscriptions & Payments</h2>
<ul>
<li>Free users receive a limited number of readings per month.</li>
<li>Premium subscriptions unlock unlimited readings and additional features.</li>
<li>Subscriptions renew automatically unless cancelled before the renewal date.</li>
<li>Cancellations can be made through your app store settings or by contacting <a href="mailto:{SUPPORT_EMAIL}">{SUPPORT_EMAIL}</a>.</li>
<li>Payments are non-refundable except where required by applicable law.</li>
</ul>

<h2>8. Intellectual Property</h2>
<p>All content, design, AI models, and branding within the Application are the intellectual property of {COMPANY}. Tarot card artwork uses public domain Rider-Waite-Smith illustrations.</p>

<h2>9. Limitation of Liability</h2>
<p>The Application is provided on an "as is" basis. {COMPANY} disclaims responsibility for:</p>
<ul>
<li>Service interruptions or errors.</li>
<li>Inaccuracies in AI-generated content.</li>
<li>Third-party services integrated into the Application.</li>
<li>Any damages arising from the use of the Application.</li>
</ul>

<h2>10. Governing Law</h2>
<p>These Terms are governed by the laws of India. Any disputes shall be subject to the exclusive jurisdiction of the courts of Mumbai, Maharashtra.</p>

<h2>11. Changes to Terms</h2>
<p>We reserve the right to modify these Terms at any time. Continued use of the Application after changes constitutes acceptance of the updated Terms.</p>

<h2>12. Contact Us</h2>
<p>For questions or concerns, contact us at: <a href="mailto:{SUPPORT_EMAIL}">{SUPPORT_EMAIL}</a></p>

<div class="footer">&copy; 2025 {COMPANY}. All rights reserved.</div>
</div></body></html>"""


@app.get("/support", response_class=HTMLResponse)
async def support_page():
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Support — {APP_NAME}</title>{LEGAL_PAGE_STYLE}</head><body><div class="container">
<h1>Support</h1>
<p class="subtitle">{APP_NAME} by {COMPANY}</p>

<h2>Need Help?</h2>
<p>For any issues, questions, or feedback about the app, please reach out to us:</p>

<h2>Email</h2>
<p><a href="mailto:{SUPPORT_EMAIL}">{SUPPORT_EMAIL}</a></p>

<h2>Common Issues</h2>
<ul>
<li><strong>Login issues:</strong> Ensure you have a stable internet connection and are using the same Google account you registered with.</li>
<li><strong>Reading not loading:</strong> AI readings may take 10-30 seconds to generate. Please wait for the full response.</li>
<li><strong>Subscription issues:</strong> Contact us with your registered email and transaction ID for assistance.</li>
<li><strong>Data deletion:</strong> Email us at {SUPPORT_EMAIL} to request deletion of your account and all associated data.</li>
</ul>

<h2>Response Time</h2>
<p>We aim to respond to all support queries within 24-48 hours.</p>

<div class="footer">&copy; 2025 {COMPANY}. All rights reserved.</div>
</div></body></html>"""


@app.get("/refund", response_class=HTMLResponse)
async def refund_page():
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Refund Policy — Tarot AI – Kundali App</title>{LEGAL_PAGE_STYLE}</head><body><div class="container">
<h1>Refund Policy – Tarot AI – Kundali App</h1>
<p class="subtitle">{COMPANY}</p>

<p>This Refund Policy applies to the Tarot AI – Kundali App ("Application"), developed and operated by {COMPANY} ("Company", "we", "our", or "us").</p>

<h2>1. Subscription Payments</h2>
<p>The Application may offer premium features through paid subscriptions (monthly or annual).</p>
<p>All payments are securely processed through third-party platforms such as:</p>
<ul>
<li>Google Play Store</li>
</ul>

<h2>2. No Refund Policy</h2>
<p>All purchases and subscription payments are non-refundable, except where required by applicable laws or platform policies.</p>
<p>Once a subscription is activated:</p>
<ul>
<li>You will retain access to premium features until the end of the billing period</li>
<li>No refunds, partial refunds, or credits will be issued for unused time</li>
</ul>

<h2>3. Subscription Cancellation</h2>
<p>You may cancel your subscription at any time:</p>
<ul>
<li>Through your Google Play account settings</li>
<li>Or by contacting us at <a href="mailto:{SUPPORT_EMAIL}">{SUPPORT_EMAIL}</a></li>
</ul>
<p>After cancellation:</p>
<ul>
<li>No future charges will apply</li>
<li>Your current subscription will remain active until the end of the billing period</li>
</ul>

<h2>4. Platform-Based Refunds</h2>
<p>All refund requests, if applicable, must be made directly through the platform provider:</p>
<ul>
<li>Google Play purchases are subject to Google Play's refund policies</li>
</ul>
<p>We do not process or control refunds handled by the platform.</p>

<h2>5. Digital Service Disclaimer</h2>
<p>The Application provides digital services that are delivered instantly upon purchase.</p>
<p>Due to the nature of digital content:</p>
<ul>
<li>Refunds are not applicable once the service has been accessed or used</li>
</ul>

<h2>6. Contact Us</h2>
<p>If you have any questions regarding this Refund Policy, please contact us at:</p>
<p><a href="mailto:{SUPPORT_EMAIL}">📧 {SUPPORT_EMAIL}</a></p>

<div class="footer">&copy; 2025 {COMPANY}. All rights reserved.</div>
</div></body></html>"""
