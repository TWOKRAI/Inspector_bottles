# -*- coding: utf-8 -*-
"""Ф0.5 — внутренние опасности двухслойного контекста (АВТОРСКИЕ тесты).

Изоляцию между потоками и тасками проверяет независимый тестировщик
(``test_context_isolation.py``). Здесь — то, что видно только автору правки:
последствия того, ЧЕМ именно сделана изоляция.

Реализация: один модульный ``ContextVar`` со словарём «ключ менеджера → стек»,
плюс отдельный процессный слой ``_base_context`` под локом. Отсюда опасности:

  1. Ключ менеджера. Если бы им был ``id(self)``, менеджер, созданный после
     сборки мусора предыдущего, унаследовал бы его контекст в том потоке,
     который не сделал ``pop``. Два менеджера обязаны быть изолированы.
  2. Общий словарь. Значение ``ContextVar`` обязано пересоздаваться целиком:
     мутация на месте видна всем потокам сразу и возвращает ровно ту утечку,
     ради которой всё затевалось.
  3. Процессная база — общее изменяемое состояние, к ней ходят из всех потоков
     на КАЖДОЙ записи. Гонка чтения во время записи не должна давать рваный
     словарь.
  4. Пул потоков переиспользует поток. ``push_context`` без ``pop_context``
     переживает конец задачи и достаётся следующей — это свойство ContextVar,
     и оно должно быть зафиксировано явно, а не обнаружено в проде.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any, Dict, List

from multiprocess_framework.modules.logger_module.core.log_config import (
    LoggerChannelSchema,
    LoggerManagerConfig,
    LoggerScopeSchema,
)
from multiprocess_framework.modules.logger_module.core.logger_manager import LoggerManager


class _Capture:
    """Приёмник-tap: складывает записи в список."""

    name = "capture"

    def __init__(self) -> None:
        self.records: List[Dict[str, Any]] = []

    def write(self, record: Dict[str, Any]) -> Dict[str, Any]:
        self.records.append(record)
        return {"status": "success"}

    def close(self) -> None:
        return None


def _manager(tmp_path: Path, name: str) -> LoggerManager:
    return LoggerManager(
        manager_name=name,
        config=LoggerManagerConfig(
            app_name="ctx_hazards",
            log_directory=str(tmp_path / name),
            enable_batching=False,
            modules={},
            channels={
                "console": LoggerChannelSchema(name="console", type="console", enabled=False),
            },
            scopes={
                "SYSTEM": LoggerScopeSchema(enabled=True, min_level="DEBUG", channels=["console"]),
                "BUSINESS": LoggerScopeSchema(enabled=True, min_level="DEBUG", channels=["console"]),
            },
        ),
    )


def _extras(cap: _Capture, module: str) -> List[Dict[str, Any]]:
    """Только записи нашего модуля: менеджеры пишут и свои внутренние."""
    return [r["extra"] for r in cap.records if r.get("module") == module]


# =============================================================================
# 1. Два менеджера в одном потоке не видят контекст друг друга
# =============================================================================


def test_two_managers_do_not_share_context_in_one_thread(tmp_path: Path) -> None:
    """Ключ контекста — на инстанс, а не на класс и не на поток.

    Иначе ``ErrorManager`` и ``LoggerManager`` одного процесса перемешали бы
    контексты: оба живут в одном потоке и оба наследуют ``LoggerCore``.
    """
    a, b = _manager(tmp_path, "A"), _manager(tmp_path, "B")
    cap_a, cap_b = _Capture(), _Capture()
    a.add_tap(cap_a, min_level="DEBUG", name="cap_a")
    b.add_tap(cap_b, min_level="DEBUG", name="cap_b")
    try:
        a.push_context(who="менеджер_A")
        b.push_context(who="менеджер_B")

        a.info("запись A", module="unit")
        b.info("запись B", module="unit")

        assert _extras(cap_a, "unit")[-1]["who"] == "менеджер_A"
        assert _extras(cap_b, "unit")[-1]["who"] == "менеджер_B"
    finally:
        a.shutdown()
        b.shutdown()


def test_pop_on_one_manager_does_not_touch_the_other(tmp_path: Path) -> None:
    a, b = _manager(tmp_path, "A2"), _manager(tmp_path, "B2")
    cap_b = _Capture()
    b.add_tap(cap_b, min_level="DEBUG", name="cap_b2")
    try:
        a.push_context(who="A")
        b.push_context(who="B")
        a.pop_context()

        b.info("после чужого pop", module="unit")
        assert _extras(cap_b, "unit")[-1]["who"] == "B"
    finally:
        a.shutdown()
        b.shutdown()


# =============================================================================
# 2. Процессная база: гонка чтения и записи
# =============================================================================


def test_base_context_survives_concurrent_writes_and_reads(tmp_path: Path) -> None:
    """База меняется из одного потока, читается из восьми на каждой записи.

    Проверяется не значение, а целостность: ни одна запись не должна получить
    полуприменённую базу (часть ключей от старого состояния, часть от нового)
    и ни один поток не должен упасть на изменившемся во время итерации словаре.
    """
    mgr = _manager(tmp_path, "Race")
    cap = _Capture()
    mgr.add_tap(cap, min_level="DEBUG", name="cap_race")
    try:
        mgr.set_base_context(proc_name="p", generation=0)
        stop = threading.Event()
        errors: List[BaseException] = []

        def writer() -> None:
            gen = 0
            while not stop.is_set():
                gen += 1
                mgr.set_base_context(generation=gen)

        def reader() -> None:
            try:
                for _ in range(500):
                    mgr.info("гонка", module="unit")
            except BaseException as exc:  # noqa: BLE001 — тест ловит любой отказ
                errors.append(exc)

        w = threading.Thread(target=writer, daemon=True)
        readers = [threading.Thread(target=reader) for _ in range(8)]
        w.start()
        for t in readers:
            t.start()
        for t in readers:
            t.join()
        stop.set()
        w.join(timeout=2)

        assert not errors, f"чтение базы упало: {errors[:1]}"
        extras = _extras(cap, "unit")
        assert len(extras) == 8 * 500
        # proc_name не менялся ни разу — он обязан быть в КАЖДОЙ записи.
        assert all(e.get("proc_name") == "p" for e in extras), "база рвалась при записи"
    finally:
        mgr.shutdown()


def test_clear_base_context_removes_all_fields(tmp_path: Path) -> None:
    mgr = _manager(tmp_path, "Clear")
    cap = _Capture()
    mgr.add_tap(cap, min_level="DEBUG", name="cap_clear")
    try:
        mgr.set_base_context(proc_name="p", extra_field="x")
        mgr.info("до очистки", module="unit")
        mgr.clear_base_context()
        mgr.info("после очистки", module="unit")

        extras = _extras(cap, "unit")
        assert extras[-2].get("proc_name") == "p"
        assert "proc_name" not in extras[-1]
        assert "extra_field" not in extras[-1]
    finally:
        mgr.shutdown()


def test_set_base_context_merges_not_replaces(tmp_path: Path) -> None:
    """Второй вызов не должен стирать поля первого — иначе владелец второго
    вызова молча отбирает контекст у владельца первого."""
    mgr = _manager(tmp_path, "Merge")
    cap = _Capture()
    mgr.add_tap(cap, min_level="DEBUG", name="cap_merge")
    try:
        mgr.set_base_context(proc_name="p")
        mgr.set_base_context(app="inspector")
        mgr.info("оба поля", module="unit")

        last = _extras(cap, "unit")[-1]
        assert last.get("proc_name") == "p"
        assert last.get("app") == "inspector"
    finally:
        mgr.shutdown()


# =============================================================================
# 3. Поток переиспользуется: незакрытый push переживает задачу
# =============================================================================


def test_unpopped_context_persists_on_a_reused_thread(tmp_path: Path) -> None:
    """ЗАФИКСИРОВАНО КАК СВОЙСТВО, а не как желаемое поведение.

    Контекст живёт в ``ContextVar``, то есть привязан к потоку/таску, а не к
    «задаче». Пул потоков переиспользует поток, поэтому ``push_context`` без
    парного ``pop_context`` достаётся следующей задаче на том же потоке.

    Это цена выбранного механизма, и она должна быть записана: код, кладущий
    контекст на время работы, обязан снимать его в ``finally``. Если однажды
    появится автоматическая очистка на границе задачи, этот тест покраснеет —
    и это будет правильный сигнал «поведение сменилось намеренно».
    """
    mgr = _manager(tmp_path, "Reused")
    cap = _Capture()
    mgr.add_tap(cap, min_level="DEBUG", name="cap_reused")
    try:
        results: List[Any] = []

        def task_one() -> None:
            mgr.push_context(task="первая")  # намеренно без pop
            mgr.info("работа первой задачи", module="unit")

        def task_two() -> None:
            mgr.info("работа второй задачи", module="unit")
            results.append(_extras(cap, "unit")[-1].get("task"))

        worker = threading.Thread(target=lambda: (task_one(), task_two()))
        worker.start()
        worker.join()

        assert results == ["первая"], (
            "ожидается ПРОТЕЧКА в рамках одного потока — контекст привязан к потоку, "
            "а не к задаче; снимать обязан тот, кто положил"
        )
    finally:
        mgr.shutdown()


# =============================================================================
# 4. Новый менеджер не наследует контекст предыдущего в том же потоке
# =============================================================================


def test_fresh_manager_starts_with_empty_context(tmp_path: Path) -> None:
    """Ключ инстанса выдаётся счётчиком, а не ``id(self)``.

    С ``id(self)`` менеджер, созданный на месте освобождённого, подхватил бы
    его непогашенный контекст — запись получила бы поля от покойника.
    """
    first = _manager(tmp_path, "First")
    first.push_context(ghost="контекст_покойника")
    first.shutdown()
    del first

    second = _manager(tmp_path, "Second")
    cap = _Capture()
    second.add_tap(cap, min_level="DEBUG", name="cap_second")
    try:
        second.info("чистый старт", module="unit")
        assert "ghost" not in _extras(cap, "unit")[-1]
    finally:
        second.shutdown()
