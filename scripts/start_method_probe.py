"""Замер способов старта процессов: fork / forkserver / spawn (Атлас 0.8, часть 0.8b).

Зачем. Решение «какой метод запуска у дочерних процессов» принимает владелец по числам,
а не по ощущению: ``spawn`` заново импортирует модули в каждом ребёнке (дороже по времени
старта и памяти), ``fork`` копирует состояние родителя (дёшево, но небезопасно при живых
потоках родителя). Скрипт даёт два числа на метод: время «старт -> все дети готовы» и
USS (память, принадлежащая только этому процессу) ребёнка.

Что делает. Для каждого метода, доступного в этой ОС (иначе строка «недоступен»), 5 повторов:
родитель ДО старта детей импортирует тот же набор модулей, что и дети
(``multiprocess_framework.modules.process_manager_module``, ``numpy``, ``cv2``) — иначе
fork-дети тоже платили бы за импорт, и разница была бы занижена. Затем стартуют 4 ребёнка;
каждый импортирует набор, меряет свой USS (``psutil``), кладёт его в очередь и ставит
своё событие. Время — от первого ``start()`` до того, как выставлены все 4 события.
Замер USS входит во время ребёнка (порядок действий задан спекой 0.8a).

Печать: ОС, Python, число CPU, таблица «метод | медиана c | min-max c | медиана USS ребёнка, МБ».
Реальное приложение здесь не меряется: сравнение на ``examples/minimal_app`` — это длительность
CI-джоба examples-smoke под fork против spawn.

Запуск (в т.ч. на Orin, повтор замера на целевом железе)::

    python scripts/start_method_probe.py

Нужны ``numpy``, ``opencv-python``, ``psutil`` и сам пакет ``multiprocess_framework``
(скрипт добавляет корень репозитория в ``sys.path``). Падение метода не роняет весь замер.
"""

from __future__ import annotations

import importlib
import multiprocessing
import os
import platform
import statistics
import sys
import time
from pathlib import Path
from typing import Any

# Корень репозитория от места файла: скрипт запускают из любого каталога, а spawn-ребёнок
# заново исполняет этот модуль как __mp_main__ и тоже должен найти пакет.
_REPO_ROOT = str(Path(__file__).resolve().parents[1])
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

METHODS = ("fork", "forkserver", "spawn")
REPEATS = 5
CHILDREN = 4
READY_TIMEOUT_S = 120.0

# Одинаковый набор для родителя и детей: см. докстринг модуля.
IMPORT_SET = (
    "multiprocess_framework.modules.process_manager_module",
    "numpy",
    "cv2",
)


def _import_set() -> None:
    for name in IMPORT_SET:
        importlib.import_module(name)


def _child(uss_queue: Any, ready: Any) -> None:
    """Цель ребёнка: импорт набора, USS в очередь, событие готовности."""
    import psutil

    _import_set()
    uss_queue.put(psutil.Process().memory_full_info().uss)
    ready.set()


def _run_once(ctx: Any) -> tuple[float, list[int]]:
    """Один повтор: время «старт -> все готовы» и USS каждого ребёнка (байты)."""
    uss_queue = ctx.Queue()
    events = [ctx.Event() for _ in range(CHILDREN)]
    children = [ctx.Process(target=_child, args=(uss_queue, ev), daemon=True) for ev in events]
    t0 = time.perf_counter()
    try:
        for child in children:
            child.start()
        deadline = t0 + READY_TIMEOUT_S
        for ev in events:
            if not ev.wait(timeout=max(0.0, deadline - time.perf_counter())):
                raise TimeoutError(f"дети не сообщили готовность за {READY_TIMEOUT_S:.0f} с")
        elapsed = time.perf_counter() - t0
        uss = [uss_queue.get(timeout=10.0) for _ in range(CHILDREN)]
    finally:
        for child in children:
            if child.is_alive():
                child.join(timeout=5.0)
            if child.is_alive():
                child.terminate()
    return elapsed, uss


def measure(method: str) -> dict[str, Any]:
    """Замер одного метода: ``{"times": [...], "uss": [...]}`` или ``{"error": str}``."""
    ctx = multiprocessing.get_context(method)
    times: list[float] = []
    uss_all: list[int] = []
    try:
        for _ in range(REPEATS):
            elapsed, uss = _run_once(ctx)
            times.append(elapsed)
            uss_all.extend(uss)
    except Exception as exc:  # один метод не должен ронять замер остальных
        return {"error": f"{type(exc).__name__}: {exc}"}
    return {"times": times, "uss": uss_all}


def format_row(method: str, result: dict[str, Any] | None) -> str:
    if result is None:
        return f"{method:<11}| недоступен"
    if "error" in result:
        return f"{method:<11}| ошибка: {result['error']}"
    times = result["times"]
    median_s = f"{statistics.median(times):.3f}"
    span_s = f"{min(times):.3f}-{max(times):.3f}"
    uss_mb = f"{statistics.median(result['uss']) / (1024 * 1024):.1f}"
    return f"{method:<11}| {median_s:>10} | {span_s:<13}| {uss_mb:>10}"


def main() -> int:
    available = multiprocessing.get_all_start_methods()
    print(f"ОС: {platform.platform()}")
    print(f"Python: {sys.version.split()[0]} ({platform.python_implementation()})")
    print(f"CPU: {os.cpu_count()}")
    print(f"Повторов: {REPEATS}, детей на повтор: {CHILDREN}, умолчание ОС: {multiprocessing.get_start_method()}")
    print()

    # Родитель импортирует набор ДО замера — см. докстринг модуля.
    _import_set()

    print(f"{'метод':<11}| {'медиана, c':>10} | {'min-max, c':<13}| {'USS, МБ':>10}  (медиана USS ребёнка)")
    print("-" * 75)
    for method in METHODS:
        result = measure(method) if method in available else None
        print(format_row(method, result), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
