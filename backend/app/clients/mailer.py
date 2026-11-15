from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage

from ..config import Settings

log = logging.getLogger("cinelog.mail")


class Mailer:
    """Sends through SMTP when configured; otherwise reports 'logged' (the Outbox table is the dev mailbox)."""

    def __init__(self, settings: Settings) -> None:
        self.s = settings

    def send(self, to: str, subject: str, body: str) -> str:
        if not self.s.smtp_host:
            log.info("[mail:dev] to=%s subject=%s", to, subject)
            return "logged"
        msg = EmailMessage()
        msg["From"], msg["To"], msg["Subject"] = self.s.smtp_from, to, subject
        msg.set_content(body)
        with smtplib.SMTP(self.s.smtp_host, self.s.smtp_port, timeout=15) as smtp:
            smtp.starttls()
            if self.s.smtp_user:
                smtp.login(self.s.smtp_user, self.s.smtp_password)
            smtp.send_message(msg)
        return "sent"
