from __future__ import annotations

from collections import defaultdict
from decimal import Decimal
import os
from pathlib import Path
import sys
import tempfile

import pytest
from fastapi.testclient import TestClient

from steam_price_monitor.config import Settings
from steam_price_monitor.main import create_app
from steam_price_monitor.providers.base import PriceOffer, ProviderGameData


if sys.platform == "win32":
    import _pytest.pathlib as pytest_pathlib
    import _pytest.tmpdir as pytest_tmpdir

    PROJECT_ROOT = Path(__file__).resolve().parents[1]
    PROJECT_TEMP_ROOT = PROJECT_ROOT / ".tmp"
    PROJECT_TEMP_ROOT.mkdir(exist_ok=True)
    os.environ.setdefault("PYTEST_DEBUG_TEMPROOT", str(PROJECT_TEMP_ROOT))
    tempfile.tempdir = str(PROJECT_TEMP_ROOT)

    _orig_make_numbered_dir = pytest_pathlib.make_numbered_dir

    def _make_numbered_dir_windows(root: Path, prefix: str, mode: int = 0o700) -> Path:
        safe_mode = 0o777 if mode == 0o700 else mode
        return _orig_make_numbered_dir(root, prefix, safe_mode)

    def _getbasetemp_windows(self) -> Path:
        if self._basetemp is not None:
            return self._basetemp

        if self._given_basetemp is not None:
            basetemp = self._given_basetemp
            if basetemp.exists():
                try:
                    pytest_pathlib.rm_rf(basetemp)
                except PermissionError:
                    basetemp = basetemp.parent / f"{basetemp.name}-{os.getpid()}"
            basetemp.mkdir(mode=0o777, exist_ok=True)
            basetemp = basetemp.resolve()
        else:
            from_env = os.environ.get("PYTEST_DEBUG_TEMPROOT")
            temproot = Path(from_env or tempfile.gettempdir()).resolve()
            user = pytest_tmpdir.get_user() or "unknown"
            rootdir = temproot.joinpath(f"pytest-of-{user}")
            try:
                rootdir.mkdir(mode=0o777, exist_ok=True)
            except OSError:
                rootdir = temproot.joinpath("pytest-of-unknown")
                rootdir.mkdir(mode=0o777, exist_ok=True)
            keep = self._retention_count
            if self._retention_policy == "none":
                keep = 0
            basetemp = pytest_pathlib.make_numbered_dir_with_cleanup(
                prefix="pytest-",
                root=rootdir,
                keep=keep,
                lock_timeout=pytest_tmpdir.LOCK_TIMEOUT,
                mode=0o777,
            )

        self._basetemp = basetemp
        self._trace("new basetemp", basetemp)
        return basetemp

    pytest_pathlib.make_numbered_dir = _make_numbered_dir_windows
    pytest_tmpdir.TempPathFactory.getbasetemp = _getbasetemp_windows


class FakeProvider:
    name = "steam"

    def __init__(self) -> None:
        self.responses: dict[int, list[ProviderGameData | None]] = defaultdict(list)

    def queue(self, steam_appid: int, *responses: ProviderGameData | None) -> None:
        self.responses[steam_appid].extend(responses)

    def fetch(self, steam_appid: int) -> ProviderGameData | None:
        bucket = self.responses.get(steam_appid, [])
        if bucket:
            response = bucket.pop(0)
            if isinstance(response, Exception):
                raise response
            return response
        return None


class NullSupplementalProvider:
    name = "xiaoheihe"

    def fetch(self, steam_appid: int):
        return None


class ToggleableSupplementalProvider:
    name = "xiaoheihe"

    def __init__(self, settings) -> None:
        self.settings = settings

    def fetch(self, steam_appid: int):
        if not self.settings.xiaoheihe_enabled:
            return None
        return build_data(
            steam_appid,
            title=f"Supplemental {steam_appid}",
            current_price="18.00",
            original_price="60.00",
            discount_percent=70,
            source_name=self.name,
        )


class FakeNotifier:
    def __init__(self, enabled: bool = True, should_fail: bool = False) -> None:
        self.enabled = enabled
        self.should_fail = should_fail
        self.sent_messages: list[tuple[str, str]] = []

    def send(self, subject: str, body: str) -> None:
        if self.should_fail:
            raise RuntimeError("smtp failure")
        self.sent_messages.append((subject, body))


def build_data(
    steam_appid: int,
    *,
    title: str,
    current_price: str,
    original_price: str,
    discount_percent: int,
    edition_label: str = "Standard",
    base_game_appid: int | None = None,
    value_score: str = "1.00",
    source_name: str = "steam",
) -> ProviderGameData:
    return ProviderGameData(
        steam_appid=steam_appid,
        source_name=source_name,
        title=title,
        offers=[
            PriceOffer(
                source_name=source_name,
                source_game_id=str(steam_appid),
                title=title,
                current_price=Decimal(current_price),
                original_price=Decimal(original_price),
                discount_percent=discount_percent,
                currency="CNY",
                edition_label=edition_label,
                base_game_appid=base_game_appid,
                value_score=Decimal(value_score),
                source_url=f"https://example.com/{steam_appid}",
            )
        ],
    )


@pytest.fixture
def provider() -> FakeProvider:
    return FakeProvider()


@pytest.fixture
def notifier() -> FakeNotifier:
    return FakeNotifier()


@pytest.fixture
def client(tmp_path, provider: FakeProvider, notifier: FakeNotifier):
    settings = Settings(
        database_url=f"sqlite:///{(tmp_path / 'test.db').as_posix()}",
        scheduler_enabled=False,
    )
    app = create_app(
        settings=settings,
        providers=[provider, NullSupplementalProvider()],
        scheduler_enabled=False,
    )
    app.state.notifier_builder = lambda session: notifier
    with TestClient(app) as test_client:
        yield test_client
