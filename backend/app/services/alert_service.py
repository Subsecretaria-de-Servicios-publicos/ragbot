"""
app/services/alert_service.py — Avisos cuando el bot falla (mail SMTP y/o webhook).
"""
import asyncio
import smtplib
import time
from email.message import EmailMessage

import httpx
import structlog

from app.core.config import settings

logger = structlog.get_logger()

# (bot_id, tipo de error) -> timestamp del último aviso. Es por proceso (worker).
_last_sent: dict[tuple[str, str], float] = {}


def _send_email(subject: str, body: str) -> None:
    recipients = [r.strip() for r in settings.ALERT_EMAIL_TO.split(",") if r.strip()]
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = settings.SMTP_FROM or settings.SMTP_USER
    msg["To"] = ", ".join(recipients)
    msg.set_content(body)

    if settings.SMTP_PORT == 465:
        server = smtplib.SMTP_SSL(settings.SMTP_HOST, settings.SMTP_PORT, timeout=15)
    else:
        server = smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=15)
    with server:
        if settings.SMTP_PORT != 465 and settings.SMTP_USE_TLS:
            server.starttls()
        if settings.SMTP_USER:
            server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
        server.send_message(msg)


async def notify_bot_failure(bot_id: str, error: Exception) -> None:
    """Best-effort: nunca propaga excepciones, para no afectar la respuesta al usuario."""
    try:
        email_on = bool(settings.ALERT_EMAIL_TO and settings.SMTP_HOST)
        webhook_on = bool(settings.ALERT_WEBHOOK_URL)
        if not (email_on or webhook_on):
            return

        key = (bot_id, type(error).__name__)
        now = time.monotonic()
        if now - _last_sent.get(key, float("-inf")) < settings.ALERT_COOLDOWN_SECONDS:
            return
        _last_sent[key] = now

        subject = f"[{settings.APP_NAME}] Falla en el bot {bot_id}"
        body = f"El chatbot {bot_id} devolvió un error interno.\n\nTipo: {type(error).__name__}\nDetalle: {error}"

        if email_on:
            try:
                await asyncio.to_thread(_send_email, subject, body)
            except Exception as e:
                logger.error("alert_email_failed", error=str(e))
        if webhook_on:
            try:
                async with httpx.AsyncClient(timeout=10) as client:
                    # "text" lo entienden Slack/Mattermost; "content" Discord
                    await client.post(
                        settings.ALERT_WEBHOOK_URL,
                        json={"text": f"{subject}\n{body}", "content": f"{subject}\n{body}"},
                    )
            except Exception as e:
                logger.error("alert_webhook_failed", error=str(e))
    except Exception as e:
        logger.error("alert_failed", error=str(e))
