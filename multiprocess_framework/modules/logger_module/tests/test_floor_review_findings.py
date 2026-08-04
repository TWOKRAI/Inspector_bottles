# -*- coding: utf-8 -*-
"""Регресс-стражи по находкам независимого ревью Ф0.9 (2026-07-27).

Каждый тест здесь закрепляет ОДНУ находку, воспроизведённую ревьюером
запуском. Файл отдельный намеренно: это не «тесты фичи», а доказательства
того, что конкретные дефекты не вернутся. Каждый docstring называет, чем
дефект был опасен, — иначе через полгода тест выглядит придиркой.

Находки:
  1. [blocker] severity-путь ``ErrorManager`` не разбирал статус ``write()``:
     закрытый или отбросивший запись канал считался записавшим, floor не
     срабатывал, ``errors_to_floor`` оставался нулём. Ошибка исчезала, и
     «маршрут сломан» не было видно ни по файлу, ни по счётчику.
  2. [blocker] Прод-раскладка сводила floor'ы ВСЕХ процессов в один файл
     (дозапись не атомарна → потери и битые строки), а у одного процесса
     floor'ов получалось два в разных каталогах.
  3. [major] ``errors_to_floor`` считал «передано в пол», а не «записано»:
     при отказе самого пола запись исчезала полностью, а счётчик уверял, что
     она спасена.
  4. [minor] Резолв пути не смотрел на ``enabled`` — выключенный канал (ровно
     тот случай, ради которого floor и нужен) решал, куда floor ляжет.
  6. [minor] Пустой ``scope.channels`` + module-канал давали ДВЕ копии одной
     записи, что прямо нарушает инвариант «одна ошибка — одна запись».
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

import pytest

from multiprocess_framework.modules.error_module import ErrorManager, ErrorManagerConfig
from multiprocess_framework.modules.logger_module.core.error_floor import reset_error_floors
from multiprocess_framework.modules.logger_module.core.log_config import (
    LoggerChannelSchema,
    LoggerManagerConfig,
    LoggerScopeSchema,
)
from multiprocess_framework.modules.logger_module.channels.log_channel import LogChannel
from multiprocess_framework.modules.logger_module.core.logger_manager import LoggerManager


@pytest.fixture(autouse=True)
def _clean_floors():
    reset_error_floors()
    yield
    reset_error_floors()


class _FakeProcess:
    """Минимальный носитель ``.name`` — менеджеры берут из процесса только его."""

    def __init__(self, name: str) -> None:
        self.name = name


class _RefusingChannel(LogChannel):
    """Канал, который НЕ бросает исключение, но и не записывает.

    Ровно то, что делает закрытый ``FileChannel`` (его закрывает штатный
    ``reconfigure``, пока воркер пишет ошибку) и отбросивший запись
    ``ConsoleChannel`` (R2). Отличать такой канал от рабочего можно ТОЛЬКО
    по статусу — исключения не будет.

    Наследует ``LogChannel`` не для удобства: ``ChannelRegistry.register``
    проверяет тип, и утиный двойник просто НЕ регистрируется. Первая версия
    этого теста была именно такой — и зеленела по постороннему поводу: пол
    срабатывал из-за отсутствия каналов, а не из-за их отказа. Проверка
    ``attempts > 0`` ниже стоит ровно для того, чтобы это больше не прошло
    незамеченным.
    """

    def __init__(self, name: str = "errors_file") -> None:
        super().__init__(LoggerChannelSchema(name=name, type="file", enabled=True))
        self.attempts = 0

    def write(self, record: Dict[str, Any]) -> Dict[str, Any]:
        self.attempts += 1
        return {"status": "error", "error": "канал закрыт", "channel": self.name}

    def close(self) -> None:
        return None


# =============================================================================
# Находка 1 [blocker]: severity-путь обязан разбирать статус
# =============================================================================


def test_error_manager_falls_to_floor_when_channel_refuses(tmp_path: Path) -> None:
    """Канал ответил ``status=error`` → ошибка обязана уйти в пол.

    До правки severity-путь делал ``ch.write(...); return`` — не глядя на
    ответ. Это ГЛАВНЫЙ путь ошибок в проде (`ERROR`/`CRITICAL` идут через
    ``_level_to_channel``), поэтому цена была максимальной: запись исчезала,
    floor молчал, счётчик показывал ноль. Отсутствие следа хуже, чем след с
    ошибкой: по нулевому счётчику маршрут выглядит здоровым.
    """
    mgr = ErrorManager(
        manager_name="ErrorRefuseProbe",
        config=ErrorManagerConfig(
            app_name="floor_findings",
            enable_batching=False,
            critical_file_path=str(tmp_path / "critical.log"),
            error_file_path=str(tmp_path / "errors.log"),
            warnings_file_path=str(tmp_path / "warnings.log"),
        ),
        process=_FakeProcess("refuse_probe"),
    )
    mgr.initialize()
    try:
        # Подменяем ВСЕ каналы отказывающими — исключений не будет ни одного.
        refusing = []
        for name in mgr._channel_registry.names():
            ch = _RefusingChannel(name)
            refusing.append(ch)
            mgr._channel_registry.unregister(name)
            mgr._channel_registry.register(ch)

        mgr.error("ошибка в отказывающий канал", module="findings")

        stats = mgr.get_stats()
        assert stats["errors_to_floor"] >= 1, (
            "канал ответил отказом, но запись сочли доставленной — floor не сработал; "
            f"stats={ {k: v for k, v in stats.items() if 'floor' in k} }"
        )
        floor_path = Path(stats["error_floor"]["path"])
        assert floor_path.exists(), "пол обязан был появиться"
        payload = floor_path.read_text(encoding="utf-8")
        assert "ошибка в отказывающий канал" in payload, "в полу нет самой записи"
        assert any(ch.attempts > 0 for ch in refusing), "канал даже не попробовали"
    finally:
        mgr.shutdown()


# =============================================================================
# Находка 2 [blocker]: floor разведён по процессам
# =============================================================================


def _floor_path_for(process_name: str, logs_dir: Path) -> Dict[str, str]:
    """Пути пола обоих менеджеров одного процесса при прод-раскладке.

    Прод-раскладка: у ErrorManager АБСОЛЮТНЫЕ пути каналов и НЕТ
    ``log_directory`` (``managers_config.managers_from_log_dir``), у логгера —
    ``log_directory``. Именно это расхождение и разводило их полы по разным
    каталогам.
    """
    process = _FakeProcess(process_name)
    logger = LoggerManager(
        manager_name=f"logger_{process_name}",
        config=LoggerManagerConfig(
            app_name="floor_findings",
            log_directory=str(logs_dir),
            enable_batching=False,
            modules={},
            channels={"console": LoggerChannelSchema(name="console", type="console", enabled=False)},
            scopes={"SYSTEM": LoggerScopeSchema(enabled=True, min_level="DEBUG", channels=[])},
        ),
        process=process,
    )
    error = ErrorManager(
        manager_name=f"error_{process_name}",
        config=ErrorManagerConfig(
            app_name="floor_findings",
            enable_batching=False,
            critical_file_path=str(logs_dir / "critical.log"),
            error_file_path=str(logs_dir / "errors.log"),
            warnings_file_path=None,
        ),
        process=process,
    )
    try:
        return {"logger": logger._resolve_floor_path(), "error": error._resolve_floor_path()}
    finally:
        logger.shutdown()
        error.shutdown()


def test_both_managers_of_one_process_share_one_floor(tmp_path: Path) -> None:
    """Логгер и ошибки ОДНОГО процесса пишут в ОДИН файл-пол.

    Иначе «одно место» — неправда: у процесса два пола в разных каталогах, и
    в какой ляжет запись, зависит от того, какой менеджер её потерял. Искать
    улику приходится в двух местах, зная внутреннее устройство.
    """
    paths = _floor_path_for("camera_process", tmp_path / "logs")
    assert paths["logger"] == paths["error"], (
        f"у одного процесса получилось ДВА пола:\n  логгер: {paths['logger']}\n  ошибки: {paths['error']}"
    )


def test_different_processes_get_different_floors(tmp_path: Path) -> None:
    """Разные процессы — разные файлы-полы.

    Общий файл ломается не теоретически: ``open(path, "a")`` не даёт атомарной
    дозаписи, и ревью намерило ~9-11 % потерянных записей и битые строки JSONL
    при четырёх процессах. Причём именно тогда, когда пол — единственный
    источник правды: при системном шторме ошибок.
    """
    logs = tmp_path / "logs"
    first = _floor_path_for("camera_process", logs)
    second = _floor_path_for("gui", logs)
    assert first["error"] != second["error"], f"полы разных процессов сошлись в один файл: {first['error']}"
    assert first["logger"] != second["logger"]


# =============================================================================
# Находка 3 [major]: счётчик означает «записано», а не «передано»
# =============================================================================


def test_floor_failure_is_counted_separately_and_not_as_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Пол не смог записать → ``errors_to_floor`` НЕ растёт, растёт счётчик отказов.

    Прежний порядок (инкремент до записи, результат отброшен) означал, что при
    отказе диска запись исчезала полностью, а счётчик уверял, что она спасена.
    Счётчик, означающий «передано», хуже отсутствующего: ему верят.
    """
    mgr = LoggerManager(
        manager_name="FloorFailProbe",
        config=LoggerManagerConfig(
            app_name="floor_findings",
            log_directory=str(tmp_path),
            enable_batching=False,
            modules={},
            channels={},
            scopes={"SYSTEM": LoggerScopeSchema(enabled=True, min_level="DEBUG", channels=[])},
        ),
        process=_FakeProcess("floor_fail"),
    )
    mgr.initialize()
    try:
        floor = mgr.error_floor
        monkeypatch.setattr(floor, "write", lambda record: False)

        before = mgr.get_stats()
        mgr.error("пол тоже отказал", module="findings")
        after = mgr.get_stats()

        assert after["errors_to_floor"] == before["errors_to_floor"], (
            "запись НЕ легла в пол, но счётчик спасённых вырос — счётчик врёт"
        )
        assert after["errors_floor_write_failures"] == before["errors_floor_write_failures"] + 1, (
            "полная потеря записи обязана быть посчитана отдельно"
        )
    finally:
        mgr.shutdown()


# =============================================================================
# Находка 4 [minor]: выключенный канал не решает, куда ляжет пол
# =============================================================================


def test_disabled_channel_does_not_choose_the_floor_location(tmp_path: Path) -> None:
    """Первый файловый канал ВЫКЛЮЧЕН и указывает в другое место — пол туда не идёт.

    Выключенный приёмник — ровно тот случай, ради которого floor существует.
    Позволять ему ещё и выбирать место для пола значит класть улику туда, куда
    указывает то, что сломано.
    """
    good = tmp_path / "logs"
    good.mkdir()
    unused = tmp_path / "never_used"

    mgr = LoggerManager(
        manager_name="DisabledChannelProbe",
        config=LoggerManagerConfig(
            app_name="floor_findings",
            log_directory=None,
            enable_batching=False,
            modules={},
            channels={
                "dead_file": LoggerChannelSchema(
                    name="dead_file",
                    type="file",
                    enabled=False,
                    file_path=str(unused / "dead.log"),
                    rotate=False,
                ),
                "live_file": LoggerChannelSchema(
                    name="live_file",
                    type="file",
                    enabled=True,
                    file_path=str(good / "live.log"),
                    rotate=False,
                ),
            },
            scopes={"SYSTEM": LoggerScopeSchema(enabled=True, min_level="DEBUG", channels=["live_file"])},
        ),
        process=_FakeProcess("disabled_probe"),
    )
    try:
        floor_path = Path(mgr._resolve_floor_path())
        assert unused not in floor_path.parents, f"пол ушёл в каталог ВЫКЛЮЧЕННОГО канала: {floor_path}"
        assert good in floor_path.parents, f"пол обязан лежать при живом канале, а лежит в {floor_path}"
    finally:
        mgr.shutdown()


# =============================================================================
# Находка 6 [minor]: одна ошибка — одна запись, даже без явного списка каналов
# =============================================================================


def test_no_duplicate_when_scope_has_no_explicit_channels(tmp_path: Path) -> None:
    """Пустой ``scope.channels`` + добавка правила не дают ДВУХ копий записи.

    **Переклассифицирован в Ф2.6, свойство сохранено дословно.** Опасность
    исходно нашли на per-module канале: при пустом списке скоупа fallback берёт
    ВЕСЬ реестр, module-канал в нём уже есть, и его дописывали вторым — одна
    ошибка ложилась в файл дважды. Механизм per-module файлов снят, но сложение
    осталось: ``channels_extra`` добавляет приёмник к унаследованному набору, и
    ровно та же ловушка воспроизводится, когда набор пришёл из fallback'а.

    В прод-дефолтах не стреляло и тогда, и сейчас — только потому, что у скоупов
    есть явные списки. Тест держит именно вырожденный путь.
    """
    mgr = LoggerManager(
        manager_name="DupProbe",
        config=LoggerManagerConfig(
            app_name="floor_findings",
            log_directory=str(tmp_path),
            enable_batching=False,
            channels={
                "проба_файл": LoggerChannelSchema(type="file", enabled=True, file_path="проба.log", rotate=False),
            },
            # Пустой список — тот самый вырожденный случай: набор берётся из реестра.
            scopes={"SYSTEM": LoggerScopeSchema(enabled=True, min_level="DEBUG", channels=[])},
            loggers={"проба": {"channels_extra": ["проба_файл"]}},
        ),
        process=_FakeProcess("dup_probe"),
    )
    mgr.initialize()
    try:
        marker = "DUP-MARKER-уникальная-строка"
        mgr.error(marker, module="проба")
        mgr.flush()

        content = (tmp_path / "dup_probe" / "проба.log").read_text(encoding="utf-8", errors="replace")
        assert content.count(marker) == 1, (
            f"одна ошибка легла в файл {content.count(marker)} раз(а) — инвариант «одна запись» нарушен"
        )
    finally:
        mgr.shutdown()


# =============================================================================
# Находка 5 [minor]: пол ограничен по размеру, хоть и защищён от ретеншена
# =============================================================================


def test_floor_rotates_itself_at_the_size_cap(tmp_path: Path) -> None:
    """Пол не растёт бесконечно: по достижении потолка уходит в ``.1``.

    Ретеншен (Ф0.7) пол намеренно не подметает — это последнее свидетельство о
    падении. Но «не подметаем» не значит «пусть растёт»: при долгоживущем
    ``logger.sink.disable`` каждая ошибка идёт сюда, и файл повторил бы историю
    ``messages.log`` (645 МБ незамеченными).
    """
    from multiprocess_framework.modules.logger_module.core.error_floor import ErrorFloor

    # Потолок ПО УМОЛЧАНИЮ обязан быть включён. Без этой строки тест проверял бы
    # только механизм (он задаёт max_bytes явно) и остался бы зелёным, даже если
    # дефолт выключить — то есть ровно в том случае, ради которого он написан.
    # Выяснилось слом-инъекцией: обнуление дефолта не роняло тест.
    assert ErrorFloor._MAX_BYTES > 0, "ретеншен пол не подметает — значит потолок обязан быть у него самого"

    floor = ErrorFloor(str(tmp_path / "errors_floor.jsonl"), max_bytes=2048)
    try:
        record = {"message": "x" * 200, "level": "ERROR"}
        for _ in range(50):
            assert floor.write(record) is True

        main = tmp_path / "errors_floor.jsonl"
        backup = tmp_path / "errors_floor.jsonl.1"
        assert main.exists()
        assert backup.exists(), "по достижении потолка пол обязан сдвинуться в .1"
        assert main.stat().st_size <= 2048, "текущий файл обязан остаться в пределах потолка"
        assert floor.stats["rotations"] >= 1
        assert floor.stats["failures"] == 0, "ротация не должна стоить ни одной потерянной записи"

        # Старые записи отбрасываются НАМЕРЕННО: один бэкап — это и есть потолок,
        # иначе «ограничили» означало бы «не ограничили». Проверяется не полнота
        # истории, а два свойства, которые обязаны держаться: файлы остались
        # разбираемыми (ротация не рвёт строку посередине) и свежая запись цела.
        lines: List[str] = []
        for path in (backup, main):
            lines.extend(line for line in path.read_text(encoding="utf-8").splitlines() if line.strip())
        assert lines, "после ротации на диске не осталось ни одной записи"
        for line in lines:
            json.loads(line)  # ни одной порванной строки
        assert len(lines) < 50, "потолок не сработал: на диске вся история"
        floor.write({"message": "ПОСЛЕДНЯЯ", "level": "CRITICAL"})
        assert "ПОСЛЕДНЯЯ" in main.read_text(encoding="utf-8"), "после ротации пол обязан продолжать принимать записи"
    finally:
        floor.close()
