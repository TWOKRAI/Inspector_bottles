# -*- coding: utf-8 -*-
"""Живой зонд Task 5.7 (A5) — смена наблюдаемости с доказательством на РАБОТАЮЩЕЙ системе.

Почему живьём. Unit-тесты доказывают арифметику вердикта на подставных снимках.
Они не доказывают ПРОВОДКУ: что база отсчёта действительно едет в ответе
``config.reload`` живого процесса, что второй замер читается с того же процесса и
что на пишущей системе окно доставки получается ненулевым. Класс «механизм есть,
наружу не видно» на этом проекте стрелял уже не раз.

Что проверяется:

    A5-1  смена уровня на РЕАЛЬНОМ процессе → ``verdict == "confirmed"`` и
          ``delivering is True``. Два разных факта в одном ответе.
    A5-2  опечатка в имени ключа на живой системе → ``verdict == "failed"``,
          ключ назван, при ``success is True``. Сегодняшний тихий успех.
    A5-3  молчащий источник (уровень поднят до CRITICAL) → ``silent_source is True``
          и это НЕ провал вердикта: ``verdict`` остаётся ``confirmed``.
    A5-4  ``self_cost`` — цена САМОГО опроса, измеренная на DEBUG. Проверка
          обоснования механизма: читающая команда пишет записи о себе, и без
          вычета ``delivering`` был бы истинным всегда, включая молчащий
          источник. Если цена окажется нулевой — это находка о зонде и о
          docstring'е, а не украшение.

Запуск: ``python -m backend_ctl.probes.probe_5_7_verified_change``
(BACKEND_CTL выставляется самим зондом). Прогон ~1 минута.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

os.environ["BACKEND_CTL"] = "1"

# Консоль Windows отдаёт cp1251/cp866: юникод в заголовке роняет весь прогон
# UnicodeEncodeError'ом ПОСЕРЕДИНЕ стенда.
for _stream in (sys.stdout, sys.stderr):
    _reconfigure = getattr(_stream, "reconfigure", None)
    if callable(_reconfigure):
        _reconfigure(encoding="utf-8", errors="replace")

from backend_ctl.harness import BackendHarness  # noqa: E402

RECIPE = PROJECT_ROOT / "multiprocess_prototype" / "recipes" / "dualcam_synth.yaml"
TARGET = "ProcessManager"

FAILURES: list[str] = []


def log(msg: str) -> None:
    print(msg, flush=True)


def check(ok: bool, title: str, evidence: str) -> None:
    log(f"  [{'PASS' if ok else 'FAIL'}] {title}\n         {evidence}")
    if not ok:
        FAILURES.append(f"{title}: {evidence}")


def brief(res: dict) -> str:
    """Короткая выжимка ответа — то, по чему выносится вердикт."""
    return (
        f"verdict={res.get('verdict')!r} delivering={res.get('delivering')} "
        f"silent={res.get('silent_source')} losing={res.get('losing')} "
        f"delta={res.get('written_delta')} self_cost={res.get('self_cost')} "
        f"net={res.get('written_net')} window={res.get('window_sec')!r}"
    )


def main() -> int:
    harness = BackendHarness(recipe=RECIPE, warmup=8.0)
    drv = harness.start()
    try:
        log("\n--- A5-1 / A5-4: смена уровня на живом процессе ---")
        debug = drv.config_reload_verified(TARGET, observability={"log_level": "DEBUG"}, settle=2.0, timeout=25.0)
        log(f"         {brief(debug)}")
        check(
            debug.get("verdict") == "confirmed",
            "A5-1: значение ДЕЙСТВУЕТ (вердикт процесса)",
            f"verified={debug.get('verified')}",
        )
        check(
            debug.get("delivering") is True,
            "A5-1: записи ИДУТ после смены (окно по двум замерам)",
            f"delta={debug.get('written_delta')} net={debug.get('written_net')} "
            f"по каналам={debug.get('written_by_channel')}",
        )
        check(
            isinstance(debug.get("window_sec"), float) and debug["window_sec"] > 0,
            "A5-1: окно измерено (метка observed_at растёт между замерами)",
            f"window_sec={debug.get('window_sec')!r}",
        )
        check(
            isinstance(debug.get("self_cost"), int) and debug["self_cost"] > 0,
            "A5-4: цена самого опроса ИЗМЕРЕНА ненулевой на DEBUG",
            f"self_cost={debug.get('self_cost')!r} (вычитается из наблюдённой дельты)",
        )

        log("\n--- A5-2: опечатка в имени ключа на живой системе ---")
        typo = drv.config_reload_verified(TARGET, observability={"log_levl": "DEBUG"}, settle=1.0, timeout=25.0)
        log(f"         {brief(typo)}")
        check(
            typo.get("verdict") == "failed",
            "A5-2: опечатка — ПРОВАЛ вердикта, а не тихий успех",
            f"verified={typo.get('verified')}",
        )
        check(
            typo.get("success") is True,
            "A5-2: применение при этом НЕ падало (success и вердикт — разные поля)",
            f"success={typo.get('success')!r}",
        )

        log("\n--- A5-3: молчащий источник — отдельное состояние ---")
        quiet = drv.config_reload_verified(TARGET, observability={"log_level": "CRITICAL"}, settle=2.0, timeout=25.0)
        log(f"         {brief(quiet)}")
        check(
            quiet.get("silent_source") is True,
            "A5-3: источник молчит → silent_source",
            f"delta={quiet.get('written_delta')} losing={quiet.get('losing')}",
        )
        check(
            quiet.get("verdict") == "confirmed",
            "A5-3: тишина источника НЕ отменяет вердикта о значении",
            f"verdict={quiet.get('verdict')!r} verified={quiet.get('verified')}",
        )
    finally:
        # Уровень возвращается снятием ключа из слоя сессии, а не присвоением
        # прежнего: присвоение порвало бы связь с нижним слоем навсегда.
        try:
            drv.send_command(TARGET, "config.reload", {"observability_reset": ["log_level"]}, timeout=25.0)
        except Exception as exc:  # noqa: BLE001 — стенд всё равно гасится ниже
            log(f"  [WARN] уровень не возвращён: {exc}")
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
