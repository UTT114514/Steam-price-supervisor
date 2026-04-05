from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from decimal import Decimal

from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from .config import Settings
from .database import build_engine, build_session_factory, get_db, init_db
from .logging_config import setup_logging
from .models import AlertEvent, GameCanonical, PriceSnapshot, WatchItem
from .providers.steam import SteamProvider
from .providers.xiaoheihe import XiaoHeiHeProvider
from .scheduler import SchedulerManager
from .schemas import (
    AlertResponse,
    DecisionResponse,
    GameDetailResponse,
    PricePoint,
    RefreshRequest,
    SettingsPayload,
    WatchItemCreate,
    WatchItemResponse,
)
from .services.alerts import AlertService
from .services.decision import DecisionService
from .services.notifications import EmailNotifier
from .services.refresh import RefreshService, RefreshUnavailableError
from .services.settings_service import SettingsService

logger = logging.getLogger(__name__)


def create_app(
    settings: Settings | None = None,
    providers=None,
    scheduler_enabled: bool | None = None,
) -> FastAPI:
    # 初始化日志系统
    setup_logging()
    logger.info("Initializing Steam Price Monitor application")
    
    app_settings = settings or Settings.from_env()
    logger.debug(f"Configuration loaded: {app_settings.app_name}")
    
    engine = build_engine(app_settings.database_url)
    session_factory = build_session_factory(engine)
    init_db(engine)
    logger.debug(f"Database initialized: {app_settings.database_url}")

    provider_instances = providers or [SteamProvider(app_settings), XiaoHeiHeProvider(app_settings)]
    decision_service = DecisionService()
    settings_service = SettingsService(app_settings)
    alert_service = AlertService(app_settings)
    refresh_service = RefreshService(provider_instances, decision_service, alert_service)

    def notifier_builder(session: Session) -> EmailNotifier:
        runtime = settings_service.load_runtime(session)
        return EmailNotifier(runtime)

    scheduler = SchedulerManager(
        session_factory=session_factory,
        refresh_service=refresh_service,
        settings_service=settings_service,
        notifier_builder=notifier_builder,
        timezone_name=app_settings.timezone,
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        with session_factory() as session:
            settings_service.ensure_defaults(session)
        should_start = (
            app_settings.scheduler_enabled
            if scheduler_enabled is None
            else scheduler_enabled
        )
        if should_start:
            scheduler.start()
        try:
            yield
        finally:
            scheduler.stop()

    app = FastAPI(title=app_settings.app_name, lifespan=lifespan)
    app.mount("/static", StaticFiles(directory=app_settings.static_dir), name="static")
    templates = Jinja2Templates(directory=str(app_settings.templates_dir))

    app.state.settings = app_settings
    app.state.session_factory = session_factory
    app.state.decision_service = decision_service
    app.state.refresh_service = refresh_service
    app.state.settings_service = settings_service
    app.state.notifier_builder = notifier_builder
    app.state.scheduler_manager = scheduler
    app.state.templates = templates

    def sync_runtime_provider_settings(payload: SettingsPayload) -> None:
        app.state.settings.xiaoheihe_enabled = payload.xiaoheihe_enabled
        for provider in provider_instances:
            provider_settings = getattr(provider, "settings", None)
            if provider_settings is not None and hasattr(provider_settings, "xiaoheihe_enabled"):
                provider_settings.xiaoheihe_enabled = payload.xiaoheihe_enabled

    def best_current_snapshot(session: Session, steam_appid: int) -> PriceSnapshot | None:
        snapshots = session.scalars(
            select(PriceSnapshot)
            .where(PriceSnapshot.steam_appid == steam_appid)
            .order_by(PriceSnapshot.observed_at.desc())
        ).all()
        latest_per_source: dict[str, PriceSnapshot] = {}
        for snapshot in snapshots:
            latest_per_source.setdefault(snapshot.source_name, snapshot)
        return min(
            (
                snapshot
                for snapshot in latest_per_source.values()
                if snapshot.current_price is not None
            ),
            key=lambda snapshot: snapshot.current_price,
            default=None,
        )

    def build_watch_item_response(
        session: Session, watch_item: WatchItem
    ) -> WatchItemResponse:
        current_snapshot = best_current_snapshot(session, watch_item.steam_appid)
        return WatchItemResponse(
            id=watch_item.id,
            steam_appid=watch_item.steam_appid,
            title=watch_item.game.title,
            edition_label=watch_item.game.edition_label,
            value_score=watch_item.game.value_score,
            target_price=watch_item.target_price,
            priority=watch_item.priority,
            enabled=watch_item.enabled,
            current_price=current_snapshot.current_price if current_snapshot else None,
            currency=current_snapshot.currency if current_snapshot else None,
            current_discount_percent=current_snapshot.discount_percent if current_snapshot else None,
            last_decision_status=watch_item.last_decision_status,
            last_decision_reason=watch_item.last_decision_reason,
            last_checked_at=watch_item.last_checked_at,
        )

    def build_game_detail(session: Session, steam_appid: int) -> GameDetailResponse:
        game = session.get(GameCanonical, steam_appid)
        if game is None:
            raise HTTPException(status_code=404, detail="Game not found")
        watch_item = session.scalars(
            select(WatchItem).where(WatchItem.steam_appid == steam_appid)
        ).first()
        try:
            decision = decision_service.evaluate(session, steam_appid, watch_item)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        history = [
            PricePoint(
                observed_at=snapshot.observed_at,
                current_price=snapshot.current_price,
                source_name=snapshot.source_name,
                discount_percent=snapshot.discount_percent,
            )
            for snapshot in session.scalars(
                select(PriceSnapshot)
                .where(PriceSnapshot.steam_appid == steam_appid)
                .order_by(PriceSnapshot.observed_at.asc())
            ).all()
        ]
        alerts = [
            AlertResponse.model_validate(alert)
            for alert in session.scalars(
                select(AlertEvent)
                .where(AlertEvent.steam_appid == steam_appid)
                .order_by(AlertEvent.triggered_at.desc())
            ).all()
        ]
        return GameDetailResponse(
            steam_appid=game.steam_appid,
            title=game.title,
            edition_label=game.edition_label,
            base_game_appid=game.base_game_appid,
            capsule_url=game.capsule_url,
            publisher=game.publisher,
            developer=game.developer,
            decision=decision,
            price_history=history,
            alerts=alerts,
        )

    def price_points_for_chart(points: list[PricePoint]) -> str:
        valid_points = [point for point in points if point.current_price is not None]
        if not valid_points:
            return ""
        values = [float(point.current_price) for point in valid_points]
        min_value = min(values)
        max_value = max(values)
        spread = max(max_value - min_value, 1.0)
        coords = []
        total = max(len(valid_points) - 1, 1)
        for index, point in enumerate(valid_points):
            x = 20 + (index / total) * 360
            y = 180 - ((float(point.current_price) - min_value) / spread) * 140
            coords.append(f"{x:.1f},{y:.1f}")
        return " ".join(coords)

    @app.get("/health")
    def health_check(db: Session = Depends(get_db)) -> dict:
        """健康检查接口，用于监控和负载均衡器"""
        try:
            # 测试数据库连接
            db.execute(select(1))
            db_status = "ok"
        except Exception as e:
            logger.error(f"Database health check failed: {e}")
            db_status = f"error: {str(e)}"
        
        scheduler_running = app.state.scheduler_manager.scheduler.running
        
        return {
            "status": "healthy" if db_status == "ok" else "degraded",
            "database": db_status,
            "scheduler": "running" if scheduler_running else "stopped",
        }

    @app.get("/", response_class=HTMLResponse)
    def root() -> RedirectResponse:
        return RedirectResponse(url="/watch-items/dashboard", status_code=302)

    @app.post("/watch-items", response_model=WatchItemResponse)
    def create_watch_item(
        payload: WatchItemCreate, db: Session = Depends(get_db)
    ) -> WatchItemResponse:
        try:
            watch_item = refresh_service.ensure_watch_item(
                db,
                payload,
                app.state.notifier_builder(db),
            )
        except RefreshUnavailableError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return build_watch_item_response(db, watch_item)

    @app.get("/watch-items", response_model=list[WatchItemResponse])
    def list_watch_items(db: Session = Depends(get_db)) -> list[WatchItemResponse]:
        # 使用 eager loading 避免 N+1 查询
        watch_items = db.scalars(
            select(WatchItem)
            .options(selectinload(WatchItem.game))
            .order_by(WatchItem.priority.asc())
        ).all()
        return [build_watch_item_response(db, item) for item in watch_items]

    @app.get("/games/{steam_appid}", response_model=GameDetailResponse)
    def game_detail(steam_appid: int, db: Session = Depends(get_db)) -> GameDetailResponse:
        return build_game_detail(db, steam_appid)

    @app.get("/decision/{steam_appid}", response_model=DecisionResponse)
    def decision(steam_appid: int, db: Session = Depends(get_db)) -> DecisionResponse:
        watch_item = db.scalars(
            select(WatchItem).where(WatchItem.steam_appid == steam_appid)
        ).first()
        try:
            return decision_service.evaluate(db, steam_appid, watch_item)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/jobs/refresh")
    def refresh_job(payload: RefreshRequest, db: Session = Depends(get_db)) -> dict:
        notifier = app.state.notifier_builder(db)
        if payload.steam_appid is not None:
            watch_item = db.scalars(
                select(WatchItem).where(WatchItem.steam_appid == payload.steam_appid)
            ).first()
            if watch_item is None:
                raise HTTPException(status_code=404, detail="Watch item not found")
            try:
                decision_result = refresh_service.refresh_watch_item(db, watch_item, notifier)
            except RefreshUnavailableError as exc:
                raise HTTPException(status_code=503, detail=str(exc)) from exc
            except ValueError as exc:
                raise HTTPException(status_code=404, detail=str(exc)) from exc
            db.commit()
            return {
                "watch_item_id": watch_item.id,
                "steam_appid": watch_item.steam_appid,
                "status": decision_result.status,
            }
        return {"results": refresh_service.refresh_all(db, notifier)}

    @app.get("/alerts", response_model=list[AlertResponse])
    def list_alerts(db: Session = Depends(get_db)) -> list[AlertResponse]:
        alerts = db.scalars(select(AlertEvent).order_by(AlertEvent.triggered_at.desc())).all()
        return [AlertResponse.model_validate(alert) for alert in alerts]

    @app.post("/alerts/{alert_id}/retry", response_model=AlertResponse)
    def retry_alert(alert_id: int, db: Session = Depends(get_db)) -> AlertResponse:
        try:
            event = alert_service.retry_failed(
                db,
                alert_id,
                app.state.notifier_builder(db),
            )
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return AlertResponse.model_validate(event)

    @app.get("/watch-items/dashboard", response_class=HTMLResponse)
    def watch_dashboard(request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
        watch_items = list_watch_items(db)
        return templates.TemplateResponse(
            request,
            "dashboard.html",
            {
                "request": request,
                "watch_items": watch_items,
            },
        )

    @app.post("/watch-items/form")
    def create_watch_item_form(
        steam_appid: int = Form(...),
        target_price: str = Form(""),
        priority: int = Form(5),
        enabled: bool = Form(True),
        title: str = Form(""),
        edition_label: str = Form("Standard"),
        value_score: str = Form("1.00"),
        base_game_appid: str = Form(""),
        include_downloadable_content: bool = Form(False),
        db: Session = Depends(get_db),
    ) -> RedirectResponse:
        payload = WatchItemCreate(
            steam_appid=steam_appid,
            target_price=Decimal(target_price) if target_price else None,
            priority=priority,
            enabled=enabled,
            title=title or None,
            edition_label=edition_label,
            value_score=Decimal(value_score),
            base_game_appid=int(base_game_appid) if base_game_appid else None,
            include_downloadable_content=include_downloadable_content,
        )
        create_watch_item(payload, db)
        return RedirectResponse(url="/watch-items/dashboard", status_code=303)

    @app.get("/games/{steam_appid}/page", response_class=HTMLResponse)
    def game_detail_page(
        steam_appid: int, request: Request, db: Session = Depends(get_db)
    ) -> HTMLResponse:
        detail = build_game_detail(db, steam_appid)
        return templates.TemplateResponse(
            request,
            "game_detail.html",
            {
                "request": request,
                "game": detail,
                "chart_points": price_points_for_chart(detail.price_history),
            },
        )

    @app.get("/alerts/page", response_class=HTMLResponse)
    def alerts_page(request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
        alerts = list_alerts(db)
        return templates.TemplateResponse(
            request,
            "alerts.html",
            {"request": request, "alerts": alerts},
        )

    @app.get("/settings", response_class=HTMLResponse)
    def settings_page(request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
        runtime = settings_service.load_runtime(db)
        return templates.TemplateResponse(
            request,
            "settings.html",
            {"request": request, "settings": runtime},
        )

    @app.post("/settings")
    def update_settings(
        refresh_interval_minutes: int = Form(...),
        full_sync_hour: int = Form(...),
        notification_email: str = Form(""),
        smtp_host: str = Form(""),
        smtp_port: int = Form(587),
        smtp_username: str = Form(""),
        smtp_password: str = Form(""),
        smtp_sender: str = Form(""),
        smtp_use_tls: bool = Form(False),
        smtp_use_ssl: bool = Form(False),
        xiaoheihe_enabled: bool = Form(False),
        db: Session = Depends(get_db),
    ) -> RedirectResponse:
        payload = SettingsPayload(
            refresh_interval_minutes=refresh_interval_minutes,
            full_sync_hour=full_sync_hour,
            notification_email=notification_email,
            smtp_host=smtp_host,
            smtp_port=smtp_port,
            smtp_username=smtp_username,
            smtp_password=smtp_password,
            smtp_sender=smtp_sender,
            smtp_use_tls=smtp_use_tls,
            smtp_use_ssl=smtp_use_ssl,
            xiaoheihe_enabled=xiaoheihe_enabled,
        )
        settings_service.set_many(
            db,
            {
                "refresh_interval_minutes": str(payload.refresh_interval_minutes),
                "full_sync_hour": str(payload.full_sync_hour),
                "notification_email": payload.notification_email,
                "smtp_host": payload.smtp_host,
                "smtp_port": str(payload.smtp_port),
                "smtp_username": payload.smtp_username,
                "smtp_password": payload.smtp_password,
                "smtp_sender": payload.smtp_sender,
                "smtp_use_tls": "true" if payload.smtp_use_tls else "false",
                "smtp_use_ssl": "true" if payload.smtp_use_ssl else "false",
                "xiaoheihe_enabled": "true" if payload.xiaoheihe_enabled else "false",
            },
        )
        sync_runtime_provider_settings(payload)
        app.state.scheduler_manager.reload()
        return RedirectResponse(url="/settings", status_code=303)

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("steam_price_monitor.main:app", host="127.0.0.1", port=8000, reload=True)
