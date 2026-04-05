from __future__ import annotations

import logging
import smtplib
import time
from email.message import EmailMessage

from .settings_service import RuntimeSettings

logger = logging.getLogger(__name__)


class EmailNotifier:
    MAX_RETRIES = 3
    RETRY_DELAY_BASE = 2  # 秒

    def __init__(self, settings: RuntimeSettings) -> None:
        self.settings = settings

    @property
    def enabled(self) -> bool:
        return bool(
            self.settings.notification_email
            and self.settings.smtp_host
            and self.settings.smtp_sender
        )

    def send(self, subject: str, body: str) -> None:
        """发送邮件，带自动重试机制
        
        Args:
            subject: 邮件主题
            body: 邮件正文内容
            
        Raises:
            smtplib.SMTPException: 在所有重试都失败后抛出
        """
        if not self.enabled:
            logger.debug("Email notifier is not enabled, skipping send")
            return

        message = EmailMessage()
        message["Subject"] = subject
        message["From"] = self.settings.smtp_sender
        message["To"] = self.settings.notification_email
        message.set_content(body)

        for attempt in range(1, self.MAX_RETRIES + 1):
            try:
                smtp_client = smtplib.SMTP_SSL if self.settings.smtp_use_ssl else smtplib.SMTP
                with smtp_client(
                    self.settings.smtp_host,
                    self.settings.smtp_port,
                    timeout=15,
                ) as server:
                    if self.settings.smtp_use_tls and not self.settings.smtp_use_ssl:
                        server.starttls()
                    if self.settings.smtp_username:
                        server.login(self.settings.smtp_username, self.settings.smtp_password)
                    server.send_message(message)
                
                logger.info(
                    f"Email sent successfully: {subject} to {self.settings.notification_email}"
                )
                return
            except smtplib.SMTPAuthenticationError as e:
                logger.error(
                    f"SMTP authentication failed: {e}. Please check username/password."
                )
                raise
            except smtplib.SMTPException as e:
                if attempt < self.MAX_RETRIES:
                    wait_time = self.RETRY_DELAY_BASE ** (attempt - 1)
                    logger.warning(
                        f"Email send attempt {attempt}/{self.MAX_RETRIES} failed: {e}. "
                        f"Retrying in {wait_time}s..."
                    )
                    time.sleep(wait_time)
                else:
                    logger.error(
                        f"Email send failed after {self.MAX_RETRIES} attempts: {e}. "
                        f"Subject: {subject}"
                    )
                    raise
            except (OSError, TimeoutError) as e:
                if attempt < self.MAX_RETRIES:
                    wait_time = self.RETRY_DELAY_BASE ** (attempt - 1)
                    logger.warning(
                        f"Network error on attempt {attempt}/{self.MAX_RETRIES}: {e}. "
                        f"Retrying in {wait_time}s..."
                    )
                    time.sleep(wait_time)
                else:
                    logger.error(
                        f"Email send failed after {self.MAX_RETRIES} attempts due to network error: {e}"
                    )
                    raise
