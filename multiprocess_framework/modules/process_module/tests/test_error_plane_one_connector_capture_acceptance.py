# -*- coding: utf-8 -*-
"""RED (независимый тестер, plans/observability-closure): «один разъём на точку».

Критерий приёмки 1 + 5 (см. бриф задачи, раздел «Критерии приёмки», пп.1 и 5):
отказ открытия камеры (``Plugins/sources/capture/plugin.py::CapturePlugin._start_capture``,
ветка ``else: ctx.log_error(...)``) обязан доехать до ПЛОСКОСТИ ОШИБОК:

  * запись попадает в errors.log (файл ErrorManager'а, а не только в system.log);
  * ``ctx.health.status`` показывает ошибку (сейчас ``ctx.health.report_error``
    там не зовётся вовсе — ветка использует только ``ctx.log_error``);
  * инцидент несёт ПОЛНЫЙ Resource-контекст (camera_id/device_id), а не только
    текст исключения, интерполированный в строку сообщения.

Источник истины — ``interface.py`` для этого модуля НЕ существует
(MODULE_CONTRACT: impl-only на существующем ``CapturePlugin`` + существующий
``ctx.health`` контракт, см. ``multiprocess_framework/modules/process_module/health/state.py``
и ``.../plugins/base.py::PluginContext.health``). Тест написан против ПРОЗЫ
критериев приёмки, розданной оркестратором, БЕЗ чтения плана/ревью фазы.

Харнес — тот же приём, что в ``test_incident_pair_carries_source.py`` (сосед в
этом файле): настоящие ``ProcessModule`` + ``LoggerManager`` + ``ErrorManager``,
настоящий ``PluginContext`` (не MagicMock — иначе свойство ``ctx.health`` не
проверяется, см. контраст с ``Plugins/sources/capture/tests/test_health_fault.py``,
где ``ctx`` — MagicMock и ``ctx.health`` подменён руками).

Почему ОДНА функция на все факты, а не четыре теста (тот же приём, что уже
живёт в ``backend_ctl/tests/test_overview_thread_exceptions_acceptance.py``):
факт «в сторе появляется kind=error» уже ВЕРЕН СЕГОДНЯ и без фикса — ``ctx.log_error``
идёт через ``logger_manager``, а вид записи в сторе считает ТОЛЬКО важность
(``kind_for_severity``, Б-4), не то, какой менеджер её принёс. Отдельный тест
на этот факт был бы зелёным уже сейчас. Красным сегодня являются ИМЕННО
health.status и структурный Resource-контекст — они и несут RED, а факт про
store/errors.log проверяется рядом как часть той же сцены.
"""

from __future__ import annotations

import json
import time
from typing import Any, Dict, List
from unittest.mock import Mock

import pytest

from multiprocess_framework.modules.error_module.core.error_manager import ErrorManager
from multiprocess_framework.modules.logger_module.core.logger_manager import LoggerManager
from multiprocess_framework.modules.process_module.core.process_module import ProcessModule
from multiprocess_framework.modules.process_module.health.breaker import DEFAULT_FAIL_THRESHOLD
from multiprocess_framework.modules.process_module.health.schema import HealthStatus
from multiprocess_framework.modules.process_module.managers.observability_wiring import (
    unwire_observability_store,
    wire_observability_store,
)
from multiprocess_framework.modules.process_module.plugins import PluginContext

from Plugins.sources.capture.plugin import CapturePlugin


class _CapturingRouter:
    """Роутер-заглушка — граница процесса не участвует в этом сценарии."""

    def send_async(self, message: Dict[str, Any], priority: str = "normal") -> None:
        return None


def _manager_config(tmp_path, app: str, file_name: str) -> Dict[str, Any]:
    """Конфиг реального Logger/Error-менеджера с файловым каналом (см. соседний
    ``test_incident_pair_carries_source.py::_manager_config``); имя файла —
    параметром, чтобы ErrorManager писал именно ``errors.log``, а LoggerManager —
    ``system.log`` (та форма, что называет пробник C2 в ``test_error_route.py``)."""
    return {
        "app_name": app,
        "log_directory": str(tmp_path),
        "enable_batching": False,
        "modules": {},
        "channels": {"a": {"type": "file", "enabled": True, "file_path": str(tmp_path / file_name)}},
        "scopes": {
            "SYSTEM": {"channels": ["a"]},
            "BUSINESS": {"channels": ["a"]},
            "DEBUG": {"channels": ["a"]},
        },
    }


@pytest.fixture
def capture_scene(tmp_path):
    """Процесс с настоящими logger/error/store + CapturePlugin, камера падает на open."""
    logger = LoggerManager(manager_name="CamLog", config=_manager_config(tmp_path, "cam_log", "system.log"))
    logger.initialize()
    errors = ErrorManager(manager_name="CamErr", config=_manager_config(tmp_path, "cam_err", "errors.log"))
    errors.initialize()

    process = ProcessModule("camera_0")
    process.router_manager = _CapturingRouter()
    process.logger_manager = logger
    process.error_manager = errors
    process._observability_hub = Mock()
    process.register_manager("logger", logger, enabled=True)
    process.register_manager("error", errors, enabled=True)

    store, taps = wire_observability_store(
        error_manager=errors,
        logger_manager=logger,
        db_path=str(tmp_path / "store.db"),
        process="camera_0",
        min_level="INFO",
    )

    ctx = PluginContext(
        services=process,
        config={"camera_id": 3, "device_id": 7, "resolution_width": 320, "resolution_height": 240},
        plugin_name="capture",
    )
    plugin = CapturePlugin()
    plugin.configure(ctx)

    try:
        yield plugin, ctx, process, errors, store, tmp_path
    finally:
        unwire_observability_store(store, taps)
        logger.shutdown()
        errors.shutdown()


def _fake_unopened_capture(monkeypatch) -> None:
    """``cv2.VideoCapture(...).isOpened() -> False`` — камера физически недоступна."""

    class _FakeCap:
        def isOpened(self) -> bool:  # noqa: N802 — имя метода задано cv2
            return False

    monkeypatch.setattr("Plugins.sources.capture.plugin.cv2.VideoCapture", lambda *a, **kw: _FakeCap())


def _rows_dump(rows: List[Dict[str, Any]]) -> str:
    return json.dumps(rows, ensure_ascii=False, default=str)[:2000]


class TestCameraOpenFailureReachesTheErrorPlane:
    def test_camera_open_failure_is_a_single_incident_with_full_resource_context(
        self, capture_scene, monkeypatch
    ) -> None:
        plugin, ctx, process, errors, store, tmp_path = capture_scene
        _fake_unopened_capture(monkeypatch)

        ts_before = time.time()
        plugin.cmd_start_capture({})

        # --- факт 1: файл плоскости ошибок видит инцидент ---
        # ПРАВКА 2026-09-01 (диагноз investigator'а): тестер смотрел в
        # ``tmp_path/errors.log`` — канал, объявленный конфигом выше и привязанный
        # СКОУПАМИ. Запись severity=ERROR туда попасть не может НИ ПРИ КАКОМ
        # поведении продукта: ``ErrorManager.log`` для WARNING/ERROR/CRITICAL идёт
        # по ``_level_to_channel`` (error_manager.py:188-193), а скоупы правят
        # только DEBUG/INFO. Красный был артефактом харнесса, а не дефектом.
        # Боевой приёмник — дефолтный ``errors_file`` → ``<log_directory>/logs/errors.log``
        # (error_manager.py:65-72). Заодно объясняется INFO-строка, которая раньше
        # лежала в ``errors.log``: это собственная SYSTEM-болтовня ErrorManager'а
        # при инициализации, а не запись инцидента.
        errors_log_path = tmp_path / "logs" / "errors.log"
        errors_log_text = errors_log_path.read_text(encoding="utf-8") if errors_log_path.exists() else ""
        assert "камер" in errors_log_text or "camera" in errors_log_text.lower(), (
            "плоскость ошибок не увидела инцидент открытия камеры "
            f"(файл {'пуст' if not errors_log_text else 'есть, но мимо'}): "
            f"{errors_log_text!r}"
        )
        assert "[ERROR]" in errors_log_text, (
            f"инцидент доехал, но не как ошибка — уровень в строке не ERROR: {errors_log_text!r}"
        )

        # --- факт 2: снапшот health несёт факт отказа ---
        # ПРАВКА 2026-09-01 (диагноз investigator'а): тестер требовал
        # ``status != OK`` — контракта, которого у ``report_error`` НЕТ и не было.
        # ``report_error`` инкрементирует счётчик, пишет ``last_error`` и голосит
        # (health/README.md:17-21); смена статуса — отдельное API (``set_status`` /
        # ``degraded`` / ``failed``), а единственный автоматический путь в DEGRADED
        # это открытие breaker'а на пороге подряд-отказов. Принятая форма записана
        # в плане (phase-1, живая сверка 1.3b): «health.status показал errors=1 и
        # last_error». Проверяем её; деградацию — отдельным тестом ниже, чтобы
        # порог был назван явно, а не подразумевался.
        assert ctx.health.error_count == 1, (
            f"счётчик отказов health не вырос на инциденте открытия камеры: {ctx.health.error_count}"
        )
        assert ctx.health.status == HealthStatus.OK, (
            "один отказ не обязан менять статус — если поменял, изменился контракт "
            f"report_error, и это находка: {ctx.health.status!r}"
        )

        # --- факт 3: инцидент несёт ПОЛНЫЙ Resource-контекст, не только текст ---
        # camera_id=3 / device_id=7 обязаны доехать СТРУКТУРНО (context/extra записи
        # стора), а не только быть вплетены в текст f-строки, которую полнотекстовый
        # поиск найдёт, а фильтр по полю — нет.
        since_records = store.list_records(process="camera_0", since=ts_before - 1.0, limit=50)
        assert since_records, "ни одной записи в сторе по инциденту открытия камеры"
        blob = _rows_dump(since_records)
        # ПРАВКА 2026-09-01: было ``"3" in blob`` — тройка совпадает с любой цифрой
        # в метке времени или идентификаторе, то есть утверждение проходило бы и при
        # полностью потерянном контексте. Смотрим ПОЛЕ и его ЗНАЧЕНИЕ.
        contexts = [
            (row.get("extra") or {}).get("context") or {} for row in since_records if row.get("kind") == "error"
        ]
        assert contexts, f"в сторе нет записи kind=error по инциденту камеры: {blob}"
        assert any(c.get("camera_id") == 3 and c.get("device_id") == 7 for c in contexts), (
            f"Resource-контекст не доехал СТРУКТУРНО: ожидались поля camera_id=3 и "
            f"device_id=7 в extra.context записи kind=error, найдено: {contexts}"
        )

    def test_five_consecutive_failures_open_the_breaker_and_degrade(self, capture_scene, monkeypatch) -> None:
        """Деградация — от breaker'а, а не от одиночного ``report_error``.

        Тест назван отдельно (правка 2026-09-01), потому что предыдущий факт
        утверждает ОБРАТНОЕ — один отказ статус не меняет. Пара «один не меняет /
        пять меняют» держит контракт целиком: без второй половины первый assert
        нельзя отличить от «статус не меняется никогда», то есть от мёртвой ручки.

        Порог берётся из ``breaker.DEFAULT_FAIL_THRESHOLD`` (5) ИМПОРТОМ, а не
        литералом: тест, который списывает ожидаемое значение с кода, согласился бы
        с любым порогом — но здесь литерал стоит в отдельном assert ниже, и он
        обязан меняться осознанно.
        """
        plugin, ctx, process, errors, store, tmp_path = capture_scene
        _fake_unopened_capture(monkeypatch)

        assert DEFAULT_FAIL_THRESHOLD == 5, (
            "порог breaker'а изменился — сценарий ниже надо пересчитать осознанно, "
            f"а не подогнать: {DEFAULT_FAIL_THRESHOLD}"
        )

        for _ in range(DEFAULT_FAIL_THRESHOLD):
            plugin.cmd_start_capture({})

        assert ctx.health.error_count == DEFAULT_FAIL_THRESHOLD, (
            f"счётчик отказов не досчитал: {ctx.health.error_count}"
        )
        assert ctx.health.status is not HealthStatus.OK, (
            f"пять подряд отказов открытия камеры не деградировали процесс: "
            f"status={ctx.health.status!r}, errors={ctx.health.error_count}"
        )
