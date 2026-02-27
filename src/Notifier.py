import smtplib
import requests
from email.mime.text import MIMEText
from time import time


class Notifier:
    """
    Sends notifications for bot events via email (SMTP) or ntfy.sh (push).
    Rate-limits to avoid spamming (max 1 per event type per cooldown period).
    """

    COOLDOWN = 3600  # 1 hour between duplicate notifications

    def __init__(self, log, config):
        self.log = log
        self._last_sent = {}

        # SMTP email
        self.smtp_enabled = bool(config.get("smtpServer"))
        if self.smtp_enabled:
            self.smtp_server = config["smtpServer"]
            self.smtp_port = config.get("smtpPort", 587)
            self.smtp_user = config["smtpUser"]
            self.smtp_password = config["smtpPassword"]
            self.recipient = config["notifyEmail"]

        # ntfy.sh push notifications (works even when SMTP ports are blocked)
        self.ntfy_topic = config.get("ntfyTopic", "")
        self.ntfy_enabled = bool(self.ntfy_topic)

        self.enabled = self.smtp_enabled or self.ntfy_enabled

    def notify(self, subject, body, event_key=None):
        """
        Send a notification via all configured channels.

        :param subject: notification title
        :param body: notification body text
        :param event_key: dedup key for rate limiting
        """
        if not self.enabled:
            return
        if event_key:
            last = self._last_sent.get(event_key, 0)
            if time() - last < self.COOLDOWN:
                self.log.debug(f"Notification suppressed (cooldown): {event_key}")
                return

        sent = False

        if self.smtp_enabled:
            try:
                msg = MIMEText(body)
                msg["Subject"] = f"[CapsuleFarmer] {subject}"
                msg["From"] = self.smtp_user
                msg["To"] = self.recipient

                with smtplib.SMTP(self.smtp_server, self.smtp_port, timeout=10) as server:
                    server.starttls()
                    server.login(self.smtp_user, self.smtp_password)
                    server.send_message(msg)
                sent = True
                self.log.info(f"Email sent: {subject}")
            except Exception as e:
                self.log.warning(f"Email failed: {e}")

        if self.ntfy_enabled:
            try:
                requests.post(
                    f"https://ntfy.sh/{self.ntfy_topic}",
                    data=body.encode("utf-8"),
                    headers={"Title": subject, "Priority": "high"},
                    timeout=10)
                sent = True
                self.log.info(f"Push notification sent: {subject}")
            except Exception as e:
                self.log.warning(f"Push notification failed: {e}")

        if sent and event_key:
            self._last_sent[event_key] = time()
