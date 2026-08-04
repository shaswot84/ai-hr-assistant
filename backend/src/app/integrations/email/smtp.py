from __future__ import annotations

import smtplib
from email.message import EmailMessage

from app.config.settings import get_settings
from app.integrations.email import EmailProvider


class SmtpEmailProvider(EmailProvider):
    """SMTP delivery — points at Mailpit (localhost:1025) in dev, SMTP/SES in prod."""

    def __init__(self) -> None:
        self._settings = get_settings()

    def send(
        self,
        *,
        to_email: str,
        subject: str,
        body: str,
        html: str | None = None,
    ) -> None:
        message = EmailMessage()
        message["From"] = self._settings.email_from
        message["To"] = to_email
        message["Subject"] = subject
        message.set_content(body)
        if html:
            message.add_alternative(html, subtype="html")

        with smtplib.SMTP(self._settings.smtp_host, self._settings.smtp_port, timeout=15) as smtp:
            if self._settings.smtp_user:
                smtp.login(self._settings.smtp_user, self._settings.smtp_password)
            smtp.send_message(message)
