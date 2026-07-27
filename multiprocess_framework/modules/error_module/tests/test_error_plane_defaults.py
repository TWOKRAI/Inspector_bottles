# -*- coding: utf-8 -*-
"""Резидуалы P2 и P3 — умолчания плоскости ошибок и живой fallback маршрутов.

**P3.** ErrorManager наследовал от ``LoggerManagerConfig`` два умолчания,
описывающих плоскость ЛОГОВ, а не ошибок:

  * ``scopes`` со ссылками на ``system_file`` / ``messages_file`` / ``console`` —
    каналов с такими именами в его реестре нет. Воспроизведено до правки:
    свежий ``ErrorManager().initialize()`` + ``flush()`` давал
    ``unresolved_channel_records = 2`` (``{'system_file': 1, 'messages_file': 1}``)
    в полном покое — то есть счётчик-сигнал «маршрут сломан» был загрязнён
    собственным стартовым шумом менеджера;
  * ``modules`` — девять per-module файлов (``camera.log``, ``gui.log`` …),
    которые он открывал и в которые не писал ни строки.

**P2.** ``_level_to_channel`` строился один раз на ``initialize()``. Снятие
``critical_file`` оставляло маршрут ``CRITICAL → critical_file`` живым в
публичном ``level_routes``, а сама запись уходила в floor мимо живого
``errors_file`` (воспроизведено: ``errors_to_floor`` 0 → 1).

Отдельно проверяется, что починка P2 не пробила инвариант 1: когда severity
каналов не осталось ВООБЩЕ, ошибка обязана дойти до пола, а не быть отклонённой
гейтом выключенных скоупов.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

import pytest

from ...logger_module.core.error_floor import reset_error_floors
from ...logger_module.core.log_config import LogLevel, LogScope
from ..configs.error_manager_config import ErrorManagerConfig
from ..core.error_config_assembly import expand_error_manager_config
from ..core.error_manager import ErrorManager


@pytest.fixture(autouse=True)
def _clean_floors():
    reset_error_floors()
    yield
    reset_error_floors()


class _FakeProcess:
    def __init__(self, name: str) -> None:
        self.name = name


def _manager(tmp_path: Path, **overrides: Any) -> ErrorManager:
    cfg = ErrorManagerConfig(
        app_name="plane",
        enable_batching=False,
        critical_file_path=str(tmp_path / "critical.log"),
        error_file_path=str(tmp_path / "errors.log"),
        warnings_file_path=str(tmp_path / "warnings.log"),
        **overrides,
    )
    mgr = ErrorManager(config=cfg, process=_FakeProcess("plane_probe"))
    mgr.initialize()
    return mgr


# =============================================================================
# P3 — собственный шум
# =============================================================================


class TestErrorPlaneIsQuietAtRest:
    def test_no_unresolved_records_at_rest(self, tmp_path: Path) -> None:
        """Свежий менеджер после старта и сброса — ноль потерь всех четырёх классов."""
        mgr = _manager(tmp_path)
        try:
            mgr.flush()
            stats = mgr.get_stats()

            assert stats["unresolved_channel_records"] == 0, (
                f"собственный стартовый шум: {stats['unresolved_channels']}"
            )
            assert stats["unresolved_channels"] == {}
            assert stats["records_without_channels"] == 0
            assert stats["channel_refused_records"] == 0
            assert stats["channel_write_errors"] == 0
        finally:
            mgr.shutdown()

    def test_default_config_is_quiet_too(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """``ErrorManager()`` без конфига — тот же менеджер, а не другой.

        Путь ``config=None`` собирался мимо ``expand_error_manager_config``, и
        без этой проверки «дефолтный» менеджер остался бы с логгерными скоупами.
        """
        monkeypatch.setenv("MULTIPROCESS_LOG_DIR", str(tmp_path))
        mgr = ErrorManager(config={"log_directory": str(tmp_path)})
        mgr.initialize()
        try:
            mgr.flush()
            assert mgr.get_stats()["unresolved_channel_records"] == 0
        finally:
            mgr.shutdown()

    def test_no_module_channels_are_opened(self, tmp_path: Path) -> None:
        """Плоскость ошибок не открывает per-module файлы логгера.

        Проверка по ДИСКУ, а не по реестру: цена дефекта была именно в файлах —
        второй открытый хэндл на тот же ротируемый файл, что держит логгер.
        """
        mgr = _manager(tmp_path)
        try:
            names = sorted(mgr._channel_registry.names())
            assert [n for n in names if n.startswith("module_")] == []
            assert mgr.get_stats()["module_channels_count"] == 0

            unexpected = sorted(
                p.name for p in tmp_path.glob("*.log") if p.name not in {"critical.log", "errors.log", "warnings.log"}
            )
            assert unexpected == [], f"плоскость ошибок создала чужие файлы: {unexpected}"
        finally:
            mgr.shutdown()

    def test_own_info_is_skipped_not_lost(self, tmp_path: Path) -> None:
        """INFO у плоскости ошибок — отклонён гейтом, а не «потерян».

        Разница принципиальная: ``messages_skipped`` означает «конфиг так
        решил», ``unresolved_channel_records`` — «маршрут сломан». Раньше
        собственный ``info()`` попадал во второй.
        """
        mgr = _manager(tmp_path)
        try:
            before = mgr.get_stats()
            mgr.info("информация плоскости ошибок", module="plane")
            after = mgr.get_stats()

            assert after["messages_skipped"] == before["messages_skipped"] + 1
            assert after["unresolved_channel_records"] == before["unresolved_channel_records"]
        finally:
            mgr.shutdown()

    def test_explicit_scopes_win_over_the_default(self) -> None:
        """Умолчание — именно умолчание: заданные скоупы не перетираются."""
        mine = {"BUSINESS": {"enabled": True, "min_level": "INFO", "channels": ["errors_file"]}}
        expanded = expand_error_manager_config({"scopes": mine})
        assert expanded["scopes"] == mine

    def test_explicit_modules_win_over_the_default(self) -> None:
        mine = {"audit": {"enabled": True, "file_path": "audit.log"}}
        expanded = expand_error_manager_config({"modules": mine})
        assert expanded["modules"] == mine


# =============================================================================
# P2 — маршруты уровней живут вместе с составом каналов
# =============================================================================


def _floor_records(mgr: ErrorManager) -> List[Dict[str, Any]]:
    path = mgr.get_stats()["error_floor"]
    if not path:
        return []
    text = Path(path["path"]).read_text(encoding="utf-8")
    return [json.loads(line) for line in text.splitlines() if line.strip()]


class TestSeverityRoutesFollowChannelChanges:
    def test_critical_falls_back_to_errors_file_after_disable(self, tmp_path: Path) -> None:
        """Снятый ``critical_file`` → CRITICAL идёт в ЖИВОЙ ``errors_file``, не в пол."""
        mgr = _manager(tmp_path)
        try:
            assert mgr.get_stats()["level_routes"]["CRITICAL"] == "critical_file"

            assert mgr.set_sink_enabled("critical_file", False)

            assert mgr.get_stats()["level_routes"]["CRITICAL"] == "errors_file", (
                "fallback-цепочка не пересчиталась — level_routes показывает несуществующий канал"
            )

            before_floor = mgr.get_stats()["errors_to_floor"]
            mgr.critical("критическая после снятия своего канала", module="plane")

            assert mgr.get_stats()["errors_to_floor"] == before_floor, (
                "запись ушла в пол при живом errors_file — fallback не сработал"
            )
            assert "критическая после снятия" in (tmp_path / "errors.log").read_text(encoding="utf-8")
        finally:
            mgr.shutdown()

    def test_route_is_restored_after_enable(self, tmp_path: Path) -> None:
        mgr = _manager(tmp_path)
        try:
            mgr.set_sink_enabled("critical_file", False)
            assert mgr.get_stats()["level_routes"]["CRITICAL"] == "errors_file"

            assert mgr.set_sink_enabled("critical_file", True)
            assert mgr.get_stats()["level_routes"]["CRITICAL"] == "critical_file", (
                "включение приёмника обратно не вернуло его маршрут"
            )
        finally:
            mgr.shutdown()

    def test_error_still_reaches_floor_without_any_receiver(self, tmp_path: Path) -> None:
        """Инвариант 1 переживает P2 и P3 одновременно.

        Самое опасное сочетание: маршрутов уровней не осталось (P2 их убрал,
        потому что каналов нет), а скоупы плоскости выключены (P3). Наивная
        реализация делегировала бы такую ошибку родителю — и гейт отклонил бы
        её МОЛЧА. Первая редакция P2 ровно это и сделала: четыре красных теста,
        включая оба теста пола.
        """
        mgr = _manager(tmp_path)
        try:
            for name in list(mgr._channel_registry.names()):
                mgr.set_sink_enabled(name, False)
            assert mgr.get_stats()["level_routes"] == {}

            mgr.error("ошибка без единого приёмника", module="plane")

            assert mgr.get_stats()["errors_to_floor"] == 1
            messages = [rec.get("message") for rec in _floor_records(mgr)]
            assert messages == ["ошибка без единого приёмника"]
        finally:
            mgr.shutdown()

    def test_severity_path_is_open_even_without_channels(self, tmp_path: Path) -> None:
        """Гейт severity-плоскости не зависит от наличия канала.

        Завязка на ``level.value in _level_to_channel`` (первая редакция Ф1.3)
        закрывала бы гейт ровно тогда, когда запись обязана дойти до пола.
        """
        mgr = _manager(tmp_path)
        try:
            for name in list(mgr._channel_registry.names()):
                mgr.set_sink_enabled(name, False)

            assert mgr.is_enabled_for("plane", LogLevel.ERROR) is True
            assert mgr.is_enabled_for("plane", LogLevel.WARNING) is True
            assert mgr._route(LogScope.SYSTEM, LogLevel.ERROR, "plane") == []
            assert mgr.is_enabled_for("plane", LogLevel.INFO) is False
        finally:
            mgr.shutdown()
