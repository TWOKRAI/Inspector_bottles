"""CI-smoke: headless-boot minimal_app через BackendHarness + доказанный IPC (Ф5.13).

Образец — ``backend_ctl/tests/test_health_live.py`` (BackendHarness, driver
request/response). Отличие: BackendHarness по умолчанию поднимает
``multiprocess_prototype`` (``build_headless_launcher`` жёстко импортирует
``multiprocess_prototype.*``) — для minimal_app (второй, framework-only потребитель,
``examples/*`` не импортирует прототип) используется escape-hatch
``launcher_factory`` (Ф5.13): harness управляет тем же start/stop/kill_child/teardown
контрактом, но launcher собирает ``app_module.build_app`` — без единого импорта
прототипа.

Acceptance (5.13, plan.md #232): boot minimal_app + доказанный IPC (сообщение
прошло wire ticker → console_sink) + graceful shutdown, зелёный headless.

Не в дефолтном сборе pytest (маркер ``harness_smoke``, см. корневой
``pyproject.toml`` markers/testpaths — тот же режим, что у остальных live-тестов
``backend_ctl``). CI: отдельный job ``examples-smoke`` в
``.github/workflows/ci.yml`` запускает явным путём:

    python -m pytest examples/minimal_app/tests -m harness_smoke -q
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from backend_ctl.harness import BackendHarness

# .../examples/minimal_app/tests/<file> → parents[2] = examples/minimal_app.
_APP_DIR = Path(__file__).resolve().parents[1]
_APP_YAML = _APP_DIR / "app.yaml"

#: Уникальный порт этого модуля (8770-8795 заняты остальными live-тестами backend_ctl,
#: см. project_concurrent_backends_trap — свой порт изолирует бэкенд от параллельных).
_PORT = 8796


def _result(res: dict) -> dict:
    """Развернуть result-конверт ответа (см. backend_ctl/tests/test_health_live.py)."""
    if isinstance(res, dict) and isinstance(res.get("result"), dict):
        return res["result"]
    return res if isinstance(res, dict) else {}


@pytest.fixture
def minimal_app_backend(tmp_path: Path):
    """Headless minimal_app на своём порту + свой лог-каталог (изоляция от прототипа)."""
    prev_log = os.environ.get("MULTIPROCESS_LOG_DIR")
    log_dir = tmp_path / "log"
    log_dir.mkdir()
    os.environ["MULTIPROCESS_LOG_DIR"] = str(log_dir)

    def _build_minimal_app_launcher():
        from multiprocess_framework.modules.app_module import build_app

        return build_app(_APP_YAML)

    harness = BackendHarness(launcher_factory=_build_minimal_app_launcher, port=_PORT)
    drv = harness.start()
    try:
        yield drv
    finally:
        harness.stop()
        if prev_log is None:
            os.environ.pop("MULTIPROCESS_LOG_DIR", None)
        else:
            os.environ["MULTIPROCESS_LOG_DIR"] = prev_log


@pytest.mark.harness_smoke
def test_minimal_app_boots_and_ipc_delivers(minimal_app_backend) -> None:
    """boot headless (2 процесса) → ticker шлёт тик → console_sink принял ≥1 (IPC доказан)."""
    drv = minimal_app_backend

    deadline = time.time() + 15.0
    received = 0
    last_payload = None
    while time.time() < deadline:
        res = _result(drv.send_command("console_sink", "consumer_status", {}, timeout=5.0))
        assert res.get("status") == "ok", f"consumer_status не ok: {res}"
        received = res.get("received", 0)
        last_payload = res.get("last_payload")
        if received >= 1:
            break
        time.sleep(1.0)

    assert received >= 1, "console_sink не получил ни одного тика от ticker за 15s — IPC не доказан"
    assert last_payload == "hello-from-minimal-app", last_payload
