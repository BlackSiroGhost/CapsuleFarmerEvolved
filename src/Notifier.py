import smtplib
from email.mime.text import MIMEText
from time import time


class Notifier:
    """
    Sends email notifications for bot events.
    Rate-limits to avoid spamming (max 1 email per event type per cooldown period).
    """

    COOLDOWN = 3600  # 1 hour between duplicate notifications

    def __init__(self, log, config):
        self.log = log
        self.enabled = bool(config.get("smtpServer"))
        if not self.enabled:
            return
        self.smtp_server = config["smtpServer"]
        self.smtp_port = config.get("smtpPort", 587)
        self.smtp_user = config["smtpUser"]
        self.smtp_password = config["smtpPassword"]
        self.recipient = config["notifyEmail"]
        self._last_sent = {}  # event_key -> timestamp

    def notify(self, subject, body, event_key=None):
        """
        Send an email notification.

        :param subject: email subject
        :param body: email body text
        :param event_key: dedup key for rate limiting (e.g. "login_failed_Account1")
        """
        if not self.enabled:
            return
        if event_key:
            last = self._last_sent.get(event_key, 0)
            if time() - last < self.COOLDOWN:
                self.log.debug(f"Notification suppressed (cooldown): {event_key}")
                return
        try:
            msg = MIMEText(body)
            msg["Subject"] = f"[CapsuleFarmer] {subject}"
            msg["From"] = self.smtp_user
            msg["To"] = self.recipient

            with smtplib.SMTP(self.smtp_server, self.smtp_port) as server:
                server.starttls()
                server.login(self.smtp_user, self.smtp_password)
                server.send_message(msg)

            if event_key:
                self._last_sent[event_key] = time()
            self.log.info(f"Notification sent: {subject}")
        except Exception as e:
            self.log.error(f"Failed to send notification: {e}")
