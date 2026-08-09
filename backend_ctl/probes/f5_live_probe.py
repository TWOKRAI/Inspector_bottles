# -*- coding: utf-8 -*-
"""Живой прогон Ф5.2/Ф5.4 — пары «до/после» на настоящем стенде.

Что доказывается, по одной проверке на заявленную пару:

* **Ф5.4, ось приёмников** — узор ``module_*`` гасит N приёмников ОДНОЙ командой и
  называет все N поимённо. До задачи это было N команд.
* **Ф5.4, ось процессов** — ``process="all"`` / ``camera_*`` меняет M процессов и
  отвечает per-process. До задачи ответа от каждого не давал ни один путь.
* **Ф5.4, отказы** — узор, не поймавший ничего, и адрес, не поймавший процессов,
  громкие: «раздал в никуда» не выглядит как «раздал».
* **Ф5.2, Б-4** — в истории есть строки вида ``log``. До задачи все 303 016 строк
  живого прогона были ``kind='error'``, потому что вид метил перевозчик.
* **Ф5.2, Б-8** — вкладка «Логи» имеет чем наполниться (те же строки ``log``);
  плоскость метрик пуста, и это ОЖИДАЕМО до Ф8.3.
* **Ф5.2, пункт 5** — объём стора при пороге INFO: МБ/час и держит ли ретеншен.

Запуск (из корня репозитория)::

    python -m backend_ctl.probes.f5_live_probe --recipe webcam_sketch --duration 180

Стенд по умолчанию — ``webcam_sketch`` (решение владельца 2026-08-03: семь процессов,
живая камера, тяжёлый конвейер). Камеры может не быть — тогда ``--recipe region_pipeline``
даёт синтетический тракт: числа объёма будут другими, и проба скажет об этом в отчёте.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict

from backend_ctl.protocol import unwrap

_RECIPES = Path(__file__).resolve().parent.parent.parent / "multiprocess_prototype" / "recipes"


def _leaf(res: Any) -> Dict[str, Any]:
    try:
        return unwrap(res, leaf=True)
    except Exception:  # noqa: BLE001 — проба не должна падать на форме ответа
        return {"unwrap_error": repr(res)[:400]}


def _db_size(path: str) -> int:
    """Размер файла стора вместе с WAL: строки живут в WAL до чекпойнта."""
    total = 0
    for suffix in ("", "-wal", "-shm"):
        try:
            total += os.path.getsize(path + suffix)
        except OSError:
            pass
    return total


def _history(drv: Any, process: str) -> Dict[str, Any]:
    res = _leaf(drv.send_command(process, "introspect.observability", None))
    return res.get("history", {}) if isinstance(res, dict) else {}


def main() -> int:
    ap = argparse.ArgumentParser(description="Живой прогон Ф5.2/Ф5.4")
    ap.add_argument("--recipe", default="webcam_sketch", help="имя рецепта без .yaml")
    ap.add_argument("--duration", type=float, default=180.0, help="сколько секунд копить объём")
    ap.add_argument("--port", type=int, default=8811)
    ap.add_argument("--out", type=Path, default=Path("f5_live_probe.json"))
    args = ap.parse_args()

    from backend_ctl.harness import BackendHarness

    recipe = _RECIPES / f"{args.recipe}.yaml"
    if not recipe.exists():
        print(f"рецепт не найден: {recipe}")
        return 2

    report: Dict[str, Any] = {"recipe": args.recipe, "duration": args.duration, "checks": {}}
    harness = BackendHarness(recipe=recipe, with_base=True, port=args.port)
    with harness as drv:
        procs = drv._discover_processes()
        report["processes"] = procs
        print(f"[стенд] рецепт={args.recipe} процессы={procs}")
        if not procs:
            report["checks"]["topology"] = {"ok": False, "detail": "топология пуста"}
            args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            return 1

        # Дать системе прогреться: записи должны реально пойти.
        time.sleep(20.0)

        pilot = next((p for p in procs if p != "ProcessManager"), procs[0])

        # --- Ф5.2: что лежит в истории и по какому порогу ------------------
        hist_before = _history(drv, pilot)
        report["checks"]["history_policy"] = hist_before
        print(f"[Ф5.2] история {pilot}: {hist_before}")

        # --- Ф5.4, ось приёмников -----------------------------------------
        # Сперва СМОТРИМ каталог: узор доказателен только против известного множества.
        eff = _leaf(drv.send_command(pilot, "introspect.observability", None))
        catalog = (eff.get("effective", {}).get("logger", {}) or {}).get("channels_active", [])
        report["checks"]["sink_catalog"] = catalog
        print(f"[Ф5.4] каталог приёмников {pilot}: {catalog}")

        glob_res = _leaf(drv.send_command(pilot, "observability.sink.disable", {"sink": "module_*"}))
        report["checks"]["sink_glob"] = glob_res
        print(f"[Ф5.4] узор module_* → {json.dumps(glob_res, ensure_ascii=False)[:600]}")

        # Узор по ВСЕМ приёмникам плоскости ошибок — доказывает, что раскрытие
        # не выходит за свою плоскость и работает не только на per-module именах.
        err_glob = _leaf(drv.send_command(pilot, "observability.sink.disable", {"sink": "*", "manager": "error"}))
        report["checks"]["sink_glob_error_plane"] = err_glob
        print(f"[Ф5.4] узор * на плоскости error → {json.dumps(err_glob, ensure_ascii=False)[:400]}")

        miss = _leaf(drv.send_command(pilot, "observability.sink.disable", {"sink": "нет_такого_*"}))
        report["checks"]["sink_glob_miss"] = miss
        print(f"[Ф5.4] узор-промах → success={miss.get('success')} reason={str(miss.get('reason'))[:160]}")

        # --- Ф5.4, ось процессов ------------------------------------------
        batch_all = drv.config_reload("all", observability={"log_level": "INFO"})
        report["checks"]["batch_all"] = {
            "success": batch_all.get("success"),
            "targets": batch_all.get("targets"),
            "failed": batch_all.get("failed"),
            "not_ok": batch_all.get("not_ok"),
            "answered": sorted(batch_all.get("processes", {})),
        }
        print(f"[Ф5.4] батч all → цели={batch_all.get('targets')} нет ответа={batch_all.get('failed')}")

        pattern = "camera_*" if any(p.startswith("camera_") for p in procs) else f"{pilot[:3]}*"
        batch_pat = drv.config_reload(pattern, observability={"log_level": "INFO"})
        report["checks"]["batch_pattern"] = {
            "pattern": pattern,
            "targets": batch_pat.get("targets"),
            "success": batch_pat.get("success"),
        }
        print(f"[Ф5.4] батч {pattern} → цели={batch_pat.get('targets')}")

        batch_miss = drv.config_reload("робот_*", observability={"log_level": "INFO"})
        report["checks"]["batch_miss"] = {
            "success": batch_miss.get("success"),
            "error": str(batch_miss.get("error"))[:200],
        }
        print(f"[Ф5.4] батч-промах → success={batch_miss.get('success')}")

        # --- Ф5.2, объём --------------------------------------------------
        db_path = str(hist_before.get("db_path") or "")
        size0 = _db_size(db_path)
        t0 = time.time()
        print(f"[Ф5.2] замер объёма: {db_path} = {size0 / 1024:.1f} КиБ, ждём {args.duration:.0f} с")
        time.sleep(args.duration)
        size1 = _db_size(db_path)
        elapsed = time.time() - t0
        hist_after = _history(drv, pilot)
        rate_mb_h = (size1 - size0) / (1024 * 1024) / (elapsed / 3600.0) if elapsed > 0 else 0.0
        report["checks"]["volume"] = {
            "db_path": db_path,
            "bytes_before": size0,
            "bytes_after": size1,
            "elapsed_sec": round(elapsed, 1),
            "mb_per_hour": round(rate_mb_h, 2),
            "rows_before": hist_before.get("rows"),
            "rows_after": hist_after.get("rows"),
        }
        print(
            f"[Ф5.2] объём: {size0 / 1024:.1f} → {size1 / 1024:.1f} КиБ за {elapsed:.0f} с "
            f"= {rate_mb_h:.2f} МБ/час; строки {hist_before.get('rows')} → {hist_after.get('rows')}"
        )

    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nотчёт: {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
