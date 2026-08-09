# -*- coding: utf-8 -*-
"""Живой зонд Task 5.6 — счётчик доставки ненулевой на РАБОТАЮЩЕЙ системе.

Почему живьём, а не только pytest'ом. Unit-тесты доказывают механику: счётчик
растёт на доставке и не растёт на потере. Они не доказывают ПРОВОДКУ — что на
настоящем процессе записи вообще идут через учтённый путь, что ключи доезжают до
``introspect.observability`` и что число там непустое. Ровно этот разрыв
(«механизм есть, наружу не видно») ловил страж реестра публикации при реализации.

Что проверяется:

    B1  у живого процесса ``channel_written_records`` > 0 — записи доходят,
        и это ВИДНО снаружи, а не только в get_stats() для тестов.
    B2  разбивка по каналам непуста и называет конкретные приёмники.
    B3  темп, посчитанный ЗОНДОМ по двум снимкам, положителен на пишущей системе.
        Менеджер темпа не отдаёт — он отдаёт счётчик и ``observed_at``, частное
        берёт потребитель. Зонд здесь и есть потребитель, то есть проверяется
        ровно тот путь, которым числом будут пользоваться GUI и backend_ctl.
    B4  потери и доставка живут в ОДНОМ снимке: «потерь ноль при нуле доставок»
        не должно читаться здоровьем. Проверяется тем, что оба класса ключей
        присутствуют в одном ответе.
    B5  счётчик доставки есть у НЕСКОЛЬКИХ процессов, а не только у одного —
        учёт поднят в общую базу трёх менеджеров, а не дописан одному.

Запуск: ``python -m backend_ctl.probes.probe_5_6_delivery_counters``
(BACKEND_CTL выставляется самим зондом). Прогон ~1 минута.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

os.environ["BACKEND_CTL"] = "1"

# Консоль Windows отдаёт cp1251/cp866: юникод в заголовке роняет весь прогон
# UnicodeEncodeError'ом ПОСЕРЕДИНЕ стенда — то есть зонд убивает не проверка, а
# печать про неё.
for _stream in (sys.stdout, sys.stderr):
    _reconfigure = getattr(_stream, "reconfigure", None)
    if callable(_reconfigure):
        _reconfigure(encoding="utf-8", errors="replace")

from backend_ctl.driver import _leaf_result  # noqa: E402
from backend_ctl.harness import BackendHarness  # noqa: E402

RECIPE = PROJECT_ROOT / "multiprocess_prototype" / "recipes" / "dualcam_synth.yaml"
PROCESSES = ("ProcessManager", "camera_0")

FAILURES: list[str] = []


def log(msg: str) -> None:
    print(msg, flush=True)


def check(ok: bool, title: str, evidence: str) -> None:
    log(f"  [{'PASS' if ok else 'FAIL'}] {title}\n         {evidence}")
    if not ok:
        FAILURES.append(f"{title}: {evidence}")


def obs(drv, process: str) -> dict:
    return _leaf_result(drv.send_command(process, "introspect.observability", {"audit_limit": 1}, timeout=25.0)) or {}


def counters(snapshot: dict, plane: str = "logger") -> dict:
    """Счётчики КОНКРЕТНОЙ плоскости.

    Секция ``counters`` вложена по плоскостям (``logger`` / ``error`` / ``stats``),
    а не плоская. Первая редакция зонда читала верхний уровень и получила шесть
    провалов при исправном продукте — включая пустыми предсуществующие счётчики
    потерь. Это и был признак дефекта ЗОНДА: счётчики потерь существуют с Ф0.4,
    и их пустота означала неверный путь чтения, а не поломку.
    """
    return ((snapshot.get("counters") or {}).get(plane)) or {}


def main() -> int:
    harness = BackendHarness(recipe=RECIPE, warmup=8.0)
    drv = harness.start()
    try:
        log("\n--- B1, B2, B4: доставка видна снаружи ---")
        per_process: dict[str, dict] = {}
        for name in PROCESSES:
            per_process[name] = counters(obs(drv, name))

        pm = per_process["ProcessManager"]
        written = pm.get("channel_written_records")
        check(
            isinstance(written, int) and written > 0,
            "B1: у оркестратора channel_written_records > 0",
            f"channel_written_records={written!r}",
        )

        by_channel = pm.get("channel_written_by_channel") or {}
        check(
            bool(by_channel) and all(isinstance(v, int) and v > 0 for v in by_channel.values()),
            "B2: разбивка по каналам называет конкретные приёмники",
            f"channel_written_by_channel={by_channel}",
        )

        loss_keys = {"unresolved_channel_records", "channel_write_errors", "channel_refused_records"}
        delivery_keys = {"channel_written_records", "channel_written_by_channel", "observed_at"}
        check(
            loss_keys <= set(pm) and delivery_keys <= set(pm),
            "B4: потери и доставка в ОДНОМ снимке",
            f"потери={sorted(loss_keys & set(pm))}, доставка={sorted(delivery_keys & set(pm))}",
        )

        log("\n--- B5: учёт у нескольких процессов (общая база, а не один менеджер) ---")
        alive = {n: c.get("channel_written_records") for n, c in per_process.items()}
        check(
            all(isinstance(v, int) and v > 0 for v in alive.values()),
            "B5: доставка непуста у всех опрошенных процессов",
            f"{alive}",
        )

        log("\n--- B3: темп выводит потребитель по двум снимкам ---")
        time.sleep(3.0)
        second = counters(obs(drv, "ProcessManager"))
        grew = (second.get("channel_written_records") or 0) - (written or 0)
        elapsed = (second.get("observed_at") or 0) - (pm.get("observed_at") or 0)
        rate = grew / elapsed if elapsed > 0 else None
        check(
            elapsed > 0,
            "B3: метка времени снимка растёт между чтениями",
            f"observed_at: {pm.get('observed_at')!r} -> {second.get('observed_at')!r} (Δ={elapsed:.3f}с)",
        )
        check(
            rate is not None and rate > 0,
            "B3: темп, посчитанный потребителем, > 0 на пишущей системе",
            f"{grew} записей / {elapsed:.3f}с = {rate!r} записей/с",
        )
        # Вторая половина пары: темп не выдуман — он согласуется с приростом.
        check(
            grew > 0,
            "B3 (вторая половина): счётчик действительно вырос за интервал",
            f"прирост channel_written_records={grew}",
        )
    finally:
        harness.stop()

    log("\n" + "=" * 60)
    if FAILURES:
        log(f"ПРОВАЛЕНО проверок: {len(FAILURES)}")
        for f in FAILURES:
            log(f"  - {f}")
        return 1
    log("ВСЕ ПРОВЕРКИ ПРОЙДЕНЫ")
    return 0


if __name__ == "__main__":
    sys.exit(main())
