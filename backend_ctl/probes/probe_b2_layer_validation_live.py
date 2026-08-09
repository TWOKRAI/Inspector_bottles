# -*- coding: utf-8 -*-
"""Живая приёмка B2 — мусор не доживает до сессии, а валидное действует.

Зачем живьём при зелёных тестах. Тесты доказали МЕХАНИКУ границы. Здесь
судится ПРОВОДКА глазами оператора: отказ приезжает по сокету ответом команды
(а не исключением в чужом потоке), сессия остаётся чистой, и вторая половина
пары — валидное значение — по той же дороге доезжает и действует.

Проверки:

    V1  `config.reload {"log_level": "БОЛТОВНЯ"}` → success=false, в reason адрес
        ключа и список допустимых. Живой контрпример ревью: success=true.
    V2  Сессия НЕ содержит ключа (мусор не лёг в L3 со сроком).
    V3  Пара к V1: валидный DEBUG по той же дороге проходит и ДЕЙСТВУЕТ
        (readback `effective.logger.default_level`), а ключ появляется в L3.
    V4  Соседняя плоскость: `errors.level="ЧУШЬ"` отвергается тем же способом
        (дефект, починенный на одной ручке из трёх, воскресает на соседних).
    V5  Опечатка в ИМЕНИ ключа судится по-прежнему вердиктом, а не отказом:
        граница правила названа вслух и проверена, а не подразумевается.

Запуск: ``python -m backend_ctl.probes.probe_b2_layer_validation_live``
Стенд одиночный — порт 8765 не терпит двух. Прогон ~1.5 минуты.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Dict

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

FAILURES: list = []


def log(msg: str) -> None:
    print(msg, flush=True)


def check(ok: bool, title: str, evidence: str) -> None:
    log(f"  [{'PASS' if ok else 'FAIL'}] {title}\n         {evidence}")
    if not ok:
        FAILURES.append(f"{title}: {evidence}")


def introspect(drv) -> Dict[str, Any]:
    return _leaf_result(drv.send_command(CHILD, "introspect.observability", {}, timeout=25.0)) or {}


def session_keys(drv) -> list:
    return list(((introspect(drv).get("layers") or {}).get("session_keys")) or [])


def reload(drv, section: Dict[str, Any]) -> Dict[str, Any]:
    return drv.config_reload(CHILD, observability=section, timeout=30.0)


def main() -> int:
    log("=" * 78)
    log("Живая приёмка B2 — стенд webcam_sketch, валидация на границе слоёв")
    log("=" * 78)

    harness = BackendHarness(recipe=RECIPE, warmup=8.0)
    drv = harness.start()
    try:
        log("\n--- V1/V2: мусор отвергнут, сессия чиста ---")
        before = session_keys(drv)
        res = reload(drv, {"log_level": "БОЛТОВНЯ"})
        reason = str(res.get("reason", ""))
        check(
            res.get("success") is False,
            "мусорное значение НЕ засчитано успехом",
            f"success={res.get('success')}, reason={reason[:160]}",
        )
        check(
            "log_level" in reason and "DEBUG" in reason and "CRITICAL" in reason,
            "в отказе адрес ключа и список допустимых значений",
            f"reason={reason[:200]}",
        )
        after = session_keys(drv)
        check(
            "log_level" not in after,
            "ключ не лёг в сессию L3",
            f"session_keys до={before}, после={after}",
        )

        log("\n--- V3: пара — валидное значение проходит и действует ---")
        ok = reload(drv, {"log_level": "DEBUG"})
        level = ((ok.get("effective") or {}).get("logger") or {}).get("default_level")
        check(
            ok.get("success") is True and level == "DEBUG",
            "валидное значение принято и ДЕЙСТВУЕТ",
            f"success={ok.get('success')}, effective.logger.default_level={level}",
        )
        check(
            "log_level" in session_keys(drv),
            "принятый ключ виден в L3",
            f"session_keys={session_keys(drv)}",
        )

        log("\n--- V4: соседняя ручка отвергается тем же способом ---")
        res4 = reload(drv, {"errors": {"level": "ЧУШЬ"}})
        reason4 = str(res4.get("reason", ""))
        check(
            res4.get("success") is False and "errors.level" in reason4,
            "errors.level с мусором отвергнут с собственным адресом",
            f"success={res4.get('success')}, reason={reason4[:160]}",
        )
        check(
            "errors.level" not in session_keys(drv),
            "и он тоже не лёг в сессию",
            f"session_keys={session_keys(drv)}",
        )

        log("\n--- V5: опечатка в ИМЕНИ ключа — граница правила ---")
        res5 = reload(drv, {"log_levl": "DEBUG"})
        verified = res5.get("verified") or {}
        check(
            res5.get("success") is True and "log_levl" in (verified.get("unknown_keys") or []),
            "незнакомый ключ судится вердиктом (unknown_keys), а не отказом границы",
            f"success={res5.get('success')}, verdict={verified.get('verdict')}, "
            f"unknown_keys={verified.get('unknown_keys')}",
        )
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
