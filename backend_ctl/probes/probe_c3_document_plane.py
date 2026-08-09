# -*- coding: utf-8 -*-
"""Прогон C3 — «документ без приёмника» и «сток отказал» на НАСТОЯЩЕМ хранилище.

Стенд не поднимается: вопрос про учёт потерь третьей плоскости, и отвечает на
него настоящий `DocumentStore` поверх настоящего SQLite. Дубль стока в тестах
отказывает по команде — здесь отказ **не подстроен**: соединение с БД
закрывается, и запись падает так, как падала бы на живом сбое хранилища.

Три случая, которые обязаны РАЗЛИЧАТЬСЯ в readback'е:

    1. плоскость не объявлена  → documents.without_sink растёт, dropped=0
    2. сток объявлен и работает → оба нуля, тишина
    3. сток объявлен и отказал  → documents.dropped растёт, without_sink=0

Основание — major-10 приёмочного ревью 2026-08-09: у записей «приёмника нет
вовсе» названо четвёртым классом потери, а документ исчезал молча; счётчик
``DocumentStore.dropped`` рос, и прочитать его снаружи было нечем.

Запуск: ``python -m backend_ctl.probes.probe_c3_document_plane``
"""

from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any, List

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

for _stream in (sys.stdout, sys.stderr):
    _reconfigure = getattr(_stream, "reconfigure", None)
    if callable(_reconfigure):
        _reconfigure(encoding="utf-8", errors="replace")

FAILURES: List[str] = []


def log(msg: str) -> None:
    print(msg, flush=True)


def check(ok: bool, title: str, evidence: str) -> None:
    log(f"  [{'PASS' if ok else 'FAIL'}] {title}\n         {evidence}")
    if not ok:
        FAILURES.append(f"{title}: {evidence}")


class _Services:
    def __init__(self) -> None:
        self.name = "probe_c3"
        self.said: List[str] = []

    def _say(self, message: str, **kw: Any) -> None:
        self.said.append(str(message))

    log_debug = _say
    log_info = _say
    log_warning = _say
    log_error = _say
    log_critical = _say


def main() -> int:
    from multiprocess_framework.modules.process_module.managers.observability_wiring import (
        DOCUMENT_SINK_ATTR,
        document_plane_report,
    )
    from multiprocess_framework.modules.process_module.plugins.base import PluginContext
    from Services.documents.wiring import make_document_sink

    root = Path(tempfile.mkdtemp(prefix="probe_c3_"))
    log("=" * 78)
    log("Прогон C3 — плоскость документов: потери названы и различимы")
    log(f"каталог: {root}")
    log("=" * 78)

    # --- 1. плоскости нет вовсе -------------------------------------------
    log("\n--- 1: плоскость НЕ объявлена ---")
    svc = _Services()
    ctx = PluginContext(services=svc, plugin_name="verdict_plugin")
    for _ in range(3):
        ctx.write_document("verdict", "деталь бракована", source="line_7")
    report = document_plane_report(svc)["documents"]
    spoken = [line for line in svc.said if "documents" in line]
    check(
        report["without_sink"] == 3 and report["declared"] is False and report["dropped"] == 0,
        "три потерянных вердикта посчитаны как «приёмника нет»",
        f"documents={report}",
    )
    check(
        len(spoken) == 1 and "verdict" in spoken[0] and "line_7" in spoken[0],
        "первый случай сказан ОДИН раз и с адресом (kind + source)",
        f"строк: {len(spoken)}; первая: {spoken[0][:150] if spoken else '—'}",
    )

    # --- 2. настоящий сток, здоровый путь ---------------------------------
    log("\n--- 2: настоящий DocumentStore, здоровый путь ---")
    store = make_document_sink({"db_path": str(root / "documents.db")})
    svc2 = _Services()
    setattr(svc2, DOCUMENT_SINK_ATTR, store)
    ctx2 = PluginContext(services=svc2, plugin_name="verdict_plugin")
    ok = ctx2.write_document("verdict", "годная", source="line_7", confidence=0.97)
    report2 = document_plane_report(svc2)["documents"]
    check(
        ok is True and report2 == {"declared": True, "without_sink": 0, "dropped": 0},
        "здоровый путь: документ записан, счётчики нулевые, тишина",
        f"append={ok}, documents={report2}, сказано={len(svc2.said)}",
    )

    # --- 3. тот же сток, но хранилище отказало ----------------------------
    log("\n--- 3: у настоящего стока отказало хранилище ---")
    store.close()  # соединение закрыто — дальше insert падает по-настоящему
    for _ in range(3):
        ctx2.write_document("verdict", "деталь бракована", source="line_7")
    report3 = document_plane_report(svc2)["documents"]
    spoken3 = [line for line in svc2.said if "documents" in line]
    check(
        report3["dropped"] == 3 and report3["without_sink"] == 0,
        "отказ стока посчитан ОТДЕЛЬНО от «плоскости нет»",
        f"documents={report3}",
    )
    check(
        report3["declared"] is True,
        "плоскость по-прежнему объявлена — диагноз «чинить базу», а не «править конфиг»",
        f"declared={report3['declared']}",
    )
    check(
        len(spoken3) == 1 and "сток отказал" in spoken3[0],
        "отказ сказан ОДИН раз, дальше молча со счётчиком",
        f"строк: {len(spoken3)}; первая: {spoken3[0][:150] if spoken3 else '—'}",
    )

    shutil.rmtree(root, ignore_errors=True)
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
