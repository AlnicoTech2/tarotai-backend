from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse

from src.core.config import get_settings
from src.core.firebase import init_firebase
from src.routes import auth, readings, cards, horoscope, daily_card, razorpay_webhook, subscription, cron

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    init_firebase()
    yield
    # Shutdown


app = FastAPI(
    title="TarotAI API",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if settings.debug else [],
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
    "trial_enabled": False,
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
<title>Privacy Policy — {APP_NAME}</title>{LEGAL_PAGE_STYLE}</head><body><div class="container">
<h1>Privacy Policy</h1>
<p class="subtitle">{APP_NAME} by {COMPANY} | Effective: January 23, 2025</p>

<h2>1. Information We Collect</h2>
<p>We collect the following information to provide our services:</p>
<ul>
<li><strong>Account Information:</strong> Name, email address, phone number (via Firebase Authentication — Google Sign-In or phone OTP).</li>
<li><strong>Birth Details (optional):</strong> Date of birth, time of birth, and city of birth — used to generate personalised astrology (Kundli) readings.</li>
<li><strong>Device Information:</strong> Device IP address, device type, operating system, and app usage patterns.</li>
<li><strong>Reading Data:</strong> Tarot card readings, questions asked, and AI-generated interpretations are stored to improve personalisation over time.</li>
</ul>

<h2>2. How We Use Your Information</h2>
<ul>
<li>To provide tarot readings and Kundli (astrology) insights.</li>
<li>To personalise user experience and content based on your birth chart and reading history.</li>
<li>To improve app functionality and AI accuracy.</li>
<li>To send push notifications (daily card, horoscope) if you opt in.</li>
<li>To process payments and manage subscriptions.</li>
</ul>

<h2>3. Data Sharing</h2>
<p>We do not sell or rent your personal data. Information may be shared:</p>
<ul>
<li>With third-party service providers (Firebase, OpenAI, Prokerala) under confidentiality agreements, solely to provide app functionality.</li>
<li>To comply with legal requirements or respond to lawful requests by public authorities.</li>
</ul>

<h2>4. AI-Generated Content</h2>
<p>All tarot readings and astrology insights are generated by artificial intelligence (OpenAI GPT-4o) and are for <strong>informational and entertainment purposes only</strong>. They should not replace professional advice.</p>

<h2>5. Data Storage & Security</h2>
<p>Your data is stored securely on Amazon Web Services (AWS) infrastructure in the Mumbai (ap-south-1) region. We implement appropriate technical and organisational measures to protect your information, including encrypted connections (HTTPS), secure database access, and Firebase Authentication.</p>

<h2>6. Data Retention & Deletion</h2>
<p>Your data is retained as long as your account is active. You may request deletion of your account and all associated data by contacting <a href="mailto:{SUPPORT_EMAIL}">{SUPPORT_EMAIL}</a>. Deletion requests will be processed within a reasonable timeframe (typically 30 days).</p>

<h2>7. Location Data</h2>
<p>We do not track your precise GPS location. City of birth is provided voluntarily by you and is used solely for birth chart calculations.</p>

<h2>8. Age Restriction</h2>
<p>This application is not intended for users under the age of 18. If you are under 18, you must have parental or guardian consent to use this app.</p>

<h2>9. Third-Party Services</h2>
<p>We use the following third-party services, each governed by their own privacy policies:</p>
<ul>
<li>Firebase (Google) — Authentication, push notifications, crash reporting</li>
<li>OpenAI — AI reading generation</li>
<li>Prokerala — Vedic astrology calculations</li>
<li>Razorpay — Payment processing</li>
</ul>

<h2>10. Your Rights</h2>
<p>Under the Digital Personal Data Protection Act, 2023 (India), you have the right to:</p>
<ul>
<li>Access your personal data.</li>
<li>Request correction of inaccurate data.</li>
<li>Request deletion of your data.</li>
<li>Opt out by uninstalling the app or avoiding optional fields.</li>
</ul>

<h2>11. Changes to This Policy</h2>
<p>We may update this Privacy Policy from time to time. Changes will be posted within the app and on this page.</p>

<h2>12. Contact Us</h2>
<p>For any questions or data requests, contact us at: <a href="mailto:{SUPPORT_EMAIL}">{SUPPORT_EMAIL}</a></p>

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
<title>Refund & Cancellation Policy — {APP_NAME}</title>{LEGAL_PAGE_STYLE}</head><body><div class="container">
<h1>Refund & Cancellation Policy</h1>
<p class="subtitle">{APP_NAME} by {COMPANY}</p>

<h2>Subscription Cancellation</h2>
<p>You may cancel your {APP_NAME} subscription at any time through the in-app settings or by contacting our support team. Your subscription will remain active until the end of the current billing period, after which it will not auto-renew.</p>

<h2>Refund Eligibility</h2>
<p>We offer refunds in the following cases:</p>
<ul>
<li><strong>Technical issues:</strong> If you experience persistent technical problems that prevent you from using the app and our support team is unable to resolve them within 7 days.</li>
<li><strong>Accidental purchase:</strong> Refund requests for accidental purchases must be submitted within 48 hours of the transaction.</li>
<li><strong>Service unavailability:</strong> If the app or its core features are unavailable for an extended period (more than 7 consecutive days).</li>
</ul>

<h2>Non-Refundable Items</h2>
<ul>
<li>Subscription periods that have already been used or partially consumed.</li>
<li>One-time purchases consumed within the app (single readings, premium card spreads).</li>
<li>Subscriptions cancelled after 48 hours of the original purchase.</li>
</ul>

<h2>How to Request a Refund</h2>
<p>To request a refund, please email us at <a href="mailto:{SUPPORT_EMAIL}">{SUPPORT_EMAIL}</a> with the following details:</p>
<ul>
<li>Your registered email address</li>
<li>Transaction ID or payment reference</li>
<li>Reason for the refund request</li>
<li>Date of the transaction</li>
</ul>

<h2>Refund Processing Time</h2>
<p>Approved refunds will be processed within 7-14 business days to the original payment method. The actual time for the refund to reflect in your account depends on your bank or payment provider.</p>

<h2>Auto-Renewal</h2>
<p>All subscriptions auto-renew unless cancelled at least 24 hours before the end of the current period. You can manage and cancel auto-renewal in your Razorpay payment account or by contacting our support team.</p>

<h2>Contact Us</h2>
<p>For any questions about refunds or cancellations, please contact: <a href="mailto:{SUPPORT_EMAIL}">{SUPPORT_EMAIL}</a></p>

<div class="footer">&copy; 2025 {COMPANY}. All rights reserved.</div>
</div></body></html>"""
