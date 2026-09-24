# -*- coding: utf-8 -*-
"""Live acceptance-тест Task 1.1 (`plans/lifecycle-graceful-stop.md`), Property C.

Полный стенд (``inspection_full``, 7 процессов) должен останавливаться за < 2.0s
за прогон — вне зависимости от объёма трафика по очередям. Сегодня PM висит
в ``queues._finalize_join`` (мёртвый/задушенный читатель очереди), спавнер
бьёт ``join(5.0)`` и добивает вручную — ``stop()`` занимает ~5.5s, и
``ProcessSpawner.stop()`` логирует "did not stop in ...s, terminating...".

Собственный диапазон портов 8850-8852 (изоляция «нескольких бэкендов» — см.
докстринг ``BackendHarness``; 8765/8766 заняты другими живыми стендами).
"""

from __future__ import annotations

import time

import pytest

from backend_ctl.harness import BackendHarness

_PORT_BASE = 8850

# CLI-запуск рецепта (см. шапку самого yaml) идёт БЕЗ подмешивания base.yaml —
# inspection_full не объявляет зависимость на "devices" (камера — симулятор).
_RECIPE = "multiprocess_prototype/backend/topology/inspection_full.yaml"


@pytest.mark.harness_smoke
def test_harness_stop_is_under_two_seconds(capsys) -> None:
    """10 независимых прогонов: ``harness.stop()`` укладывается в 2.0s, без "did not stop in",
    И оркестратор (PM) выходит с exitcode 0 (не убит spawner'ом после зависшего join(5.0)).

    Строка-маркер зависания (``ProcessSpawner.stop()``) идёт через
    ``StdLoggerFacade``/каналы наблюдаемости в stderr того же pytest-процесса
    (spawner живёт в родителе, не в дочернем OS-процессе) — снимается
    ``capsys``, не ``caplog`` (замерено: строка НЕ доезжает до
    ``logging.getLogger("mpf.spawner")`` через хендлер, который видит caplog).

    Exitcode PM берётся через приватные атрибуты ``BackendHarness._launcher._spawner``
    (``ProcessSpawner.get_process()`` отдаёт живой ``multiprocessing.Process``) —
    публичного акцессора у ``BackendHarness`` для этого нет; ``harness.stop()``
    обнуляет ``self._launcher``, поэтому ссылку на процесс нужно снять ДО stop().
    """
    elapsed_times: list[float] = []
    for i in range(10):
        harness = BackendHarness(recipe=_RECIPE, port=_PORT_BASE + i, warmup=1.0)
        capsys.readouterr()  # слить хвост предыдущего прогона
        harness.start()
        # Дать пайплайну прогнать кадры по всем 7 процессам, чтобы очереди
        # накопили реальный трафик (лёгкий рецепт дефект не воспроизводит).
        time.sleep(2.0)

        pm_process = None
        if harness._launcher is not None and harness._launcher._spawner is not None:
            pm_process = harness._launcher._spawner.get_process()

        start = time.monotonic()
        harness.stop()
        elapsed = time.monotonic() - start
        captured = capsys.readouterr()

        elapsed_times.append(elapsed)
        stuck_lines = [line for line in (captured.out + captured.err).splitlines() if "did not stop in" in line]

        assert elapsed < 2.0, f"run {i}: stop() занял {elapsed:.3f}s (>= 2.0s); все прогоны: {elapsed_times}"
        assert not stuck_lines, f"run {i}: launcher залогировал зависание: {stuck_lines}"
        assert pm_process is not None, f"run {i}: не удалось снять ссылку на PM-процесс до stop()"
        assert pm_process.exitcode == 0, (
            f"run {i}: PM вышел с exitcode={pm_process.exitcode} (не 0) — "
            "штатный graceful stop не мог его добить сам, добил spawner (terminate/kill)"
        )

    print(f"[test_harness_stop_is_under_two_seconds] elapsed per run: {elapsed_times}")
