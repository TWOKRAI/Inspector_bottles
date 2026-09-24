# -*- coding: utf-8 -*-
"""Live acceptance-тест Task 1.1 (`plans/lifecycle-stop-ownership.md`).

Контракт (CTO): любой стоп всей системы — окно GUI, `harness.stop()`, команда
`system.shutdown` (backend_ctl, будущий Пульт) — должен идти ОДНИМ путём, общим
системным стоп-событием, чтобы дети останавливались параллельно и хук выхода
КАЖДОГО ребёнка знал, что это системный стоп.

Факт до правки: `_cmd_system_shutdown` взводил только `self.stop_event` — не общий
системный путь. Живьём (CTO, 8853-8855): 5.83 / 1.39 / 1.28 с, в первом прогоне
`Process 'renderer' did not stop in 5.0s, terminating...` при PM exitcode 0. После
правки — 0.68–0.71 с в 10 из 10.

Наблюдаемое для критерия 2 (замерено этим тестом на текущем дереве ДО правки, без
чтения кода `process_manager_module`): единственное найденное отличие хука выхода
между заведомо системным путём (`harness.stop()`) и командой `system.shutdown` до правки —
суффикс `(system-wide)` у строки `"<name>: Stop signal received"` в
`<log_dir>/<name>/messages.log` каждого ребёнка. На пути `harness.stop()` суффикс
есть у всех 6 детей; на пути `system.shutdown` до правки не было ни у одного. Никакого
признака `system_stop` ни в stdout/stderr, ни в `observability.db` сегодня нет
вовсе — проверено (`sqlite3 ... LIKE '%stop%'` — 0 строк, `grep -r system_stop
logs/` — 0 строк). Строку итога хука `"queues released to gone readers: N,
buffered dropped: 0"` сознательно НЕ используем как признак — она зависит от
порядка выхода процессов (кто раньше отпустил очередь), а не от режима стопа, и
задача 1.3 планирует убрать её при `buffered dropped == 0`.

Собственный диапазон портов 8860-8869 (8850-8859 и 8765/8766 заняты другими живыми
стендами — см. `TASK: 1.1`).
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Dict, List, Optional

import pytest

from backend_ctl.harness import BackendHarness

_PORT_BASE = 8860
_RECIPE = "multiprocess_prototype/backend/topology/inspection_full.yaml"
_CHILDREN = ("camera_0", "processor", "renderer", "inspector", "storage", "gui")
_STOP_DEADLINE_S = 10.0
_SYSTEM_WIDE_MARKER = "Stop signal received (system-wide)"


def _wait_pm_exit(pm_process, deadline_s: float) -> Optional[int]:
    """Ждёт выхода PM-процесса с ограниченным дедлайном (не виснет)."""
    pm_process.join(timeout=deadline_s)
    return pm_process.exitcode


def _read_children_logs(log_dir: Path) -> Dict[str, str]:
    """Содержимое ``messages.log`` каждого ребёнка (пусто, если файла ещё нет)."""
    result: Dict[str, str] = {}
    for name in _CHILDREN:
        path = log_dir / name / "messages.log"
        result[name] = path.read_text(encoding="utf-8") if path.exists() else ""
    return result


@pytest.mark.harness_smoke
def test_system_shutdown_command_stops_tree_under_two_seconds(capfd, tmp_path) -> None:
    """10 независимых прогонов: `system.shutdown` через `BackendDriver.system_command`
    укладывается в 2.0s от отправки команды до выхода PM, без строки "did not stop in"
    (ни у спавнера в pytest-процессе, ни у PM в его собственном stderr — оба видит
    `capfd`, т.к. дочерний OS-процесс наследует файловые дескрипторы), PM exitcode 0.

    Ответ на команду обязан дойти: PM отвечает до выхода (замер ревью: 10/10 за
    0.014–0.026 с), обрыв канала — дефект, а не норма.
    """
    elapsed_times: List[float] = []
    for i in range(10):
        log_dir = tmp_path / f"run_{i}"
        harness = BackendHarness(recipe=_RECIPE, port=_PORT_BASE + i, warmup=1.0, log_dir=log_dir)
        try:
            capfd.readouterr()  # слить хвост предыдущего прогона
            drv = harness.start()
            # Дать пайплайну прогнать кадры по всем процессам — лёгкий трафик дефект
            # не воспроизводит (см. `test_graceful_stop_live.py`).
            time.sleep(2.0)

            pm_process = None
            if harness._launcher is not None and harness._launcher._spawner is not None:
                pm_process = harness._launcher._spawner.get_process()
            assert pm_process is not None, f"run {i}: не удалось снять ссылку на PM-процесс до команды"

            start = time.monotonic()
            reply = drv.system_command({"cmd": "system.shutdown"}, timeout=10.0)
            assert reply.get("success") is True, f"run {i}: ответ на system.shutdown: {reply!r}"

            exitcode = _wait_pm_exit(pm_process, _STOP_DEADLINE_S)
            elapsed = time.monotonic() - start
            captured = capfd.readouterr()
            combined = captured.out + captured.err
            stuck_lines = [line for line in combined.splitlines() if "did not stop in" in line]

            elapsed_times.append(elapsed)
            assert elapsed < 2.0, f"run {i}: дерево не вышло за 2.0s ({elapsed:.3f}s); все прогоны: {elapsed_times}"
            assert not stuck_lines, f"run {i}: залогировано зависание (спавнер/PM): {stuck_lines}"
            assert exitcode == 0, f"run {i}: PM вышел с exitcode={exitcode} (не 0)"
        finally:
            harness.stop()

    print(f"[test_system_shutdown_command_stops_tree_under_two_seconds] elapsed per run: {elapsed_times}")


@pytest.mark.harness_smoke
def test_system_shutdown_children_exit_hook_in_system_stop_mode(tmp_path) -> None:
    """Хук выхода каждого ребёнка должен идти в режиме системного стопа независимо от
    того, какой путь его вызвал.

    Санитарная часть (обязательна первой): на заведомо системном пути —
    `harness.stop()` — суффикс `(system-wide)` должен быть у ВСЕХ 6 детей. Если его
    там нет, выбранный наблюдаемый признак ничего не отличает, и тест бессмыслен
    (см. докстринг модуля) — эта проверка защищает от такого ложного вывода.

    Проверяемая часть: на пути команды `system.shutdown` тот же суффикс должен быть
    у ВСЕХ 6 детей — до правки его не было ни у одного (команда взводила только
    приватный `stop_event` PM, а не общий системный стоп).

    PM обязан выйти САМ до ``harness.stop()``: тот в finally взводит системное событие,
    и маркер от него сделал бы тест зелёным впустую (замечание ревью).
    """
    sanity_log_dir = tmp_path / "sanity_harness_stop"
    sanity = BackendHarness(recipe=_RECIPE, port=_PORT_BASE + 9, warmup=1.0, log_dir=sanity_log_dir)
    try:
        sanity.start()
        time.sleep(2.0)
    finally:
        sanity.stop()

    sanity_texts = _read_children_logs(sanity_log_dir)
    missing_on_sanity = [name for name, text in sanity_texts.items() if _SYSTEM_WIDE_MARKER not in text]
    assert not missing_on_sanity, (
        f"санитарная проверка провалена: harness.stop() не даёт суффикс '(system-wide)' "
        f"для {missing_on_sanity} — выбранный наблюдаемый признак ничего не отличает, "
        "нужен другой (см. докстринг модуля)"
    )

    shutdown_log_dir = tmp_path / "system_shutdown"
    harness = BackendHarness(recipe=_RECIPE, port=_PORT_BASE + 8, warmup=1.0, log_dir=shutdown_log_dir)
    try:
        drv = harness.start()
        time.sleep(2.0)
        pm_process = None
        if harness._launcher is not None and harness._launcher._spawner is not None:
            pm_process = harness._launcher._spawner.get_process()
        assert pm_process is not None, "не удалось снять ссылку на PM-процесс до команды"

        drv.system_command({"cmd": "system.shutdown"}, timeout=10.0)
        exitcode = _wait_pm_exit(pm_process, _STOP_DEADLINE_S)
        assert exitcode is not None, f"PM не вышел сам за {_STOP_DEADLINE_S}s после system.shutdown"
    finally:
        harness.stop()

    shutdown_texts = _read_children_logs(shutdown_log_dir)
    missing_on_shutdown = [name for name, text in shutdown_texts.items() if _SYSTEM_WIDE_MARKER not in text]
    assert not missing_on_shutdown, (
        f"хук выхода без суффикса '(system-wide)' у {missing_on_shutdown} на пути "
        "system.shutdown — команда не взводит общий системный стоп "
        "(см. Task 1.1, plans/lifecycle-stop-ownership.md)"
    )
