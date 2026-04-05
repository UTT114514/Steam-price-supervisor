from __future__ import annotations

from fastapi.testclient import TestClient

from steam_price_monitor.config import Settings
from steam_price_monitor.main import create_app
from steam_price_monitor.services.notifications import EmailNotifier
from steam_price_monitor.services.settings_service import RuntimeSettings

from .conftest import (
    FakeNotifier,
    FakeProvider,
    NullSupplementalProvider,
    ToggleableSupplementalProvider,
    build_data,
)


def test_create_watch_item_triggers_initial_refresh(client, provider: FakeProvider):
    provider.queue(
        730,
        build_data(
            730,
            title="Counter-Strike",
            current_price="39.00",
            original_price="59.00",
            discount_percent=34,
        ),
    )

    response = client.post(
        "/watch-items",
        json={"steam_appid": 730, "target_price": 40, "priority": 3},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["steam_appid"] == 730
    assert body["current_price"] == "39.00"
    assert body["last_decision_status"] == "Buy"


def test_missing_supplemental_source_still_returns_decision(client, provider: FakeProvider):
    provider.queue(
        570,
        build_data(
            570,
            title="Dota 2 Companion",
            current_price="25.00",
            original_price="50.00",
            discount_percent=50,
        ),
    )
    client.post("/watch-items", json={"steam_appid": 570, "target_price": 20})

    decision = client.get("/decision/570")

    assert decision.status_code == 200
    assert decision.json()["status"] in {"Buy", "Wait"}


def test_target_price_alert_is_deduplicated(client, provider: FakeProvider):
    provider.queue(
        999,
        build_data(
            999,
            title="Price Alert Test",
            current_price="30.00",
            original_price="60.00",
            discount_percent=50,
        ),
        build_data(
            999,
            title="Price Alert Test",
            current_price="30.00",
            original_price="60.00",
            discount_percent=50,
        ),
    )

    client.post("/watch-items", json={"steam_appid": 999, "target_price": 35})
    client.post("/jobs/refresh", json={"steam_appid": 999})

    alerts = client.get("/alerts").json()
    target_alerts = [alert for alert in alerts if alert["alert_type"] == "target_price_reached"]
    assert len(target_alerts) == 1


def test_decision_transitions_from_wait_to_buy(client, provider: FakeProvider):
    provider.queue(
        1000,
        build_data(
            1000,
            title="Wait Then Buy",
            current_price="60.00",
            original_price="100.00",
            discount_percent=40,
        ),
        build_data(
            1000,
            title="Wait Then Buy",
            current_price="45.00",
            original_price="100.00",
            discount_percent=55,
        ),
    )

    first = client.post("/watch-items", json={"steam_appid": 1000, "target_price": 45})
    assert first.json()["last_decision_status"] == "Wait"

    second = client.post("/jobs/refresh", json={"steam_appid": 1000})
    assert second.status_code == 200

    decision = client.get("/decision/1000").json()
    assert decision["status"] == "Buy"


def test_recommended_purchase_selects_best_variant(client, provider: FakeProvider):
    provider.queue(
        2000,
        build_data(
            2000,
            title="Base Edition",
            current_price="60.00",
            original_price="80.00",
            discount_percent=25,
            edition_label="Standard",
            value_score="1.00",
        ),
    )
    provider.queue(
        2001,
        build_data(
            2001,
            title="Deluxe Edition",
            current_price="72.00",
            original_price="120.00",
            discount_percent=40,
            edition_label="Deluxe",
            base_game_appid=2000,
            value_score="1.30",
        ),
    )

    client.post(
        "/watch-items",
        json={
            "steam_appid": 2000,
            "title": "Base Edition",
            "target_price": 65,
            "value_score": "1.00",
        },
    )
    client.post(
        "/watch-items",
        json={
            "steam_appid": 2001,
            "title": "Deluxe Edition",
            "base_game_appid": 2000,
            "edition_label": "Deluxe",
            "value_score": "1.30",
            "target_price": 80,
        },
    )

    decision = client.get("/decision/2000").json()
    assert decision["recommended_purchase_appid"] == 2001
    assert decision["recommended_purchase_title"] == "Deluxe Edition"


def test_email_failure_is_recorded_and_retry_is_possible(tmp_path):
    provider = FakeProvider()
    notifier = FakeNotifier(should_fail=True)
    provider.queue(
        3000,
        build_data(
            3000,
            title="Retry Mail Test",
            current_price="19.00",
            original_price="59.00",
            discount_percent=67,
        ),
    )
    app = create_app(
        settings=Settings(
            database_url=f"sqlite:///{(tmp_path / 'retry.db').as_posix()}",
            scheduler_enabled=False,
        ),
        providers=[provider, NullSupplementalProvider()],
        scheduler_enabled=False,
    )
    app.state.notifier_builder = lambda session: notifier

    with TestClient(app) as client:
        client.post("/watch-items", json={"steam_appid": 3000, "target_price": 20})
        alerts = client.get("/alerts").json()
        assert alerts[0]["status"] == "failed"

        notifier.should_fail = False
        retry = client.post(f"/alerts/{alerts[0]['id']}/retry")
        assert retry.status_code == 200
        assert retry.json()["status"] == "sent"


def test_restart_keeps_watch_items_and_history(tmp_path):
    provider = FakeProvider()
    provider.queue(
        4000,
        build_data(
            4000,
            title="Persistence Test",
            current_price="29.00",
            original_price="49.00",
            discount_percent=41,
        ),
    )
    db_path = tmp_path / "persist.db"
    settings = Settings(
        database_url=f"sqlite:///{db_path.as_posix()}",
        scheduler_enabled=False,
    )

    app1 = create_app(
        settings=settings,
        providers=[provider, NullSupplementalProvider()],
        scheduler_enabled=False,
    )
    app1.state.notifier_builder = lambda session: FakeNotifier(enabled=False)
    with TestClient(app1) as client:
        client.post("/watch-items", json={"steam_appid": 4000, "target_price": 30})

    app2 = create_app(
        settings=settings,
        providers=[NullSupplementalProvider()],
        scheduler_enabled=False,
    )
    app2.state.notifier_builder = lambda session: FakeNotifier(enabled=False)
    with TestClient(app2) as client:
        watch_items = client.get("/watch-items").json()
        assert len(watch_items) == 1
        assert watch_items[0]["steam_appid"] == 4000
        detail = client.get("/games/4000").json()
        assert len(detail["price_history"]) == 1


def test_refresh_failure_does_not_look_like_a_success(client, provider: FakeProvider):
    provider.queue(
        5000,
        build_data(
            5000,
            title="Flaky Network",
            current_price="28.00",
            original_price="68.00",
            discount_percent=59,
        ),
        RuntimeError("steam temporarily unavailable"),
    )

    created = client.post("/watch-items", json={"steam_appid": 5000, "target_price": 30}).json()
    before_checked = created["last_checked_at"]

    refresh = client.post("/jobs/refresh", json={"steam_appid": 5000})
    assert refresh.status_code == 503

    after = client.get("/watch-items").json()[0]
    assert after["last_checked_at"] == before_checked


def test_missing_resources_return_404(client):
    assert client.get("/decision/999999").status_code == 404
    assert client.post("/alerts/999999/retry").status_code == 404


def test_settings_toggle_updates_runtime_provider_usage(tmp_path):
    provider = FakeProvider()
    settings = Settings(
        database_url=f"sqlite:///{(tmp_path / 'runtime.db').as_posix()}",
        scheduler_enabled=False,
        xiaoheihe_enabled=False,
        xiaoheihe_base_url="https://example.com/{appid}",
    )
    supplemental = ToggleableSupplementalProvider(settings)
    app = create_app(
        settings=settings,
        providers=[provider, supplemental],
        scheduler_enabled=False,
    )
    app.state.notifier_builder = lambda session: FakeNotifier(enabled=False)

    provider.queue(
        6000,
        build_data(
            6000,
            title="Primary Price",
            current_price="40.00",
            original_price="80.00",
            discount_percent=50,
        ),
        build_data(
            6000,
            title="Primary Price",
            current_price="40.00",
            original_price="80.00",
            discount_percent=50,
        ),
    )

    with TestClient(app) as client:
        created = client.post("/watch-items", json={"steam_appid": 6000, "target_price": 25})
        assert created.status_code == 200
        assert created.json()["current_price"] == "40.00"

        settings_response = client.post(
            "/settings",
            data={
                "refresh_interval_minutes": 180,
                "full_sync_hour": 6,
                "notification_email": "",
                "smtp_host": "",
                "smtp_port": 587,
                "smtp_username": "",
                "smtp_password": "",
                "smtp_sender": "",
                "xiaoheihe_enabled": "on",
            },
            follow_redirects=False,
        )
        assert settings_response.status_code == 303

        refresh = client.post("/jobs/refresh", json={"steam_appid": 6000})
        assert refresh.status_code == 200

        watch_items = client.get("/watch-items").json()
        assert watch_items[0]["current_price"] == "18.00"


def test_email_notifier_uses_ssl_transport(monkeypatch):
    calls: list[str] = []

    class DummySMTP:
        def __init__(self, *args, **kwargs) -> None:
            calls.append("smtp")

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

        def starttls(self) -> None:
            calls.append("starttls")

        def login(self, username: str, password: str) -> None:
            calls.append(f"login:{username}")

        def send_message(self, message) -> None:
            calls.append("send")

    class DummySMTPSSL(DummySMTP):
        def __init__(self, *args, **kwargs) -> None:
            calls.append("smtp_ssl")

    monkeypatch.setattr("steam_price_monitor.services.notifications.smtplib.SMTP", DummySMTP)
    monkeypatch.setattr(
        "steam_price_monitor.services.notifications.smtplib.SMTP_SSL",
        DummySMTPSSL,
    )

    notifier = EmailNotifier(
        RuntimeSettings(
            refresh_interval_minutes=180,
            full_sync_hour=6,
            notification_email="receiver@example.com",
            smtp_host="smtp.example.com",
            smtp_port=465,
            smtp_username="sender@example.com",
            smtp_password="secret",
            smtp_sender="sender@example.com",
            smtp_use_tls=False,
            smtp_use_ssl=True,
            xiaoheihe_enabled=False,
        )
    )

    notifier.send("subject", "body")

    assert "smtp_ssl" in calls
    assert "starttls" not in calls
    assert "send" in calls
