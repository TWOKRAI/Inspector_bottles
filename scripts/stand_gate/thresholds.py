"""Пороги стенд-гейта фазы 5 — ЛИТЕРАЛЫ из Task 5.6 (`plans/transport-single-policy/phase-5.md`, OWNER-8).

Все пороги — в единицах (Σ ``count``), не в строках журнала. Менять число здесь = менять приёмку:
правка идёт через план, а не через этот файл.
"""

from __future__ import annotations

#: Процессы под ``extras.overflow: every`` в профиле quick (решение лида 2026-10-03). JSON стенда
#: этого не сообщает: верхний ``overflow`` один на кейс.
EVERY_PROCESSES: tuple[str, ...] = ("processor", "inspector")

#: Процессы, у которых проверяется формула ``born(P) − drops(P) == 0`` на ``s2``.
FORMULA_PROCESSES: tuple[str, ...] = ("processor", "inspector")

#: Соседи processor: ``handled(N) − own_in(N) − born(processor) == 0`` на ``s2``.
NEIGHBOR_PROCESSES: tuple[str, ...] = ("inspector", "renderer")

#: Учёт решателя: ``0 ≤ (I + N) − F ≤ 0.005 × F``.
LEDGER_LOWER: int = 0
LEDGER_UPPER_FRACTION: float = 0.005

#: Дублей ``trace_id`` в журнале (``messages.log``).
JOURNAL_DUP_MAX: int = 0

#: ``Σ_P Σ_workers not_inspected_stale_restore ≤ 0.001 × F`` на ``s2`` (сумма по ВСЕМ процессам).
STALE_RESTORE_FRACTION: float = 0.001

#: Lag processor: ``Σ_workers lag_dropped_items ≤ 0.01 × F``; выключается ``--no-throughput-gate``.
PROCESSOR_LAG_FRACTION: float = 0.01

#: Кейс D100: ``V ≥ 0.9 × (F − N)``.
VERDICT_FLOOR_FRACTION: float = 0.9

#: Кейс D100, гейт 5.2: ``Σ_workers not_inspected_lag(inspector, s1) − то же на s0 ≤ 100``.
INSPECTOR_WINDOW_LAG_MAX: int = 100

#: Кейс P10, гейт 5.3: ``pause.rss1 − pause.rss0 ≤ 1 МиБ``.
PAUSE_RSS_GROWTH_MAX_BYTES: int = 1048576

#: Кейс P10: ``pause.drain_s ≤ 0.1``; при ``pause.drain_poll_period_s > 0.1`` — ``NOT_MEASURED``.
DRAIN_MAX_S: float = 0.1
DRAIN_POLL_PERIOD_MAX_S: float = 0.1

#: Старт (``s0``): ``rs.frame_stale_drops == 0`` у процессов под every.
START_STALE_DROPS_MAX: int = 0

#: Шаг опроса дренажа в живом прогоне (спека: ``≤ 20 мс``).
DRAIN_POLL_STEP_S: float = 0.02
