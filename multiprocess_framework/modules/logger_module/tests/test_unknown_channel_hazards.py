# -*- coding: utf-8 -*-
"""Ф0.4 — внутренние опасности учёта нерезолвящихся каналов (АВТОРСКИЕ тесты).

Контрактную половину пишет независимый тестировщик
(``test_unknown_channel_accounting.py``) — она проверяет, что обещанное
поведение есть. Этот файл проверяет другое: что механизм учёта не ломается
в местах, которые видны только автору правки.

Опасности, за которыми здесь следят:
  1. Гонка инкремента: ``+=`` по dict/int не атомарен, а писать в лог могут
     десятки потоков плюс поток таймера буфера. Счётчик ПОТЕРЬ, который врёт
     в меньшую сторону, — хуже отсутствующего.
  2. Гонка «одноразового» предупреждения: проверка «уже предупреждали?» и
     отметка обязаны быть одной атомарной операцией, иначе N потоков дадут
     N предупреждений на одно имя.
  3. Реентерантность: предупреждение уходит через stdlib-логгер, у которого
     может стоять handler, сам пишущий в этот же LoggerManager. Если бы
     предупреждение эмитилось под lock'ом — дедлок.
  4. Взаимодействие с floor (Ф0.9): для error/critical нерезолвящийся канал
     НЕ означает потерю — запись подхватывает пол. Два счётчика обязаны быть
     согласованы, а не противоречить друг другу.
  5. reconfigure не имеет права стирать историю потерь: иначе hot-reload
     превращается в «отмыть статистику».
"""

from __future__ import annotations

import logging
import sys
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, List

import pytest

from multiprocess_framework.modules.logger_module.channels.log_channel import LogChannel
from multiprocess_framework.modules.logger_module.core.log_config import (
    LoggerChannelSchema,
    LoggerManagerConfig,
    LoggerScopeSchema,
)
from multiprocess_framework.modules.logger_module.core.logger_manager import LoggerManager


def _config(tmp_path: Path, *, enable_batching: bool, scope_channels: List[str]) -> LoggerManagerConfig:
    return LoggerManagerConfig(
        app_name="unknown_channel_hazards",
        log_directory=str(tmp_path),
        enable_batching=enable_batching,
        batch_size=10_000,
        batch_interval=600.0,
        modules={},
        channels={
            "system_file": LoggerChannelSchema(
                name="system_file", type="file", enabled=True, file_path="system.log", rotate=False
            ),
        },
        default_level="DEBUG",
        scopes={
            "BUSINESS": LoggerScopeSchema(channels=scope_channels),
            "SYSTEM": LoggerScopeSchema(channels=scope_channels),
        },
    )


@pytest.fixture
def manager(tmp_path: Path, request):
    """LoggerManager, у которого BUSINESS/SYSTEM роутятся в несуществующий канал."""
    batching = getattr(request, "param", True)
    mgr = LoggerManager(
        manager_name="HazardLogger",
        config=_config(tmp_path, enable_batching=batching, scope_channels=["ghost"]),
    )
    yield mgr
    mgr.shutdown()


# =============================================================================
# 1-2. Гонки: ни одного потерянного инкремента, ровно одно предупреждение
# =============================================================================


@contextmanager
def _hostile_scheduler(interval: float = 1e-6):
    """Переключать потоки как можно чаще — чтобы гонка была видна, а не «обычно не бывает».

    Без этого тест ниже зелёный ДАЖЕ со снятым lock'ом: при дефолтном
    ``switchinterval`` (5 мс) окно между чтением и записью счётчика почти
    никогда не попадает под вытеснение. Замер на этой машине: 12 × 3000
    записей, lock снят — 30265 вместо 36000 (потеряно 5735 инкрементов);
    с дефолтным интервалом та же нагрузка давала ровно 36000, то есть тест
    без этой обвязки не доказывал бы ничего.
    """
    previous = sys.getswitchinterval()
    sys.setswitchinterval(interval)
    try:
        yield
    finally:
        sys.setswitchinterval(previous)


@pytest.mark.parametrize("manager", [False], indirect=True)
def test_concurrent_emitters_lose_no_increment(manager) -> None:
    """12 потоков × 3000 записей в несуществующий канал → счётчик РОВНО 36000.

    ``+=`` по ``self.stats[...]`` и по словарю разбивки — это чтение и запись
    с окном вытеснения между ними. Прямой путь (без батчинга) выбран
    намеренно: он считает в потоке-эмитенте, то есть под настоящей гонкой,
    а не в одиночном потоке таймера.
    """
    threads_count, per_thread = 12, 3000
    barrier = threading.Barrier(threads_count)

    def worker(idx: int) -> None:
        # Ф6.х.1б: таймаут на барьере — смерть одного потока до барьера не
        # должна вешать остальных навечно (BrokenBarrierError уронит всех).
        barrier.wait(timeout=30)  # старт одновременный — иначе гонки может не случиться вовсе
        for i in range(per_thread):
            manager.info("гонка", module="unit")

    with _hostile_scheduler():
        threads = [threading.Thread(target=worker, args=(i,), daemon=True) for i in range(threads_count)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=120)
        assert not any(t.is_alive() for t in threads), "эмитенты не уложились в дедлайн — гонка зависла"

    stats = manager.get_stats()
    expected = threads_count * per_thread
    assert stats["unresolved_channel_records"] == expected
    assert stats["unresolved_channels"] == {"ghost": expected}


@pytest.mark.parametrize("manager", [False], indirect=True)
def test_one_warning_survives_the_race(manager, caplog) -> None:
    """16 потоков стартуют одновременно на ОДНО неизвестное имя → одно предупреждение.

    Проверка «уже предупреждали?» и отметка обязаны стоять внутри одного
    lock-а. Разнеси их — и предупреждений станет столько, сколько потоков
    успело проскочить между проверкой и отметкой.

    ЧЕСТНАЯ ОГОВОРКА о силе этого теста: со СНЯТЫМ lock'ом он остаётся
    зелёным — окно между проверкой и отметкой слишком узкое, чтобы попасть
    под вытеснение даже на враждебном планировщике. Он проверяет инвариант,
    но НЕ доказывает необходимость lock-а; необходимость доказана соседним
    ``test_concurrent_emitters_lose_no_increment`` (без lock-а 29261 из
    36000), а lock там и здесь один и тот же.
    """
    threads_count = 32
    barrier = threading.Barrier(threads_count)

    with caplog.at_level(logging.WARNING, logger="multiprocess_framework"), _hostile_scheduler():

        def worker() -> None:
            barrier.wait(timeout=30)  # Ф6.х.1б: см. соседний тест
            manager.info("одновременная запись", module="unit")

        threads = [threading.Thread(target=worker, daemon=True) for _ in range(threads_count)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=60)
        assert not any(t.is_alive() for t in threads), "потоки не уложились в дедлайн — гонка зависла"

        ghost_warnings = [r for r in caplog.records if "ghost" in r.getMessage()]
        assert len(ghost_warnings) == 1, f"предупреждений {len(ghost_warnings)}, ожидалось одно"


# =============================================================================
# 3. Реентерантность: handler предупреждения сам пишет в этот же логгер
# =============================================================================


class _ReentrantHandler(logging.Handler):
    """Handler, который в ответ на предупреждение пишет обратно в LoggerManager.

    Это не выдумка: в проде stdlib-логгер может быть подключён к тому же
    контуру наблюдаемости (std_facade). Если бы предупреждение эмитилось под
    ``_miss_lock``, повторный вход взял бы тот же нерекурсивный lock и поток
    встал бы навсегда.
    """

    def __init__(self, manager: LoggerManager) -> None:
        super().__init__()
        self._manager = manager
        self.seen = 0

    def emit(self, record: logging.LogRecord) -> None:
        self.seen += 1
        if self.seen <= 2:  # ограничитель — тест проверяет отсутствие дедлока, не глубину
            self._manager.info("ответная запись из handler'а", module="unit")


@pytest.mark.parametrize("manager", [False], indirect=True)
def test_warning_handler_may_log_back_without_deadlock(manager) -> None:
    """Реентерантный handler не вешает эмитента (тест упал бы по таймауту потока)."""
    root = logging.getLogger("multiprocess_framework")
    handler = _ReentrantHandler(manager)
    root.addHandler(handler)
    try:
        done = threading.Event()

        def worker() -> None:
            manager.info("запись, порождающая предупреждение", module="unit")
            done.set()

        t = threading.Thread(target=worker, daemon=True)
        t.start()
        t.join(timeout=5.0)

        assert done.is_set(), "эмитент завис — предупреждение эмитится под lock'ом"
    finally:
        root.removeHandler(handler)


# =============================================================================
# 4. Согласие с floor (Ф0.9): для ошибок «канала нет» ≠ «запись потеряна»
# =============================================================================


@pytest.mark.parametrize("manager", [False], indirect=True)
def test_unresolved_error_is_counted_and_still_rescued_by_floor(manager) -> None:
    """ERROR в несуществующий канал: счётчик растёт И пол ловит запись.

    Два счётчика описывают РАЗНОЕ и не должны противоречить: маршрут сломан
    (``unresolved_channel_records`` > 0), но запись уцелела
    (``errors_to_floor`` > 0, файл пола непустой). Реализация, которая ради
    «красивых нулей» не считала бы ошибочный путь, спрятала бы поломку
    маршрута до первого INFO.
    """
    manager.error("ошибка в никуда", module="unit")

    stats = manager.get_stats()
    assert stats["unresolved_channel_records"] >= 1, "сломанный маршрут обязан быть виден"
    assert stats["errors_to_floor"] >= 1, "запись обязана быть подхвачена полом"

    floor_path = Path(stats["error_floor"]["path"])
    assert floor_path.exists() and floor_path.stat().st_size > 0


# =============================================================================
# 5. reconfigure не стирает историю потерь
# =============================================================================


@pytest.mark.parametrize("manager", [False], indirect=True)
def test_reconfigure_does_not_erase_loss_history(manager, tmp_path: Path) -> None:
    """Hot-reload чинит маршрут, но не имеет права отмыть статистику потерь.

    Обратное поведение опаснее, чем кажется: оператор, увидев потери, правит
    конфиг — и ровно тем же действием стирает улику, по которой потери можно
    было бы связать с периодом до правки.
    """
    for i in range(3):
        manager.info(f"до reconfigure {i}", module="unit")
    before = manager.get_stats()["unresolved_channel_records"]
    assert before == 3

    fixed = _config(tmp_path, enable_batching=False, scope_channels=["system_file"])
    manager.reconfigure(fixed.to_dict() if hasattr(fixed, "to_dict") else fixed.model_dump())

    manager.info("после reconfigure — маршрут исправен", module="unit")

    after = manager.get_stats()
    assert after["unresolved_channel_records"] == before, "история потерь стёрта reconfigure'ом"
    assert after["unresolved_channels"] == {"ghost": 3}


# =============================================================================
# 6. Учёт исключения канала не зависит от пути доставки
# =============================================================================


class _RaisingChannel(LogChannel):
    def __init__(self, name: str) -> None:
        super().__init__(LoggerChannelSchema(name=name, type="console", enabled=True))

    def write(self, record: Dict[str, Any]) -> Dict[str, Any]:
        raise RuntimeError("канал сломан")


@pytest.mark.parametrize("batching", [True, False])
def test_write_exception_counted_on_both_paths(tmp_path: Path, batching: bool) -> None:
    """Исключение из ``write()`` считается и на батчевом, и на прямом пути.

    Батчевый путь исполняется в другом потоке (таймер/явный flush) и в другом
    методе — легко починить один и забыть второй.
    """
    mgr = LoggerManager(
        manager_name=f"RaiseLogger{batching}",
        config=_config(tmp_path, enable_batching=batching, scope_channels=["system_file"]),
    )
    try:
        mgr._channel_registry.unregister("system_file")
        mgr._channel_registry.register(_RaisingChannel("system_file"))

        for i in range(3):
            mgr.info(f"запись {i}", module="unit")
        mgr.flush()

        stats = mgr.get_stats()
        assert stats["channel_write_errors"] == 3
        assert stats["channel_write_errors_by_channel"] == {"system_file": 3}
        # Нерезолвящихся каналов здесь нет — счётчики не должны путаться между собой.
        assert stats["unresolved_channel_records"] == 0
    finally:
        mgr.shutdown()
