# -*- coding: utf-8 -*-
"""B3 — логгер гасится ПОСЛЕДНИМ, error/stats гасятся вообще.

Основание — major-5 + major-6 приёмочного ревью 2026-08-09:

* ``logger_manager.shutdown()`` стоял ТРЕТЬИМ из шести, а после него шли
  ``command``/``router``, смена статуса и запись «shut down successfully» — то
  есть INFO/WARNING уборки терялись ВСЕГДА (floor подстраховывает только
  ERROR/CRITICAL). Воспроизведено ревью: `unresolved=6`, `floor=1`;
* ``error_manager.shutdown()`` и ``stats_manager.shutdown()`` не вызывались
  нигде (grep по репозиторию — пусто), то есть финальный сброс двух плоскостей
  из трёх оставался на совести ОС.

Ф3, задача 3.1 (правка по ревью 2026-08-25): плоскостей стало ЧЕТЫРЕ —
``observation`` поднимается сборкой (``observation.initialize()``), а гасились
по-прежнему две. Блок «финальный сброс двух из трёх на совести ОС» повторился
слово в слово, просто про четвёртую.

Проверяется НАБЛЮДАЕМЫЙ ЭФФЕКТ, а не имя вызванного метода: дубль логгера
умеет ОТКАЗАТЬ — после своего ``shutdown`` он не принимает записи, а считает их
потерянными. Спай на имени сторожил бы имя; счётчик потерь сторожит свойство
«записи уборки доезжают».

**Дубли доказывают дубли, поэтому в конце файла один тест на НАСТОЯЩЕЙ сборке.**
Харнесс ниже расставляет менеджеры по атрибутам руками, и переименуй сборка
атрибут ``observation_manager`` — все тесты на дублях остались бы зелёными, а
плоскость снова гасилась бы нигде. Живой тест поднимает ``ProcessModule`` целиком
и спрашивает у слотов ``is_initialized``.
"""

from __future__ import annotations

from typing import Any, Dict, List
from unittest.mock import Mock

from ..core.process_module import ProcessModule


class _Journal:
    """Общий журнал порядка гашения — один на все дубли."""

    def __init__(self) -> None:
        self.order: List[str] = []


class _DyingLogger:
    """Логгер, который ПЕРЕСТАЁТ принимать записи после своего гашения.

    Дубль обязан уметь отказывать: фальшивка-всегда-успех глушит гейт, и
    свойство «запись уборки доехала» стало бы непроверяемым в принципе
    (оплаченный урок A2 — `MockProcessServices`, молча евший kwargs).
    """

    manager_name = "LoggerManager"

    def __init__(self, journal: _Journal) -> None:
        self._journal = journal
        self.alive = True
        self.written: List[str] = []
        self.lost_after_shutdown: List[str] = []

    def _accept(self, message: Any) -> None:
        (self.written if self.alive else self.lost_after_shutdown).append(str(message))

    def debug(self, message: Any, **kwargs: Any) -> None:
        self._accept(message)

    def info(self, message: Any, **kwargs: Any) -> None:
        self._accept(message)

    def warning(self, message: Any, **kwargs: Any) -> None:
        self._accept(message)

    def error(self, message: Any, **kwargs: Any) -> None:
        self._accept(message)

    def critical(self, message: Any, **kwargs: Any) -> None:
        self._accept(message)

    def clear_base_context(self) -> None: ...

    def shutdown(self) -> bool:
        self._journal.order.append("logger")
        self.alive = False
        return True


class _RecordingManager:
    """Менеджер, отмечающийся в журнале при гашении."""

    def __init__(self, journal: _Journal, name: str) -> None:
        self._journal = journal
        self._name = name
        self.flushed = 0

    def shutdown(self) -> bool:
        self._journal.order.append(self._name)
        self.flushed += 1
        return True


def _process_ready_to_stop() -> tuple:
    journal = _Journal()
    process = ProcessModule("teardown_proc")
    logger = _DyingLogger(journal)
    managers: Dict[str, Any] = {
        "logger": logger,
        "error": _RecordingManager(journal, "error"),
        "stats": _RecordingManager(journal, "stats"),
        "observation": _RecordingManager(journal, "observation"),
        "command": _RecordingManager(journal, "command"),
        "router": _RecordingManager(journal, "router"),
        "console": _RecordingManager(journal, "console"),
    }
    process.logger_manager = logger
    process.error_manager = managers["error"]
    process.stats_manager = managers["stats"]
    process.observation_manager = managers["observation"]
    process.command_manager = managers["command"]
    process.router_manager = managers["router"]
    process.console_manager = managers["console"]
    process.register_manager("logger", logger)
    process.is_initialized = True
    process._stop_system_threads = Mock()
    process.worker_manager = None
    process.shared_resources = None
    process.update_process_state = Mock()
    return process, logger, managers, journal


def test_logger_is_the_last_manager_to_die() -> None:
    process, _logger, _managers, journal = _process_ready_to_stop()
    assert process.shutdown() is True
    assert journal.order, "не погашен ни один менеджер"
    assert journal.order[-1] == "logger", f"логгер погашен не последним: {journal.order}"


def test_error_and_stats_planes_are_shut_down_at_all() -> None:
    """major-6: финальный flush двух плоскостей из трёх был на совести ОС."""
    process, _logger, managers, journal = _process_ready_to_stop()
    process.shutdown()
    assert "error" in journal.order, f"плоскость ошибок не гасится: {journal.order}"
    assert "stats" in journal.order, f"плоскость статистики не гасится: {journal.order}"
    assert managers["error"].flushed == 1
    assert managers["stats"].flushed == 1


def test_the_observation_plane_is_shut_down_at_all() -> None:
    """Ф3: четвёртая плоскость. До правки ревью 2026-08-25 гасились две из четырёх.

    Ломается, если строку гашения ``observation`` убрать из шага 4: цена сегодня
    нулевая (у порта пустой буфер и пустой реестр каналов), но задача 3.2
    понесёт в тот же реестр записи ``kind=observation``, и несброшенный буфер
    станет молчаливой потерей ровно на останове.
    """
    process, _logger, managers, journal = _process_ready_to_stop()
    process.shutdown()
    assert "observation" in journal.order, f"плоскость наблюдений не гасится: {journal.order}"
    assert managers["observation"].flushed == 1


def test_observation_dies_before_the_logger_it_will_write_through() -> None:
    """Тот же довод, что у stats: канал порта (3.2) пишет ЧЕРЕЗ логгер.

    Погаси логгер раньше — и финальный сброс уехал бы в мёртвый приёмник, то
    есть «гасим observation» существовало бы, а эффекта не давало.
    """
    process, _logger, _managers, journal = _process_ready_to_stop()
    process.shutdown()
    assert journal.order.index("observation") < journal.order.index("logger"), journal.order


def test_the_planes_that_were_stopped_are_named_in_the_journal() -> None:
    """Гашение младших плоскостей обязано быть ВИДНО в журнале.

    Собственная запись плоскости ошибок идёт по её же маршруту, а INFO по нему
    не ездит (пороги severity) — то есть «погасили» и «не погасили» выглядят в
    файле одинаково. Строка называет ФАКТИЧЕСКИ погашенное, а не список из
    докстринга: у процесса без плоскости статистики её в перечне не будет.
    """
    process, logger, _managers, _journal = _process_ready_to_stop()
    process.stats_manager = None
    process.shutdown()
    named = [line for line in logger.written if "observability planes stopped" in line]
    assert named, f"погашенные плоскости не названы: {logger.written}"
    assert "error" in named[0] and "stats" not in named[0], named[0]
    # Плоскостей четыре, и порт — единственная, чьё ИМЯ в этой строке не
    # сторожилось ничем: заплата «убрать только append, гашение оставить»
    # давала ноль красных на всём scope (находка ревью, итерация 2). Само
    # гашение закрыто соседними тестами — здесь охраняется ЖУРНАЛЬНЫЙ след,
    # объявленный докстрингом модуля единственным наблюдаемым.
    assert "observation" in named[0], named[0]


def test_stats_dies_before_the_logger_it_writes_through() -> None:
    """Порядок не произвольный: `log_stats` пишет ЧЕРЕЗ логгер.

    Погаси логгер раньше — и финальный снапшот метрик уедет в мёртвый канал,
    то есть «гасим stats» существовало бы, а эффекта не давало.
    """
    process, _logger, _managers, journal = _process_ready_to_stop()
    process.shutdown()
    assert journal.order.index("stats") < journal.order.index("logger"), journal.order


def test_teardown_records_reach_a_live_logger() -> None:
    """Наблюдаемый эффект: ни одна запись уборки не пришла в мёртвый логгер."""
    process, logger, _managers, _journal = _process_ready_to_stop()
    process.shutdown()
    assert logger.lost_after_shutdown == [], f"записи уборки уехали в мёртвый логгер: {logger.lost_after_shutdown}"
    assert any("shut down successfully" in line for line in logger.written), (
        f"итоговая INFO уборки не доехала вовсе: {logger.written}"
    )


def test_the_old_order_loses_them_and_that_is_countable() -> None:
    """Вторая половина пары: на «грязном» пути потеря ЕСТЬ и она видна.

    Тест, у которого зелёное — единственный исход, не отличает работающий
    порядок от отсутствующего. Здесь логгер гасится ДО останова (ровно прежний
    порядок), и те же записи уборки попадают в мёртвый приёмник — счётчик
    дубля их считает поимённо.
    """
    process, logger, _managers, _journal = _process_ready_to_stop()
    logger.shutdown()  # прежний порядок: логгер умер первым
    process.shutdown()
    assert logger.lost_after_shutdown, "потеря на грязном пути не зафиксирована — счётчик слеп"
    assert any("shut down successfully" in line for line in logger.lost_after_shutdown), logger.lost_after_shutdown


def test_a_failing_logger_shutdown_is_not_swallowed() -> None:
    """Отказ гашения логгера обязан быть слышен — и не отменять успех останова.

    Писать о нём через сам логгер нельзя (предмет претензии — он), поэтому
    named-исключение: аварийный выход stdlib.
    """
    import multiprocess_framework.modules.process_module.lifecycle.process_lifecycle as lifecycle

    process, logger, _managers, _journal = _process_ready_to_stop()
    logger.shutdown = Mock(side_effect=RuntimeError("канал не закрылся"))
    heard: List[str] = []
    original = lifecycle.emergency_log
    lifecycle.emergency_log = lambda *a, **k: heard.append(" ".join(str(x) for x in a))
    try:
        assert process.shutdown() is True, "отказ гашения логгера не должен ронять останов"
    finally:
        lifecycle.emergency_log = original
    assert heard, "отказ гашения логгера проглочен молча"
    assert any("канал не закрылся" in line for line in heard), heard


# --------------------------------------------------------------------------- #
# Настоящая сборка — один тест, чтобы дубли выше не доказывали сами себя.
# --------------------------------------------------------------------------- #

#: Плоскости наблюдаемости в том порядке, в каком их поднимает сборка. Список
#: один на весь тест: разойдись «поднято» и «погашено», расхождение обязано быть
#: видно в одном месте, а не в двух перечислениях.
OBSERVABILITY_PLANES = ("logger", "stats", "error", "observation")


def test_all_four_planes_of_a_real_process_are_stopped(monkeypatch, tmp_path) -> None:
    """ЧЕТЫРЕ плоскости настоящего ``ProcessModule`` погашены после ``shutdown``.

    Тест на НАСТОЯЩЕЙ сборке, а не на дублях: харнесс выше расставляет менеджеры
    по атрибутам руками, поэтому он остался бы зелёным и в том случае, когда
    сборка кладёт менеджера в слот, а шаг гашения ищет его под другим именем —
    ровно так плоскость и не гасилась до правки ревью 2026-08-25.

    **Якорь СУЩЕСТВОВАНИЯ, а не «не упало»:** каждая плоскость сперва
    предъявляется живой (``is_initialized is True``), и только потом
    проверяется, что она погашена. Без первой половины «все погашены»
    удовлетворял бы процесс, у которого их вовсе не подняли, — и ``None`` в
    слоте прошёл бы за успех.

    Секция ``error`` в конфиге не для красоты: без неё ``_create_error_manager``
    возвращает ``None``, плоскостей живых оказывается три, и утверждение про
    ЧЕТЫРЕ проверяло бы три.

    Ломается, если убрать гашение любой из четырёх (для ``observation`` — ту
    самую строку шага 4, которой не было).
    """
    monkeypatch.setenv("MULTIPROCESS_LOG_DIR", str(tmp_path / "logs"))
    process = ProcessModule("obs_teardown_probe", config={"managers": {"error": {"enabled": True}}})
    assert process.initialize() is True

    before = {name: process.get_manager(name) for name in OBSERVABILITY_PLANES}
    not_raised = [name for name, manager in before.items() if getattr(manager, "is_initialized", None) is not True]
    assert not not_raised, f"плоскости не подняты вовсе, гасить нечего: {not_raised}"

    assert process.shutdown() is True

    still_running = [
        name for name in OBSERVABILITY_PLANES if getattr(process.get_manager(name), "is_initialized", None) is not False
    ]
    assert not still_running, (
        f"после shutdown() процесса плоскости остались поднятыми: {still_running} "
        f"(их финальный сброс остаётся на совести ОС)"
    )
