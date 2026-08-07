from __future__ import annotations

from abc import ABC, abstractmethod


class EmailProvider(ABC):
    """Swappable email delivery seam. Dev = Mailpit (SMTP :1025), prod = SMTP/SES."""

    @abstractmethod
    def send(
        self,
        *,
        to_email: str,
        subject: str,
        body: str,
        html: str | None = None,
    ) -> None:
        """Deliver one email. Raises on failure so the job can retry."""
