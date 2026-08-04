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
        """``ErrorManager()`` БЕЗ конфига — тот же менеджер, а не другой.

        Путь ``config=None`` собирался мимо ``expand_error_manager_config``, и
        без этой проверки «дефолтный» менеджер остался бы с логгерными скоупами.

        Здесь именно ``config=None``. Первая редакция теста передавала
        ``config={"log_directory": ...}`` — то есть dict-путь, уже покрытый
        соседями, — и возврат ветки ``None`` к прежней сборке оставлял все 588
        тестов зелёными. Docstring при этом обещал обратное. Найдено ревью Ф1;
        четвёртый вакуумный тест этой фазы.
        """
        monkeypatch.setenv("MULTIPROCESS_LOG_DIR", str(tmp_path))
        mgr = ErrorManager()
        mgr.initialize()
        try:
            mgr.flush()
            assert mgr.get_stats()["unresolved_channel_records"] == 0
            assert [s.enabled for s in mgr.config.scopes.values()] == [False] * len(mgr.config.scopes), (
                "дефолтный ErrorManager получил ЧУЖИЕ (логгерные) скоупы"
            )
        finally:
            mgr.shutdown()

    def test_no_foreign_files_are_opened(self, tmp_path: Path) -> None:
        """Плоскость ошибок не открывает чужих файлов.

        Проверка по ДИСКУ, а не по реестру: цена дефекта была именно в файлах —
        второй открытый хэндл на тот же ротируемый файл, что держит логгер.

        **Переклассифицирован в Ф2.6.** Прежняя редакция называла конкретного
        нарушителя (per-module файлы логгера) и заглядывала в снятый счётчик
        ``module_channels_count``. Механизма нет, а свойство шире исходного
        повода и осталось несущим: плоскость ошибок владеет ровно тремя своими
        файлами и ничем больше.
        """
        mgr = _manager(tmp_path)
        try:
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

    def test_every_level_has_a_fallback_receiver(self, tmp_path: Path) -> None:
        """Пол — для «приёмников нет», а не для «приёмник есть, просто не тот».

        Ревью Ф1: у ERROR запасного маршрута не было вовсе, и снятие одного
        ``errors_file`` при живом ``critical_file`` отправляло ошибку в пол
        (``errors_to_floor`` 0 → 1, ``critical.log`` пуст). Проверяются все три
        уровня по очереди — асимметрия обязана быть невозможной, а не
        исправленной в одном месте.
        """
        mgr = _manager(tmp_path)
        try:
            assert mgr.set_sink_enabled("errors_file", False)
            assert mgr.get_stats()["level_routes"]["ERROR"] == "critical_file", (
                "у ERROR нет запасного приёмника при живом critical_file"
            )

            before = mgr.get_stats()["errors_to_floor"]
            mgr.error("ошибка при живом critical_file", module="plane")

            assert mgr.get_stats()["errors_to_floor"] == before, "ушло в пол при живом приёмнике"
            assert "ошибка при живом critical_file" in (tmp_path / "critical.log").read_text(encoding="utf-8")

            # WARNING остаётся на своём, а без него уходит вверх, не вниз.
            assert mgr.set_sink_enabled("warnings_file", False)
            assert mgr.get_stats()["level_routes"]["WARNING"] == "critical_file"
        finally:
            mgr.shutdown()

    def test_fallback_record_keeps_its_own_level_label(self, tmp_path: Path) -> None:
        """Запасной приёмник не имеет права переклеить уровень записи.

        Формат ``critical_file`` был литералом ``[CRITICAL]`` — безобидным ровно
        до тех пор, пока в файл писал только CRITICAL. Достроенная цепочка
        запасных маршрутов сделала ERROR и WARNING в ``critical.log`` НЕОТЛИЧИМЫМИ
        от настоящего критикала (воспроизведено ревью Ф1: три записи разных
        уровней, все с меткой ``[CRITICAL]``). То есть починка «ошибка не должна
        прятаться в warnings.log» породила зеркальное «предупреждение выглядит
        критикалом» — в файле, по которому поднимают тревогу.

        Проверяется МЕТКА, а не вхождение текста: соседний тест смотрел на
        подстроку сообщения и этого поймать не мог.
        """
        mgr = _manager(tmp_path)
        try:
            assert mgr.set_sink_enabled("errors_file", False)
            assert mgr.set_sink_enabled("warnings_file", False)
            assert mgr.get_stats()["level_routes"] == {
                "CRITICAL": "critical_file",
                "ERROR": "critical_file",
                "WARNING": "critical_file",
            }, "предусловие: все три уровня свелись в один файл"

            mgr.warning("это предупреждение", module="plane")
            mgr.error("это ошибка", module="plane")
            mgr.critical("это критикал", module="plane")
            mgr.flush()

            text = (tmp_path / "critical.log").read_text(encoding="utf-8")
            labels = {line.split("]")[0].split("[")[-1] for line in text.splitlines() if "[" in line and "]" in line}
            assert labels == {"WARNING", "ERROR", "CRITICAL"}, (
                f"уровни в запасном файле склеились в {labels or 'ничто'} — тревога по critical.log станет ложной"
            )
        finally:
            mgr.shutdown()

    def test_fallback_never_goes_down_in_severity(self, tmp_path: Path) -> None:
        """Запасной приёмник — всегда более важный файл, никогда менее важный.

        Ошибка, спрятанная в ``warnings.log``, формально не потеряна, а
        практически потеряна: этот файл просматривают реже всех.
        """
        mgr = _manager(tmp_path)
        try:
            assert mgr.set_sink_enabled("errors_file", False)
            assert mgr.set_sink_enabled("critical_file", False)
            routes = mgr.get_stats()["level_routes"]

            assert "ERROR" not in routes, f"ERROR ушёл вниз по важности: {routes}"
            assert "CRITICAL" not in routes, f"CRITICAL ушёл вниз по важности: {routes}"
            assert routes.get("WARNING") == "warnings_file"

            mgr.error("ошибка без приёмников своего уровня", module="plane")
            assert mgr.get_stats()["errors_to_floor"] == 1, "должен был сработать пол"
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

    def test_error_before_initialize_still_reaches_its_channel(self, tmp_path: Path) -> None:
        """Между конструктором и ``initialize()`` ошибка обязана дойти (инвариант 1).

        ``_setup_level_routes()`` зовётся уже в ``__init__``. Без него запись
        НЕ теряется — гейт severity-плоскости открыт по рангу, и её ловит пол, —
        но уезжает в аварийный JSONL при живом ``errors.log``, а
        ``errors_to_floor`` поднимает ложный сигнал «маршрут ошибок сломан».
        Ровно это и проверяется, в таком порядке: сначала СВОЙСТВО (файл + пол),
        и только потом состав маршрутов как диагностика.

        Первая редакция теста била по предусловию (``level_routes`` пусты), то
        есть сторожила структуру, а не свойство; а её docstring вслед за
        комментарием в коде утверждал про «отклонён гейтом МОЛЧА» — неверно.
        Обе неточности сняты второй итерацией ревью Ф1 с воспроизведением.
        """
        mgr = ErrorManager(
            config=ErrorManagerConfig(
                app_name="preinit",
                enable_batching=False,
                critical_file_path=str(tmp_path / "critical.log"),
                error_file_path=str(tmp_path / "errors.log"),
                warnings_file_path=str(tmp_path / "warnings.log"),
            ),
            process=_FakeProcess("preinit_probe"),
        )
        # ВНИМАНИЕ: initialize() намеренно НЕ вызывается.
        try:
            mgr.error("ошибка до initialize", module="plane")

            # СВОЙСТВО — первым: ошибка в своём файле, пол не тронут.
            assert "ошибка до initialize" in (tmp_path / "errors.log").read_text(encoding="utf-8"), (
                "ошибка не дошла до errors.log между конструктором и initialize()"
            )
            assert mgr.get_stats()["errors_to_floor"] == 0, (
                "запись ушла в пол при живом канале — ложный сигнал «маршрут ошибок сломан»"
            )
            # Диагностика: почему свойство держится.
            assert mgr.get_stats()["level_routes"].get("ERROR") == "errors_file"
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
