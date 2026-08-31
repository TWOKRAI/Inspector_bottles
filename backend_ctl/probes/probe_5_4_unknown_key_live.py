# -*- coding: utf-8 -*-
"""Живая приёмка 5.4 — незнакомое ИМЯ ключа отвергается, а не оседает в L3.

Основание — приёмка F2 2026-08-12, находки Н-C/Н-D. Дефект живьём (до правки)::

    config.reload {"observability": {"logger": {"default_level": "DEBUG"}}}
    → success=true, session_keys=['logger.default_level'], effective — прежний,
      verified={'verdict': 'failed', 'unknown_keys': ['logger.default_level']}

`success` и вложенный вердикт в ОДНОМ ответе говорили разное. Оператор читает
`success`.

**Зачем живьём при 132 зелёных.** Тесты доказали механику границы на харнессе.
Здесь судится ПРОВОДКА: команда идёт по боевой дороге ``сокет → ПМ → роутер →
процесс``, то есть через receive-мидлварь получателя (fence/contract-check), а не
мимо неё. Именно этот пробел приёмщик назвал сам: «батарея мусора судила
командный слой, тот же мусор из GUI может вести себя иначе».

**Стенд не поднимается зондом** (решение владельца 2026-08-11 — у GUI-стенда одна
дорога подъёма, боевая)::

    BACKEND_CTL=1 INSPECTOR_GUI_UNATTENDED=1 INSPECTOR_LOG_DIR=logs_live/f2_5_4 \\
        .venv/Scripts/python.exe multiprocess_prototype/frontend/run.py

Проверки (каждая — на ДВУХ адресатах: ребёнок и оркестратор; дефект, починенный
на одном процессе из двух, воскресает на соседнем):

    P1  опечатка в имени → success=false, в reason путь ключа;
    P2  машинная форма ``logger.default_level`` → отказ, и reason называет
        человеческую форму (выход, а не только проблему);
    P3  в L3 не осело ничего: ни опечатка, ни машинная форма — и срок не съеден;
    P4  ответ не противоречит себе: нет пары ``success=true`` + ``verdict=failed``;
    P5  сосед не отравлен: после двух отказов законная правка принята И ДЕЙСТВУЕТ
        (класс Н-4: отвергнутая правка оставалась в слое и валила следующую);
    P6  уборка: поставленный проверкой P5 ключ снят, стенд остался как был.

Запуск: ``python -m backend_ctl.probes.probe_5_4_unknown_key_live``
"""

from __future__ import annotations

import sys
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

#: Оба адресата: ребёнок (дорога ПМ → роутер → процесс) и сам оркестратор.
TARGETS = ("camera_0", "ProcessManager")

FAILURES: List[str] = []


def log(message: str) -> None:
    print(message, flush=True)


def check(ok: bool, title: str, evidence: str) -> None:
    log(f"  [{'PASS' if ok else 'FAIL'}] {title}\n         {evidence}")
    if not ok:
        FAILURES.append(f"{title}: {evidence}")


def introspect(drv: BackendDriver, target: str) -> Dict[str, Any]:
    return _leaf_result(drv.send_command(target, "introspect.observability", {}, timeout=25.0)) or {}


def session_keys(drv: BackendDriver, target: str) -> List[str]:
    return list(((introspect(drv, target).get("layers") or {}).get("session_keys")) or [])


def reload(drv: BackendDriver, target: str, section: Dict[str, Any]) -> Dict[str, Any]:
    return drv.config_reload(target, observability=section, timeout=30.0)


def judge(drv: BackendDriver, target: str) -> None:
    log(f"\n=== адресат {target} ===")
    before = session_keys(drv, target)
    log(f"  session_keys до прогона: {before}")

    res1 = reload(drv, target, {"log_levl": "DEBUG"})
    reason1 = str(res1.get("reason", ""))
    check(
        res1.get("success") is False and "log_levl" in reason1,
        "P1 опечатка отвергнута с адресом ключа",
        f"success={res1.get('success')}, reason={reason1[:180]}",
    )

    res2 = reload(drv, target, {"logger": {"default_level": "DEBUG"}})
    reason2 = str(res2.get("reason", ""))
    check(
        res2.get("success") is False and "logger.default_level" in reason2,
        "P2 машинная форма отвергнута с адресом",
        f"success={res2.get('success')}, reason={reason2[:180]}",
    )
    check(
        "log_level" in reason2,
        "P2b отказ называет человеческую форму ключа",
        f"reason={reason2[:180]}",
    )

    after = session_keys(drv, target)
    check(
        "log_levl" not in after and not [k for k in after if k.startswith("logger.")],
        "P3 в L3 не осело ни одного отвергнутого ключа",
        f"session_keys={after}",
    )
    check(
        sorted(after) == sorted(before),
        "P3b состав L3 не изменился двумя отказами",
        f"до={sorted(before)}, после={sorted(after)}",
    )

    for name, res in (("опечатка", res1), ("машинная форма", res2)):
        verdict = (res.get("verified") or {}).get("verdict")
        check(
            not (res.get("success") is True and verdict == "failed"),
            f"P4 ответ не противоречит себе ({name})",
            f"success={res.get('success')}, verified.verdict={verdict}",
        )

    res5 = reload(drv, target, {"stats": {"flush_interval": 4.0}})
    eff5 = (res5.get("effective") or {}).get("stats") or {}
    verdict5 = (res5.get("verified") or {}).get("verdict")
    check(
        res5.get("success") is True and verdict5 != "failed",
        "P5 законная правка после отказов принята",
        f"success={res5.get('success')}, verdict={verdict5}",
    )
    check(
        "stats.flush_interval" in session_keys(drv, target),
        "P5b и она держится сессией",
        f"session_keys={session_keys(drv, target)}",
    )
    check(
        eff5.get("flush_interval") in (4.0, 4),
        "P5c и ДЕЙСТВУЕТ (readback живого объекта)",
        f"effective.stats.flush_interval={eff5.get('flush_interval')}",
    )

    # Уборка — адресным сбросом ключа, а не пустой секцией: пустая секция это
    # «владение пустотой» по правилу Г3, то есть другая операция.
    drv.send_command(
        target,
        "config.reload",
        {"observability_reset": ["stats.flush_interval"]},
        timeout=30.0,
    )
    left = session_keys(drv, target)
    check(
        "stats.flush_interval" not in left,
        "P6 уборка: ключ прогона снят, стенд остался как был",
        f"session_keys={left}",
    )


def main() -> int:
    host, port = resolve_endpoint()
    log("=" * 78)
    log("Живая приёмка 5.4 — незнакомое имя ключа не доживает до слоя сессии")
    log(f"эндпоинт: {host}:{port}")
    log("=" * 78)

    drv = BackendDriver(host=host, port=port)
    try:
        drv.connect()
    except Exception as exc:  # noqa: BLE001 — отсутствие стенда объясняем командой запуска
        log(f"стенд недоступен ({exc}). Подними его так:")
        log("  BACKEND_CTL=1 INSPECTOR_GUI_UNATTENDED=1 INSPECTOR_LOG_DIR=logs_live/f2_5_4 \\")
        log("      .venv/Scripts/python.exe multiprocess_prototype/frontend/run.py")
        return 2

    try:
        for target in TARGETS:
            judge(drv, target)
    finally:
        close = getattr(drv, "close", None)
        if callable(close):
            close()

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
