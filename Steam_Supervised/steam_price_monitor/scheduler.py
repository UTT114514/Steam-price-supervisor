from __future__ import annotations

from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy.orm import Session, sessionmaker

from .services.refresh import RefreshService
from .services.settings_service import SettingsService


class SchedulerManager:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        refresh_service: RefreshService,
        settings_service: SettingsService,
        notifier_builder,
        timezone_name: str,
    ) -> None:
        self.session_factory = session_factory
        self.refresh_service = refresh_service
        self.settings_service = settings_service
        self.notifier_builder = notifier_builder
        self.scheduler = BackgroundScheduler(timezone=timezone_name)

    def start(self) -> None:
        if self.scheduler.running:
            return
        self.reload()
        self.scheduler.start()

    def stop(self) -> None:
        if self.scheduler.running:
            self.scheduler.shutdown(wait=False)

    def reload(self) -> None:
        with self.session_factory() as session:
            runtime = self.settings_service.load_runtime(session)
        self.scheduler.remove_all_jobs()
        self.scheduler.add_job(
            self._refresh_all_job,
            "interval",
            minutes=runtime.refresh_interval_minutes,
            id="refresh_watch_items",
            replace_existing=True,
        )
        self.scheduler.add_job(
            self._refresh_all_job,
            "cron",
            hour=runtime.full_sync_hour,
            id="full_sync_watch_items",
            replace_existing=True,
        )

    def _refresh_all_job(self) -> None:
        with self.session_factory() as session:
            notifier = self.notifier_builder(session)
            self.refresh_service.refresh_all(session, notifier)
