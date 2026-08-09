# -*- coding: utf-8 -*-
"""Живая приёмка B1 — ручка темпа стат-плоскости действует и читается честно.

Зачем живьём при зелёных тестах. Тесты доказали МЕХАНИКУ: окно пересобирается,
пол говорит вслух, readback читает живое окно. Этот прогон судит ПРОВОДКУ:
доезжает ли ``config.reload`` до ``StatsManager`` ребёнка через сокет, ПМ и
раскладку слоёв, и меняется ли при этом ФАКТИЧЕСКИЙ темп записи. Ровно на этом
стыке жил major-3: механика каждого звена выглядела рабочей, а живой замер
ревью дал 115 → 138 сбросов за 187 с при заявленных «30».

Проверки:

    T1  ``effective.stats`` в ``introspect.observability`` СУЩЕСТВУЕТ. До B1
        ветка сторожилась недостижимым ``getattr(stats, "config")`` и не
        исполнялась ни разу — плоскость не отдавала наружу ничего.
    T2  Флип 12 → 36 → 12: число сбросов окна за ФИКСИРОВАННОЕ окно меняется
        втрое в обе стороны. Числа — в отчёте.
    T3  ``config_reload_verified`` на этом ключе → ``confirmed`` (не
        ``unverifiable``), и ``effective`` совпадает с живым окном.
    T4  Пара к T3: запрос НИЖЕ пола → ``failed`` с обоими числами, и пол назван
        WARNING'ом с адресом ключа (решение Р-3б: пол остаётся, но не молчит).
    T5  Смена темпа не теряет записи: счётчики потерь плоскости не выросли,
        ``channel_written_records`` вырос.

Числа взяты ВНЕ дефолтов (5.0 / 10.0) и выше пола: на дефолтных числах тест
проверял бы дефолт, а не ручку, а значение ниже пола молча съелось бы им.

Замер идёт ``flush=False``. Это не мелочь: ``flush=True`` сам делает
``flush_all()`` окна и увеличивает ровно тот счётчик, который мы считаем, —
опрос стал бы источником измеряемого.

Запуск: ``python -m backend_ctl.probes.probe_b1_stats_tempo_live``
Стенд одиночный — порт 8765 не терпит двух. Прогон ~8 минут.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

os.environ["BACKEND_CTL"] = "1"

for _stream in (sys.stdout, sys.stderr):
    _reconfigure = getattr(_stream, "reconfigure", None)
    if callable(_reconfigure):
        _reconfigure(encoding="utf-8", errors="replace")

from backend_ctl.driver import _leaf_result  # noqa: E402
from backend_ctl.harness import BackendHarness  # noqa: E402

RECIPE = PROJECT_ROOT / "multiprocess_prototype" / "recipes" / "webcam_sketch.yaml"
CHILD = "camera_0"

#: Длина окна замера, сек. При темпе 12 с окно даёт ~10 сбросов, при 36 с — ~3:
#: разрыв достаточный, чтобы «втрое» не тонуло в одном пограничном такте.
WINDOW = 120.0

FAILURES: list = []


def log(msg: str) -> None:
    print(msg, flush=True)


def check(ok: bool, title: str, evidence: str) -> None:
    log(f"  [{'PASS' if ok else 'FAIL'}] {title}\n         {evidence}")
    if not ok:
        FAILURES.append(f"{title}: {evidence}")


def introspect(drv, *, flush: bool = False) -> Dict[str, Any]:
    args = {"flush": True} if flush else {}
    return _leaf_result(drv.send_command(CHILD, "introspect.observability", args, timeout=25.0)) or {}


def stats_buffer(snapshot: Dict[str, Any]) -> Dict[str, Any]:
    counters = snapshot.get("counters") or {}
    plane = counters.get("stats") or {}
    return plane.get("buffer") or {}


def stats_plane(snapshot: Dict[str, Any]) -> Dict[str, Any]:
    return (snapshot.get("counters") or {}).get("stats") or {}


def effective_stats(snapshot: Dict[str, Any]) -> Dict[str, Any]:
    return (snapshot.get("effective") or {}).get("stats") or {}


def flushes(drv) -> Optional[int]:
    """Число тактов окна агрегации. ``None`` — счётчика нет вовсе.

    «Счётчик не найден» обязано отличаться от «ноль сбросов»: слепота,
    прочитанная как ноль, дала бы ложный вывод в обе стороны (урок A1).
    """
    raw = stats_buffer(introspect(drv)).get("total_flushes")
    return None if raw is None else int(raw)


def set_tempo(drv, seconds: float) -> Dict[str, Any]:
    return drv.config_reload_verified(
        CHILD,
        observability={"stats": {"aggregation_interval": seconds}},
        settle=1.5,
        timeout=30.0,
    )


def measure(drv, title: str) -> Tuple[int, str]:
    """Дельта тактов окна за ФИКСИРОВАННОЕ время."""
    before = flushes(drv)
    if before is None:
        return -1, "счётчик total_flushes не найден в ответе"
    time.sleep(WINDOW)
    after = flushes(drv)
    if after is None:
        return -1, "счётчик total_flushes исчез между замерами"
    delta = after - before
    evidence = f"{title}: {before} → {after} за {WINDOW:.0f} с = {delta} сбросов"
    log(f"         {evidence}")
    return delta, evidence


# --------------------------------------------------------------------------


def t1_stats_plane_is_visible(drv) -> None:
    log("\n--- T1: effective.stats существует (до B1 ветка была недостижима) ---")
    section = effective_stats(introspect(drv))
    check(
        bool(section),
        "плоскость статистики отдаёт readback",
        f"effective.stats = {section}",
    )
    check(
        "aggregation_interval" in section and "flush_interval" in section,
        "в readback'е есть и действующий темп, и пол",
        f"ключи: {sorted(section)}",
    )


def t2_flip_changes_the_real_tempo(drv) -> None:
    log(f"\n--- T2: флип 12 → 36 → 12, окно замера {WINDOW:.0f} с ---")
    set_tempo(drv, 12.0)
    fast_1, ev_fast_1 = measure(drv, "темп 12 с (до)")

    set_tempo(drv, 36.0)
    slow, ev_slow = measure(drv, "темп 36 с")

    set_tempo(drv, 12.0)
    fast_2, ev_fast_2 = measure(drv, "темп 12 с (после)")

    # Допуск в один такт: окно замера не выровнено по границам тиков таймера.
    check(
        slow >= 0 and fast_1 >= 3 * slow - 1,
        "переход 12 → 36 срезал темп ВТРОЕ",
        f"{ev_fast_1}; {ev_slow}; отношение {fast_1 / slow if slow else float('inf'):.2f}",
    )
    check(
        slow >= 0 and fast_2 >= 3 * slow - 1,
        "обратный переход 36 → 12 вернул темп ВТРОЕ (пара, а не один случай)",
        f"{ev_slow}; {ev_fast_2}; отношение {fast_2 / slow if slow else float('inf'):.2f}",
    )


def t3_verdict_is_confirmed(drv) -> None:
    log("\n--- T3: вердикт на ключе темпа = confirmed, effective = живое окно ---")
    res = set_tempo(drv, 24.0)
    verdict = res.get("verdict")
    snapshot = introspect(drv)
    section = effective_stats(snapshot)
    window = stats_buffer(snapshot)
    check(
        verdict == "confirmed",
        "вердикт confirmed (не unverifiable)",
        f"verdict={verdict}, verified={res.get('verified')}",
    )
    check(
        section.get("aggregation_interval") == 24.0,
        "readback показывает запрошенный темп",
        f"effective.stats.aggregation_interval = {section.get('aggregation_interval')}",
    )
    check(
        window.get("flush_interval") == section.get("aggregation_interval"),
        "readback совпадает с ЖИВЫМ окном, а не с конфигом",
        f"окно = {window.get('flush_interval')}, readback = {section.get('aggregation_interval')}",
    )


def t4_floor_is_named_not_silent(drv) -> None:
    log("\n--- T4: запрос ниже пола → failed + WARNING с адресом ключа ---")
    drv.unwatch()
    time.sleep(1.0)
    drv.watch_like_gui(tail_level="WARNING")
    time.sleep(2.0)
    drv.observability_records(level="DEBUG")  # сбросить хвост, считать своё окно

    res = set_tempo(drv, 3.0)
    time.sleep(6.0)
    verdict = res.get("verdict")
    verified = res.get("verified") or {}
    mismatches = [m for m in (verified.get("mismatches") or []) if m.get("key") == "stats.aggregation_interval"]
    check(
        verdict == "failed" and bool(mismatches),
        "значение ниже пола НЕ засчитано успехом",
        f"verdict={verdict}, mismatches={mismatches}",
    )
    if mismatches:
        m = mismatches[0]
        check(
            m.get("expected") == 3.0 and m.get("actual") == 10.0,
            "в расхождении оба числа: запрошенное и действующее",
            f"expected={m.get('expected')}, actual={m.get('actual')}",
        )

    records = drv.observability_records(level="DEBUG")
    spoken = [r for r in records if "stats.aggregation_interval" in str(r.get("message", ""))]
    check(
        bool(spoken),
        "пол назван вслух WARNING'ом с адресом ключа",
        f"записей с адресом ключа: {len(spoken)}; пример: {spoken[0].get('message') if spoken else '—'}",
    )
    set_tempo(drv, 12.0)


def t5_tempo_change_loses_nothing(drv, before: Dict[str, Any]) -> None:
    log("\n--- T5: смена темпа не потеряла записей ---")
    after = stats_plane(introspect(drv, flush=True))
    loss_keys = (
        "unresolved_channel_records",
        "channel_write_errors",
        "channel_refused_records",
        "records_without_channels",
    )
    grew = {k: (before.get(k, 0), after.get(k, 0)) for k in loss_keys if after.get(k, 0) != before.get(k, 0)}
    check(
        not grew,
        "ни один класс потерь стат-плоскости не вырос за все флипы",
        f"до={{{', '.join(f'{k}={before.get(k, 0)}' for k in loss_keys)}}}, выросли: {grew or 'ни один'}",
    )
    written_before = int(before.get("channel_written_records", 0) or 0)
    written_after = int(after.get("channel_written_records", 0) or 0)
    check(
        written_after > written_before,
        "записи ПРОДОЛЖАЛИ доезжать (счётчик доставки вырос)",
        f"channel_written_records: {written_before} → {written_after}",
    )


def main() -> int:
    log("=" * 78)
    log("Живая приёмка B1 — стенд webcam_sketch, темп стат-плоскости")
    log("=" * 78)

    harness = BackendHarness(recipe=RECIPE, warmup=8.0)
    drv = harness.start()
    try:
        baseline = stats_plane(introspect(drv, flush=True))
        log(f"\nсчётчики стат-плоскости на входе: { {k: v for k, v in baseline.items() if k != 'buffer'} }")

        t1_stats_plane_is_visible(drv)
        t2_flip_changes_the_real_tempo(drv)
        t3_verdict_is_confirmed(drv)
        t4_floor_is_named_not_silent(drv)
        t5_tempo_change_loses_nothing(drv, baseline)
    finally:
        harness.stop()

    log("\n" + "=" * 78)
    if FAILURES:
        log(f"ПРОВАЛЕНО проверок: {len(FAILURES)}")
        for f in FAILURES:
            log(f"  - {f}")
        return 1
    log("ВСЕ ПРОВЕРКИ ПРОЙДЕНЫ")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
