# -*- coding: utf-8 -*-
"""Пара к зонду Н3-1: уборка аварийного разрыва не сломала ШТАТНЫЕ формы (Т-2).

Зонд `probe_n3_1_ghost_rst.py` доказывает, что призрак больше не появляется.
Один он ничего не говорит о цене: уборка, снимающая лишнее, дала бы точно такой
же зелёный — «подписок нет» и «призрака нет» неразличимы по счётчику ошибок.
Прецедент в этом же треке записан дважды (Н2-2: `unwatch()` снимал чужой хвост;
5.5-I4: проверка мерила хвост ПОСЛЕ снятия и потому не судила ничего).

Поэтому здесь два клиента и три утверждения:

  П1 «уходить есть чему» — клиент A подписался и получал события до ухода;
  П2 «сосед жив» — клиент B, подписанный ДО ухода A, продолжает получать
     события ПОСЛЕ него (иначе уборка снимает по суффиксу лишнее);
  П3 «ушедший не копит отказы» — рост счётчика ПОСЛЕ того, как уход улёгся,
     равен нулю; П3a — сама разовая цена ухода осталась окном (единицы), а не
     потоком. Делить их обязательно: между «пуш ушёл в сокет» и «сокет закрыт»
     окно есть всегда, и требование «ровно ноль» покрасило бы здоровую систему,
     а требование «ноль роста» ловит ровно призрака.

Запуск (стенд поднят, порт 8765):
    .venv/Scripts/python.exe backend_ctl/probes/probe_t2_normal_forms_pair.py
"""

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend_ctl.driver import BackendDriver  # noqa: E402
from backend_ctl.probes.probe_n3_1_ghost_rst import router_error_counters  # noqa: E402

WATCH_WINDOW_SEC = 15.0
SETTLE_SEC = 3.0
DEPARTURE_CEILING = 10  # разовое окно «пуш уже на проводе»; призрак давал ~39/с и не затухал


def drain(drv, cursor):
    """Счёт НОВЫХ событий от курсора. Длина страницы не годится: кольцо ограничено,
    и на насыщенном кольце «столько же» неотличимо от «ничего не пришло»."""
    total = 0
    while True:
        page = drv.events_page(cursor=cursor, limit=500)
        if not page.get("success", True):
            return total, None  # курсор сброшен — счёт этого окна недостоверен
        items = page.get("items") or []
        total += len(items)
        cursor = page.get("next_cursor")
        if len(items) < 500:
            return total, cursor


def main() -> int:
    failures: list = []
    base = router_error_counters()
    print("BASELINE:", json.dumps(base, ensure_ascii=False))

    b = BackendDriver()
    b.connect()
    b.state_subscribe("processes.**", timeout=10.0)
    b.observability_tail_all(level="INFO", timeout=10.0)

    a = BackendDriver()
    a.connect()
    a.state_subscribe("processes.**", timeout=10.0)
    a.observability_tail_all(level="INFO", timeout=10.0)
    time.sleep(3.0)

    a_before, _ = drain(a, None)
    print(f"A получил до ухода: {a_before}")
    if a_before <= 0:
        failures.append("П1: клиент A не получил ни одного события — уходить нечему")

    _b_seen, b_cursor = drain(b, None)
    a.unwatch()
    a.close()
    print("A ушёл штатно (unwatch + close)")

    time.sleep(SETTLE_SEC)  # пуш, уже уехавший на провод, отказом станет ЗДЕСЬ, а не позже
    settled = router_error_counters()
    departure = {k: settled.get(k, 0) - base.get(k, 0) for k in sorted(set(base) | set(settled))}
    departure = {k: v for k, v in departure.items() if v}
    print("DEPARTURE COST:", json.dumps(departure, ensure_ascii=False))
    # Разовая цена ухода законна: между «пуш ушёл в сокет» и «сокет закрыт» всегда есть
    # окно. Судится её ПОРЯДОК поимённо — призрак давал ~39/с, окно даёт единицы.
    for key, value in departure.items():
        if value > DEPARTURE_CEILING:
            failures.append(f"П3a: разовая цена ухода по '{key}' = {value} > {DEPARTURE_CEILING} — это уже не окно")

    time.sleep(WATCH_WINDOW_SEC)
    b_after, _ = drain(b, b_cursor)
    print(f"B получил ПОСЛЕ ухода A за {WATCH_WINDOW_SEC:.0f} с: {b_after}")
    if b_after <= 0:
        failures.append("П2: сосед замолчал после ухода A — уборка сняла чужое")

    after = router_error_counters()
    growth = {k: after.get(k, 0) - settled.get(k, 0) for k in sorted(set(settled) | set(after))}
    growth = {k: v for k, v in growth.items() if v}
    print(f"GROWTH(+{WATCH_WINDOW_SEC:.0f}s после ухода):", json.dumps(growth, ensure_ascii=False))
    if growth:
        failures.append(f"П3: ушедший клиент продолжает копить отказы — это призрак: {growth}")

    try:
        b.unwatch()
        b.close()
    except Exception:  # noqa: BLE001 — уборка зонда не судится
        pass

    print("VERDICT:", "OK" if not failures else "FAILED")
    for f in failures:
        print("  -", f)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
