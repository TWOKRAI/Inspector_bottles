# -*- coding: utf-8 -*-
"""Host-скрипт для acceptance-тестов Task 1.5 (`lifecycle-stop-ownership`):
«ребёнок, созданный ProcessManager'ом, не переживает его».

Не production-код (тестовая утилита, не dev/module-contract) — запускается КАК
РЕАЛЬНЫЙ ОТДЕЛЬНЫЙ OS-процесс через ``python -m <этот модуль> <сценарий>`` и играет
роль «родителя» (заместителя ProcessManager): строит ``ProcessRegistry``,
создаёт+стартует ребёнка (``QuickChild``/``HungChild`` — ИМПОРТИРУЮТСЯ из
``_no_orphans_helpers``, не дублируются), печатает JSON-строку(и) с pid'ами в
stdout и застывает — тест сам решает, когда и как его убить (SIGKILL).

Каждая JSON-строка флашится сразу (``flush=True``), чтобы тест мог прочитать её
без буферизации. ``python -m`` (а не путь к файлу) — тот же приём, что и в
``test_no_orphans_acceptance.py::_SIGINT_MAIN_SCRIPT``: spawn-контекст
переимпортирует модуль по dotted-path, а не переисполняет ``__main__``.

Сценарии (argv[1]):
    single_quick    — один QuickChild, печать {"child": pid}, затем сон.
    single_hung     — один HungChild, печать {"child": pid}, затем сон.
    boot_race       — один HungChild, печать pid СРАЗУ после start() (без окна
                      settle) — родителя убивают, пока ребёнок мог не успеть
                      initialize().
    alive_pair      — два QuickChild "a"/"b", печать {"a": pid, "b": pid}, хост
                      остаётся жив (для проверки «родитель жив → дети живут»).
    thread_child    — короткоживущий поток создаёт+стартует QuickChild "t" и
                      завершается; печать {"child": pid, "thread_done": true}
                      ПОСЛЕ join() потока, хост остаётся жив.
    restarted_child — создать+стартовать "r", напечатать {"child": pid,
                      "phase": "first"}; остановить/снять/пересоздать под тем
                      же именем; напечатать {"child": pid, "phase": "second"};
                      хост остаётся жив.
"""

from __future__ import annotations

import json
import sys
import threading
import time

from multiprocess_framework.modules.process_manager_module.core.process_registry import (
    ProcessRegistry,
)
from multiprocess_framework.modules.process_manager_module.tests._no_orphans_helpers import (
    HUNG_CHILD_CLASS_PATH,
    QUICK_CHILD_CLASS_PATH,
)

# Хост переживает любой разумный дедлайн теста — умирает только от SIGKILL теста,
# никогда сам (иначе гонка «сам вышел vs тест успел прочитать/убить»).
_SLEEP_S = 600.0


def _emit(obj: dict) -> None:
    print(json.dumps(obj), flush=True)


def _make_registry() -> ProcessRegistry:
    # Минимальный конструктор (см. test_process_registry.py::test_create_and_register_
    # provides_ready_event) — без queue_registry/shared_resources create_and_register
    # всё равно строит рабочий multiprocessing.Process.
    return ProcessRegistry(logger=None)


def _start_child(registry: ProcessRegistry, name: str, class_path: str):
    process = registry.create_and_register(name, class_path, {}, "normal")
    assert process is not None, f"create_and_register('{name}') вернул None — окружение сломано"
    process.start()
    return process


def run_single(class_path: str) -> None:
    registry = _make_registry()
    process = _start_child(registry, "child", class_path)
    _emit({"child": process.pid})
    time.sleep(_SLEEP_S)


def run_boot_race() -> None:
    registry = _make_registry()
    process = registry.create_and_register("child", HUNG_CHILD_CLASS_PATH, {}, "normal")
    assert process is not None
    process.start()
    # Никакого settle-окна: печатаем pid МГНОВЕННО — тест убивает нас сразу по чтению.
    _emit({"child": process.pid})
    time.sleep(_SLEEP_S)


def run_alive_pair() -> None:
    registry = _make_registry()
    a = _start_child(registry, "a", QUICK_CHILD_CLASS_PATH)
    b = _start_child(registry, "b", QUICK_CHILD_CLASS_PATH)
    _emit({"a": a.pid, "b": b.pid})
    time.sleep(_SLEEP_S)


def run_thread_child() -> None:
    registry = _make_registry()
    holder: dict = {}

    def _spawn() -> None:
        process = _start_child(registry, "t", QUICK_CHILD_CLASS_PATH)
        holder["pid"] = process.pid

    t = threading.Thread(target=_spawn)
    t.start()
    t.join(timeout=30.0)
    if t.is_alive():
        _emit({"error": "spawn thread did not finish in 30s"})
        return
    # thread_done печатается ПОСЛЕ join() — поток уже мёртв к моменту, когда тест
    # читает эту строку (это и есть проверяемое свойство C4).
    _emit({"child": holder.get("pid"), "thread_done": True})
    time.sleep(_SLEEP_S)


def run_restarted_child() -> None:
    registry = _make_registry()
    first = _start_child(registry, "r", QUICK_CHILD_CLASS_PATH)
    _emit({"child": first.pid, "phase": "first"})
    registry.stop_one("r", timeout=5.0)
    registry.remove_process("r")
    second = _start_child(registry, "r", QUICK_CHILD_CLASS_PATH)
    _emit({"child": second.pid, "phase": "second"})
    time.sleep(_SLEEP_S)


_SCENARIOS = {
    "single_quick": lambda: run_single(QUICK_CHILD_CLASS_PATH),
    "single_hung": lambda: run_single(HUNG_CHILD_CLASS_PATH),
    "boot_race": run_boot_race,
    "alive_pair": run_alive_pair,
    "thread_child": run_thread_child,
    "restarted_child": run_restarted_child,
}


def _main() -> None:
    if len(sys.argv) != 2 or sys.argv[1] not in _SCENARIOS:
        print(f"usage: python -m ... <{'|'.join(_SCENARIOS)}>", file=sys.stderr)
        sys.exit(2)
    _SCENARIOS[sys.argv[1]]()


if __name__ == "__main__":
    # spawn-контекст перечитывает модуль в каждом дочернем интерпретаторе по
    # dotted-path (``python -m``), а не как ``__main__`` — этот guard не выполняется
    # повторно у детей (в отличие от запуска голым путём к файлу).
    _main()
