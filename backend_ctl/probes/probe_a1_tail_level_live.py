# -*- coding: utf-8 -*-
"""Живая приёмка A1 — порог подписки доезжает до сервера и там применяется.

Зачем живьём при 7174 зелёных. Тесты доказали МЕХАНИКУ каждого звена; этот
прогон судит ПРОВОДКУ: доехал ли порог через реальный сокет, брокер, broadcast
и tap'ы восьми процессов. Ровно на этом стыке жил Б-1 — механика каждого звена
по отдельности выглядела рабочей.

Проверки:

    L1  подписка INFO → в плоскости logs НЕНУЛЕВОЕ число записей за окно.
        Живой контрпример из ревью: 40 минут подписки с INFO → 0 событий.
    L2  подписка ERROR → INFO-запись НЕ доезжает, ERROR-запись доезжает.
        Пара, а не один случай: «ничего не пришло» доказывало бы сломанный
        хвост так же хорошо, как работающий порог.
    L3  contract_violations на подписку = 0 (Б-1б: поле было незадекларировано).
    L4  readback брокера показывает действующий уровень намерения.
    L5  FW_CONTRACTS_STRICT=1: подписка ЖИВЁТ и доставляет (при незадекларированном
        поле strict-мидлварь дропала бы её молча). Второй стенд, свой процесс.

ВАЖНО про клиентский предохранитель. ``observability_records`` сам режет по
объявленному ``tail_level``. Читай с дефолтом — и L2 прошла бы даже при
неработающем сервере: отфильтровал бы клиент. Поэтому все чтения идут с
``level="DEBUG"``, то есть клиентский фильтр снят, и судится ровно то, что
реально приехало по проводу. Снимать в стенде все предохранители, кроме
проверяемого, — иначе неизвестно, который из них держит.

Запуск: ``python -m backend_ctl.probes.probe_a1_tail_level_live``
Стенд одиночный — порт 8765 не терпит двух. Прогон ~3 минуты.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

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

FAILURES: list[str] = []


def log(msg: str) -> None:
    print(msg, flush=True)


def check(ok: bool, title: str, evidence: str) -> None:
    log(f"  [{'PASS' if ok else 'FAIL'}] {title}\n         {evidence}")
    if not ok:
        FAILURES.append(f"{title}: {evidence}")


def provoke(drv, marker: str, level: str = "INFO") -> None:
    """Заставить процесс написать запись заданной важности с опознаваемым маркером.

    Провокация явная, а не ожидание фонового потока: молчащий источник дал бы
    ноль записей, и проверка стала бы вакуумной независимо от порога.

    Первая редакция пробы полагала, что ``health.report`` сам даёт ПАРУ
    INFO+ERROR (через ``state.report_error``). Живой прогон это опроверг:
    health-запись идёт на **WARNING**, а не ERROR, и при ERROR-подписке
    законно отсекается. Поэтому обе половины пары провоцируются явно —
    предположение о важности чужой записи проверено, а не унаследовано.
    """
    drv.send_command(
        CHILD,
        "health.report",
        {"message": marker, "level": level, "context": "probe_a1"},
        timeout=15.0,
    )


def drain(drv) -> list:
    """Все приехавшие записи БЕЗ клиентского severity-фильтра."""
    return drv.observability_records(level="DEBUG")


def with_marker(records: list, marker: str) -> list:
    return [r for r in records if marker in str(r.get("message", ""))]


def router_violations(drv, process: str) -> int:
    stats = _leaf_result(drv.send_command(process, "introspect.router_stats", {}, timeout=20.0)) or {}
    section = stats.get("router_stats") if isinstance(stats, dict) else None
    if isinstance(section, dict) and "contract_violations" in section:
        return int(section["contract_violations"] or 0)
    # Отсутствие счётчика — это НЕ «ноль нарушений», а отсутствие замера.
    # Первая редакция пробы искала его в трёх неверных секциях и получала -1;
    # молчащий детектор обязан отличаться от детектора, показавшего ноль.
    return -1


# --------------------------------------------------------------------------


def l1_info_subscription_delivers(drv) -> None:
    log("\n--- L1: подписка INFO → плоскость logs НЕ пуста ---")
    drv.watch_like_gui(tail_level="INFO")
    time.sleep(2.0)
    drain(drv)  # сбросить бутстрап-хвост, считать только своё окно

    marker = "A1-L1-INFO-marker"
    for _ in range(3):
        provoke(drv, marker)
        time.sleep(1.0)
    time.sleep(6.0)

    records = drain(drv)
    logs = [r for r in records if r.get("kind") == "log"]
    mine = with_marker(records, marker)
    info_mine = [r for r in mine if str(r.get("severity", "")).lower() == "info"]

    check(
        len(logs) > 0,
        "плоскость logs непуста за окно подписки",
        f"записей kind=log: {len(logs)}, всего приехало: {len(records)}",
    )
    check(
        len(info_mine) > 0,
        "INFO-запись с маркером доехала до подписчика",
        f"с маркером: {len(mine)}, из них severity=info: {len(info_mine)}",
    )


def l2_error_subscription_still_filters(drv) -> None:
    log("\n--- L2: подписка ERROR → INFO отсечён, ERROR проходит (ПАРА) ---")
    drv.unwatch()
    time.sleep(1.5)
    drv.watch_like_gui(tail_level="ERROR")
    time.sleep(2.0)
    drain(drv)

    low_marker = "A1-L2-LOW-marker"
    high_marker = "A1-L2-HIGH-marker"
    for _ in range(3):
        provoke(drv, low_marker, level="INFO")
        provoke(drv, high_marker, level="ERROR")
        time.sleep(1.0)
    time.sleep(6.0)

    records = drain(drv)
    low = with_marker(records, low_marker)
    high = with_marker(records, high_marker)
    low_below = [r for r in low if str(r.get("severity", "")).lower() in ("debug", "info")]
    high_ok = [r for r in high if str(r.get("severity", "")).lower() in ("error", "critical")]

    check(
        len(low_below) == 0,
        "порог всё ещё режет: INFO-записи НЕ приехали",
        f"INFO/DEBUG с низким маркером: {len(low_below)} (ожидалось 0); всего с ним: {len(low)}",
    )
    check(
        len(high_ok) > 0,
        "вторая половина пары: ERROR-запись приехала",
        f"ERROR/CRITICAL с высоким маркером: {len(high_ok)} (ожидалось >0)",
    )


def l3_no_contract_violations(drv, before: dict) -> None:
    log("\n--- L3: подписка не даёт contract_violations ---")
    for process in sorted(before):
        was = before[process]
        now = router_violations(drv, process)
        if was < 0 or now < 0:
            check(False, f"счётчик contract_violations читается ({process})", f"до={was}, после={now}")
            continue
        check(
            now == was,
            f"contract_violations не вырос за прогон ({process})",
            f"до={was}, после={now}, дельта={now - was}",
        )


def l4_broker_readback_shows_the_level(drv) -> None:
    log("\n--- L4: readback брокера показывает действующий уровень ---")
    snap = _leaf_result(drv.send_command("ProcessManager", "introspect.observability", {}, timeout=25.0)) or {}
    broker = (snap.get("broker") or {}) if isinstance(snap, dict) else {}
    subs = broker.get("subscribers") or []
    levels = {s.get("subscriber"): s.get("level") for s in subs if isinstance(s, dict)}
    check(
        any(v == "ERROR" for v in levels.values()),
        "уровень намерения виден в readback",
        f"подписчики → уровни: {levels}",
    )


def l5_strict_mode_keeps_the_subscription_alive() -> None:
    """Второй стенд со STRICT: незадекларированное поле дропало бы подписку молча."""
    log("\n--- L5: FW_CONTRACTS_STRICT=1 — подписка живёт и доставляет ---")
    os.environ["FW_CONTRACTS_STRICT"] = "1"
    harness = BackendHarness(recipe=RECIPE, warmup=8.0)
    try:
        drv = harness.start()
        res = drv.watch_like_gui(tail_level="INFO")
        check(
            bool(res.get("success")),
            "watch поднялся при строгих контрактах",
            f"success={res.get('success')}, observability={(res.get('observability') or {}).get('success')}",
        )
        time.sleep(2.0)
        drain(drv)
        marker = "A1-L5-STRICT-marker"
        for _ in range(3):
            provoke(drv, marker)
            time.sleep(1.0)
        time.sleep(6.0)
        mine = with_marker(drain(drv), marker)
        check(
            len(mine) > 0,
            "при STRICT записи ДОЕЗЖАЮТ (подписка не исчезла молча)",
            f"записей с маркером: {len(mine)}",
        )
    finally:
        harness.stop()
        os.environ.pop("FW_CONTRACTS_STRICT", None)


def main() -> int:
    log("=" * 78)
    log("Живая приёмка A1 — стенд webcam_sketch, порог подписки")
    log("=" * 78)

    harness = BackendHarness(recipe=RECIPE, warmup=8.0)
    drv = harness.start()
    try:
        procs = ["ProcessManager", CHILD]
        before = {p: router_violations(drv, p) for p in procs}
        log(f"\ncontract_violations до прогона: {before}")

        l1_info_subscription_delivers(drv)
        l2_error_subscription_still_filters(drv)
        l3_no_contract_violations(drv, before)
        l4_broker_readback_shows_the_level(drv)
    finally:
        harness.stop()

    l5_strict_mode_keeps_the_subscription_alive()

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
