"""Уведомления администраторам: лента в панели (+ будущий SMTP-канал)."""
import logging

log = logging.getLogger(__name__)


def notify_admin(db, message: str, kind: str = "info") -> None:
    from app.models import Notification
    db.add(Notification(kind=kind, message=message))
    db.flush()
    # Будущий канал: свой почтовый сервер. Раскомментируй, когда настроишь SMTP:
    # _send_email(message)


def _send_email(message: str) -> None:  # pragma: no cover
    try:
        from app.core.config import settings
        if not getattr(settings, "SMTP_HOST", ""):
            return
        import smtplib
        from email.mime.text import MIMEText
        msg = MIMEText(message)
        msg["Subject"] = "[ITKAM34] уведомление"
        msg["From"] = getattr(settings, "SMTP_FROM", "billing@itkam34.ru")
        msg["To"] = getattr(settings, "ADMIN_EMAIL", "admin@itkam34.ru")
        with smtplib.SMTP(settings.SMTP_HOST, int(getattr(settings, "SMTP_PORT", 587))) as srv:
            if getattr(settings, "SMTP_USE_TLS", True):
                srv.starttls()
            if getattr(settings, "SMTP_USER", ""):
                srv.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
            srv.send_message(msg)
    except Exception as e:
        log.error("smtp notify failed: %s", e)
