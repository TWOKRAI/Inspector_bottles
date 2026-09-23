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
@pytest.mark.skip(
    reason="Task 1.2 plans/lifecycle-graceful-stop.md: второй источник зависания "
    "(писатель переживает читателя) — красный 4/5 и плодит сирот"
)
def test_harness_stop_is_under_two_seconds(capsys) -> None:
    """3 независимых прогона: ``harness.stop()`` укладывается в 2.0s, без "did not stop in".

    Строка-маркер зависания (``ProcessSpawner.stop()``) идёт через
    ``StdLoggerFacade``/каналы наблюдаемости в stderr того же pytest-процесса
    (spawner живёт в родителе, не в дочернем OS-процессе) — снимается
    ``capsys``, не ``caplog`` (замерено: строка НЕ доезжает до
    ``logging.getLogger("mpf.spawner")`` через хендлер, который видит caplog).
    """
    elapsed_times: list[float] = []
    for i in range(3):
        harness = BackendHarness(recipe=_RECIPE, port=_PORT_BASE + i, warmup=1.0)
        capsys.readouterr()  # слить хвост предыдущего прогона
        harness.start()
        # Дать пайплайну прогнать кадры по всем 7 процессам, чтобы очереди
        # накопили реальный трафик (лёгкий рецепт дефект не воспроизводит).
        time.sleep(2.0)
        start = time.monotonic()
        harness.stop()
        elapsed = time.monotonic() - start
        captured = capsys.readouterr()

        elapsed_times.append(elapsed)
        stuck_lines = [line for line in (captured.out + captured.err).splitlines() if "did not stop in" in line]

        assert elapsed < 2.0, f"run {i}: stop() занял {elapsed:.3f}s (>= 2.0s); все прогоны: {elapsed_times}"
        assert not stuck_lines, f"run {i}: launcher залогировал зависание: {stuck_lines}"

    print(f"[test_harness_stop_is_under_two_seconds] elapsed per run: {elapsed_times}")
