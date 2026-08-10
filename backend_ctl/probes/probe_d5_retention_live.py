# -*- coding: utf-8 -*-
"""Живая приёмка D5 — ПМ метёт ВСЁ дерево `log_dir`, чужие деревья только называет.

Что доказывается прогоном, а не чтением:

  1. каталог процесса, которого нет в текущем рецепте (осиротевший — ровно та
     слепая зона, что подтверждена листингом: файлы 12 дней при
     ``retention_days=7``), после boot'а не содержит просроченных файлов;
  2. свежий файл в том же каталоге НЕ удалён — уборка судит по возрасту, а не
     по факту «каталог чужой»;
  3. каталог ЖИВОГО процесса не тронут глобальной уборкой (его метёт свой
     подметальщик, знающий открытые хэндлы);
  4. чужое дерево вне ``log_dir`` НАЗВАНО, но не удалено (Р-5: уборка legacy —
     руками владельца).

Стенд поднимается со своим ``INSPECTOR_LOG_DIR`` во временном каталоге: живые
логи проекта проба не трогает вообще.

Запуск: ``python -m backend_ctl.probes.probe_d5_retention_live``
"""

from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path
from typing import List, Tuple

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

for _stream in (sys.stdout, sys.stderr):
    _reconfigure = getattr(_stream, "reconfigure", None)
    if callable(_reconfigure):
        _reconfigure(encoding="utf-8", errors="replace")

#: Возраст «просроченных» файлов. Заведомо больше ``retention_days: 7`` из
#: `backend/config/system.yaml` — и заведомо не равен ему, чтобы проверялась
#: политика, а не совпадение с границей.
_STALE_AGE_DAYS = 12
_SEC_PER_DAY = 86400

#: Порт пробы — свой, чтобы не столкнуться с параллельным стендом.
_PORT = 8811


def _read_tail(path: Path, limit: int = 200_000) -> str:
    """Хвост текстового файла журнала. Отказ чтения — пустая строка, не исключение."""
    try:
        data = path.read_bytes()[-limit:]
    except OSError:
        return ""
    return data.decode("utf-8", errors="replace")


def _write_aged(path: Path, age_days: float, size: int = 4096) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)
    stamp = time.time() - age_days * _SEC_PER_DAY
    os.utime(path, (stamp, stamp))


def main() -> int:
    tmp_root = Path(tempfile.mkdtemp(prefix="d5_retention_"))
    log_dir = tmp_root / "logs"
    foreign_root = tmp_root / "legacy_logs"

    # Осиротевший каталог: процесса с таким именем в рецепте нет.
    stale = log_dir / "dead_recipe_process" / "app.log"
    fresh = log_dir / "dead_recipe_process" / "today.log"
    # Каталог живого процесса (в рецепте `region_pipeline` он есть).
    live_stale = log_dir / "camera_0" / "old_but_live.log"
    # Чужое дерево ВНЕ log_dir.
    foreign = foreign_root / "camera_0" / "ancient.log"

    _write_aged(stale, _STALE_AGE_DAYS)
    _write_aged(fresh, 0.01)
    _write_aged(live_stale, _STALE_AGE_DAYS)
    _write_aged(foreign, 30)

    os.environ["INSPECTOR_LOG_DIR"] = str(log_dir)
    # cwd НЕ меняем: кандидат «чужого дерева» во фреймворке ровно один —
    # `<cwd>/logs`, и первая редакция пробы уводила cwd в tmp, где этот
    # кандидат совпадал с активным каталогом и потому законно отбрасывался.
    # Проверка получалась про пустое место. Здесь стенд повторяет реальную
    # раскладку: активный каталог — временный, а настоящее дерево `logs/`
    # проекта (то самое, на 308 МБ) остаётся чужим — его обязаны НАЗВАТЬ и
    # не тронуть.
    project_logs = PROJECT_ROOT / "logs"
    project_logs_before = sum(1 for p in project_logs.rglob("*") if p.is_file()) if project_logs.is_dir() else 0

    from backend_ctl.harness import BackendHarness  # noqa: E402 — после мутации env

    checks: List[Tuple[str, bool, str]] = []
    harness = BackendHarness(with_base=True, port=_PORT)
    try:
        harness.start()
        # Уборка идёт в initialize() ПМ, то есть до готовности стенда; короткая
        # пауза — на дозапись собственных логов процессов, не на саму уборку.
        time.sleep(2.0)

        checks.append(
            (
                "просроченный файл осиротевшего каталога удалён",
                not stale.exists(),
                f"{stale} → exists={stale.exists()}",
            )
        )
        checks.append(
            (
                "свежий файл того же каталога НЕ удалён",
                fresh.exists(),
                f"{fresh} → exists={fresh.exists()}",
            )
        )
        # Приёмка плана: во ВСЁМ дереве нет файлов старше `retention_days` —
        # ни в одном подкаталоге. Прежняя редакция этой проверки требовала,
        # чтобы файл в каталоге ЖИВОГО процесса уцелел, и была красной законно:
        # 12-дневный файл живого процесса метёт его СОБСТВЕННЫЙ подметальщик,
        # и живьём «его подмёл свой» неотличимо от «в него залез глобальный».
        # Различает их только инъекция на юните (снять пропуск живых имён →
        # красные тесты), поэтому здесь судится итог, а не исполнитель.
        cutoff = time.time() - 7 * _SEC_PER_DAY
        overdue = [p for p in log_dir.rglob("*") if p.is_file() and p.stat().st_mtime < cutoff]
        checks.append(
            (
                "во всём дереве log_dir нет файлов старше retention_days=7",
                not overdue,
                f"просроченных осталось: {len(overdue)} {[str(p) for p in overdue[:3]]}",
            )
        )
        checks.append(
            (
                "чужое дерево вне log_dir НЕ удалено",
                foreign.exists(),
                f"{foreign} → exists={foreign.exists()}",
            )
        )

        # Вторая половина Р-5: назвать. Без этой проверки «не удалили» было бы
        # неотличимо от «не заметили» — а именно это и требовалось развести.
        marker = str(project_logs)
        named = [
            p for p in log_dir.rglob("*") if p.is_file() and p.suffix in (".log", ".jsonl") and marker in _read_tail(p)
        ]
        checks.append(
            (
                "настоящее дерево logs/ проекта НАЗВАНО в журнале стенда",
                bool(named),
                f"файлов с упоминанием {marker}: {len(named)} {[p.name for p in named[:3]]}",
            )
        )

        project_logs_after = sum(1 for p in project_logs.rglob("*") if p.is_file()) if project_logs.is_dir() else 0
        checks.append(
            (
                "настоящее дерево logs/ проекта НЕ тронуто",
                project_logs_after == project_logs_before,
                f"файлов было {project_logs_before}, стало {project_logs_after}",
            )
        )
    finally:
        try:
            harness.stop()
        except Exception as exc:  # noqa: BLE001 — падение teardown'а не должно съесть вердикт
            print(f"[warn] teardown: {exc}")

    ok = 0
    for name, passed, detail in checks:
        mark = "OK  " if passed else "FAIL"
        ok += int(passed)
        print(f"[{mark}] {name}: {detail}")
    print(f"\nитог: {ok}/{len(checks)}")
    print(f"каталог пробы (не удаляется, для разбора): {tmp_root}")
    return 0 if ok == len(checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
