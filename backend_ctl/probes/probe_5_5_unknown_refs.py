# -*- coding: utf-8 -*-
"""Живой зонд Task 5.5 — ссылка без приёмника громкая на РАБОТАЮЩЕЙ системе.

Unit-тесты доказывают различение «определение против ссылки в пустоту» на живом
`LoggerManager`, но не проводку: что отказ доезжает до оператора через IPC и что
законная правка при этом не отвергается. Новый сигнал (`unknown_refs`) обязан быть
показан ненулевым живьём — BCTL-ADR-007.

    C1  опечатка в имени канала inline → отказ, `unknown_refs` называет ключ
    C2  состояние НЕ изменилось: уровень остался прежним
    C3  законная правка того же вида проходит (проверка не запрещает правки)
    C4  новый скоуп без каналов → отказ (ложный `confirmed` больше невозможен)

Запуск: ``python -m backend_ctl.probes.probe_5_5_unknown_refs``
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))
os.environ["BACKEND_CTL"] = "1"

for _s in (sys.stdout, sys.stderr):
    _r = getattr(_s, "reconfigure", None)
    if callable(_r):
        _r(encoding="utf-8", errors="replace")

from backend_ctl.harness import BackendHarness  # noqa: E402

RECIPE = PROJECT_ROOT / "multiprocess_prototype" / "recipes" / "dualcam_synth.yaml"
TARGET = "ProcessManager"
FAILURES: list[str] = []


def check(ok: bool, title: str, evidence: str) -> None:
    print(f"  [{'PASS' if ok else 'FAIL'}] {title}\n         {evidence}", flush=True)
    if not ok:
        FAILURES.append(title)


def main() -> int:
    harness = BackendHarness(recipe=RECIPE, warmup=8.0)
    drv = harness.start()
    try:
        level_before = (
            (drv.config_reload(TARGET, observability={}, timeout=25.0) or {}).get("applied", {}).get("log_level")
        )
        typo = drv.config_reload(TARGET, observability={"channels": {"messages_fil": {"enabled": False}}}, timeout=25.0)
        check(typo.get("success") is False, "C1: опечатка в канале — отказ", f"success={typo.get('success')!r}")
        check(
            typo.get("unknown_refs") == {"channels": ["messages_fil"]},
            "C1: ключ назван поимённо",
            f"unknown_refs={typo.get('unknown_refs')!r}",
        )
        after = drv.config_reload(TARGET, observability={}, timeout=25.0) or {}
        check(
            after.get("applied", {}).get("log_level") == level_before,
            "C2: состояние не изменилось",
            f"log_level {level_before!r} -> {after.get('applied', {}).get('log_level')!r}",
        )
        good = drv.config_reload(TARGET, observability={"channels": {"console": {"enabled": True}}}, timeout=25.0)
        check(
            good.get("success") is True and "unknown_refs" not in good,
            "C3: законная правка проходит",
            f"success={good.get('success')!r} unknown_refs={good.get('unknown_refs')!r}",
        )
        scope = drv.config_reload(TARGET, observability={"scopes": {"SYSTEMM": {"min_level": "DEBUG"}}}, timeout=25.0)
        check(
            scope.get("success") is False and scope.get("unknown_refs") == {"scopes": ["SYSTEMM"]},
            "C4: новый скоуп без каналов — отказ, не ложный confirmed",
            f"success={scope.get('success')!r} unknown_refs={scope.get('unknown_refs')!r} "
            f"verified={scope.get('verified')!r}",
        )
    finally:
        harness.stop()

    print("\n" + "=" * 60)
    if FAILURES:
        print(f"ПРОВАЛЕНО: {len(FAILURES)}")
        for f in FAILURES:
            print(f"  - {f}")
        return 1
    print("ВСЕ ПРОВЕРКИ ПРОЙДЕНЫ")
    return 0


if __name__ == "__main__":
    sys.exit(main())
