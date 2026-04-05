from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from ..config import Settings
from ..models import AppSetting


DEFAULT_SETTING_VALUES = {
    "refresh_interval_minutes": "180",
    "full_sync_hour": "6",
    "notification_email": "",
    "smtp_host": "",
    "smtp_port": "587",
    "smtp_username": "",
    "smtp_password": "",
    "smtp_sender": "",
    "smtp_use_tls": "true",
    "smtp_use_ssl": "false",
    "xiaoheihe_enabled": "false",
}


def _as_bool(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(slots=True)
class RuntimeSettings:
    refresh_interval_minutes: int
    full_sync_hour: int
    notification_email: str
    smtp_host: str
    smtp_port: int
    smtp_username: str
    smtp_password: str
    smtp_sender: str
    smtp_use_tls: bool
    smtp_use_ssl: bool
    xiaoheihe_enabled: bool


class SettingsService:
    def __init__(self, app_settings: Settings) -> None:
        self.app_settings = app_settings

    def ensure_defaults(self, session: Session) -> None:
        changed = False
        for key, default_value in DEFAULT_SETTING_VALUES.items():
            if session.get(AppSetting, key) is None:
                session.add(AppSetting(key=key, value=default_value))
                changed = True
        if changed:
            session.commit()

    def get(self, session: Session, key: str) -> str:
        record = session.get(AppSetting, key)
        if record is not None:
            return record.value
        if key in DEFAULT_SETTING_VALUES:
            return DEFAULT_SETTING_VALUES[key]
        return ""

    def set_many(self, session: Session, values: dict[str, str]) -> None:
        for key, value in values.items():
            record = session.get(AppSetting, key)
            if record is None:
                session.add(AppSetting(key=key, value=value))
            else:
                record.value = value
        session.commit()

    def load_runtime(self, session: Session) -> RuntimeSettings:
        self.ensure_defaults(session)
        return RuntimeSettings(
            refresh_interval_minutes=int(
                self.get(session, "refresh_interval_minutes")
                or self.app_settings.refresh_interval_minutes
            ),
            full_sync_hour=int(
                self.get(session, "full_sync_hour") or self.app_settings.full_sync_hour
            ),
            notification_email=self.get(session, "notification_email")
            or self.app_settings.notification_email,
            smtp_host=self.get(session, "smtp_host") or self.app_settings.smtp_host,
            smtp_port=int(self.get(session, "smtp_port") or self.app_settings.smtp_port),
            smtp_username=self.get(session, "smtp_username")
            or self.app_settings.smtp_username,
            smtp_password=self.get(session, "smtp_password")
            or self.app_settings.smtp_password,
            smtp_sender=self.get(session, "smtp_sender") or self.app_settings.smtp_sender,
            smtp_use_tls=_as_bool(self.get(session, "smtp_use_tls"))
            if self.get(session, "smtp_use_tls")
            else self.app_settings.smtp_use_tls,
            smtp_use_ssl=_as_bool(self.get(session, "smtp_use_ssl"))
            if self.get(session, "smtp_use_ssl")
            else self.app_settings.smtp_use_ssl,
            xiaoheihe_enabled=_as_bool(self.get(session, "xiaoheihe_enabled"))
            if self.get(session, "xiaoheihe_enabled")
            else self.app_settings.xiaoheihe_enabled,
        )
