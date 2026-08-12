# -*- coding: utf-8 -*-
"""Живая приёмка 5.6 — прицельная подписка сильнее оптовой (Н2-1 + Н2-2).

Дефекты живьём (переприёмка F2 раунд 2, воспроизведены приёмщиком и исполнителем):

* **Н2-1 (блокер).** `subscribe(camera_0, INFO)` + `subscribe_all(WARNING)` → 31
  запись `{info}` превращалась в 0 info `{error: 6}`. Побеждала последняя воля,
  молча, а манифест продолжал обещать INFO;
* **Н2-2.** `unwatch()` глушил прицельный хвост, которого сам не создавал: 28
  записей → 28 после снятия профиля, который ни разу не включался.

Решение владельца 2026-08-12 — объединение по мерилу 1 («подписчик с level=INFO
получает INFO от каждого процесса»). Намерение «оптовая раздача» едет на проводе
(`scope="all"`): процесс не может отличить дороги сам, потому что брокер
разворачивает оптовую команду в те же адресные `observability.tail.subscribe`.

Проверки:

    U1  прицельный INFO доезжает (база отсчёта, признак жизни);
    U2  ОПТОВАЯ подписка WARNING поверх него НЕ гасит INFO — репро Н2-1;
    U3  и говорит об этом: ответ несёт `kept_level`/`ignored_level`;
    U4  ОПТОВОЕ снятие не сносит прицельную подписку — репро Н2-2;
    U5  пара к U4: ПРИЦЕЛЬНОЕ снятие её снимает (иначе «выжила» означало бы
        «не снимается вовсе»);
    U6  пара к U2: ПРИЦЕЛЬНОЕ понижение работает — оператор делает тише тем же
        жестом, каким сделал громче.

Стенд не поднимается зондом (решение владельца 2026-08-11)::

    BACKEND_CTL=1 INSPECTOR_GUI_UNATTENDED=1 INSPECTOR_LOG_DIR=logs_live/f2_5_6 \\
        .venv/Scripts/python.exe multiprocess_prototype/frontend/run.py

Запуск: ``python -m backend_ctl.probes.probe_5_6_subscription_union_live``
"""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, List

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

for _stream in (sys.stdout, sys.stderr):
    _reconfigure = getattr(_stream, "reconfigure", None)
    if callable(_reconfigure):
        _reconfigure(encoding="utf-8", errors="replace")

from backend_ctl.driver import BackendDriver, _leaf_result  # noqa: E402
from backend_ctl.endpoint_config import resolve_endpoint  # noqa: E402

SOURCE = "camera_0"
FAILURES: List[str] = []
_LOCK = threading.Lock()
_MESSAGES: List[Dict[str, Any]] = []


def log(message: str) -> None:
    print(message, flush=True)


def check(ok: bool, title: str, evidence: str) -> None:
    log(f"  [{'PASS' if ok else 'FAIL'}] {title}\n         {evidence}")
    if not ok:
        FAILURES.append(f"{title}: {evidence}")


def _collect(msg: Dict[str, Any]) -> None:
    with _LOCK:
        _MESSAGES.append(msg)


def info_records() -> int:
    """Сколько INFO-записей хвоста пришло. Судим по severity записи, а не по числу
    сообщений: WARNING-порог тоже даёт записи, и общий счёт зеленел бы всегда."""
    total = 0
    with _LOCK:
        snapshot = list(_MESSAGES)
    for msg in snapshot:
        if msg.get("command") != "observability.record":
            continue
        data = msg.get("data") or {}
        records = list(data.get("records") or [])
        if data.get("record"):
            records.append(data["record"])
        for record in records:
            level = str(record.get("level") or record.get("severity") or "").upper()
            if level in ("INFO", "DEBUG", "TRACE"):
                total += 1
    return total


def provoke(drv: BackendDriver, times: int = 4) -> None:
    """Заставить источник написать INFO: пересборка слоёв пишет «пересобран из слоёв»."""
    for _ in range(times):
        drv.config_reload(SOURCE, observability={"stats": {"flush_interval": 4.0}}, timeout=30.0)
        time.sleep(0.4)
    drv.send_command(SOURCE, "config.reload", {"observability_reset": ["stats.flush_interval"]}, timeout=30.0)
    time.sleep(4.0)


def main() -> int:
    host, port = resolve_endpoint()
    log("=" * 78)
    log("Живая приёмка 5.6 — прицельная подписка сильнее оптовой")
    log(f"эндпоинт: {host}:{port} · источник: {SOURCE}")
    log("=" * 78)

    drv = BackendDriver(host=host, port=port)
    try:
        drv.connect()
    except Exception as exc:  # noqa: BLE001
        log(f"стенд недоступен ({exc}). Подними его так:")
        log("  BACKEND_CTL=1 INSPECTOR_GUI_UNATTENDED=1 INSPECTOR_LOG_DIR=logs_live/f2_5_6 \\")
        log("      .venv/Scripts/python.exe multiprocess_prototype/frontend/run.py")
        return 2

    try:
        drv.get_status(SOURCE, timeout=25.0)
        drv.subscribe(_collect)

        # U1 — прицельная подписка INFO.
        res = drv.observability_tail(SOURCE, level="INFO", timeout=30.0)
        log(f"  прицельная подписка: success={res.get('success')}, min_level={res.get('min_level')}")
        provoke(drv)
        base = info_records()
        check(base > 0, "U1 прицельный INFO доезжает (признак жизни)", f"INFO-записей: {base}")

        # U2/U3 — оптовая WARNING поверх прицельного INFO.
        wide = (
            _leaf_result(
                drv.send_command(
                    "ProcessManager",
                    "observability.tail.subscribe_all",
                    {"subscriber": drv._subscriber, "level": "WARNING"},  # noqa: SLF001
                    timeout=30.0,
                )
            )
            or {}
        )
        log(f"  оптовая подписка WARNING: success={wide.get('success')}, reached={wide.get('reached')}")
        time.sleep(2.0)
        provoke(drv)
        after_wide = info_records()
        check(
            after_wide > base,
            "U2 оптовая WARNING не погасила прицельный INFO (репро Н2-1)",
            f"INFO-записей: {base} → {after_wide}",
        )
        own = (
            _leaf_result(
                drv.send_command(
                    SOURCE,
                    "observability.tail.subscribe",
                    {"subscriber": drv._subscriber, "level": "WARNING", "scope": "all"},
                    timeout=30.0,
                )
            )
            or {}
        )  # noqa: SLF001
        kept, ignored = own.get("kept_level"), own.get("ignored_level")
        check(
            kept == "INFO" and ignored == "WARNING",
            "U3 и процесс говорит об этом в ответе",
            f"kept_level={kept}, ignored_level={ignored}, reason={str(own.get('reason'))[:80]}",
        )

        # U4 — оптовое снятие не сносит прицельную подписку.
        drv.observability_untail_all(timeout=30.0)
        time.sleep(2.0)
        before_untail = info_records()
        provoke(drv)
        after_untail = info_records()
        check(
            after_untail > before_untail,
            "U4 оптовое снятие не сняло прицельную подписку (репро Н2-2)",
            f"INFO-записей: {before_untail} → {after_untail}",
        )

        # U6 — прицельное понижение работает (пара к U2).
        drv.observability_tail(SOURCE, level="ERROR", timeout=30.0)
        time.sleep(2.0)
        before_low = info_records()
        provoke(drv)
        after_low = info_records()
        check(
            after_low == before_low,
            "U6 прицельное понижение до ERROR гасит INFO",
            f"INFO-записей: {before_low} → {after_low}",
        )

        # U5 — прицельное снятие снимает (пара к U4).
        drv.observability_tail(SOURCE, level="INFO", timeout=30.0)
        time.sleep(1.0)
        drv.observability_untail(SOURCE, timeout=30.0)
        time.sleep(1.0)
        before_off = info_records()
        provoke(drv)
        after_off = info_records()
        check(
            after_off == before_off,
            "U5 прицельное снятие действительно снимает",
            f"INFO-записей: {before_off} → {after_off}",
        )
    finally:
        for call in (
            lambda: drv.observability_untail(SOURCE, timeout=20.0),
            lambda: drv.observability_untail_all(timeout=20.0),
        ):
            try:
                call()
            except Exception as exc:  # noqa: BLE001
                log(f"  уборка: {type(exc).__name__}: {str(exc)[:70]}")
        try:
            drv.close()
        except Exception:  # noqa: BLE001
            pass

    log("\n" + "=" * 78)
    if FAILURES:
        log(f"ПРОВАЛЕНО проверок: {len(FAILURES)}")
        for item in FAILURES:
            log(f"  - {item}")
        return 1
    log("ВСЕ ПРОВЕРКИ ПРОЙДЕНЫ")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
