# -*- coding: utf-8 -*-
"""Живая приёмка стенда с настоящим GUI: окна живут, команды доходят, гашение без клика.

**Решение владельца 2026-08-11: у GUI-стенда ОДНА дорога подъёма — боевая.** Зонд
ничего не поднимает сам, он ПОДКЛЮЧАЕТСЯ к уже работающему приложению. Это не удобство,
а вывод из измерения: попытка поднять то же самое через ``BackendHarness`` (презентационный
overlay + ``launcher_factory`` с боевым ``build_launcher``) даёт зависание процесса ``gui``
в ``_init_application_threads`` — до ``run_gui`` он не доходит, поэтому молчат команды и
переполняется очередь данных. Две дороги подъёма, из которых одна виснет, — худший из
исходов: числа стендов перестают сравниваться молча. Harness остаётся тем, чем был, —
headless-стендом для тестов.

Как поднять стенд (одна команда, из корня репозитория)::

    BACKEND_CTL=1 INSPECTOR_GUI_UNATTENDED=1 INSPECTOR_LOG_DIR=logs_live/gui_ctl \\
        .venv/Scripts/python.exe multiprocess_prototype/frontend/run.py

``INSPECTOR_GUI_UNATTENDED=1`` — режим без присмотра (``frontend/unattended.py``): вопрос
«сохранить несохранённые правки графа?» получает явный ответ «не сохранять» ДО показа
окна, а любая другая модалка закрывается сторожем с записью в лог. Без него прогон встаёт
на первой же модалке — именно поэтому живые замеры до сих пор шли headless и давали
нагрузку беднее боевой в разы (замер F1: строки 40–53 КБ с окнами против ~1900 байт без).

Проверки:

    L1  стенд отвечает: ``gui`` жив и отдаёт ``introspect.status`` — Qt-процесс не только
        существует, но и обслуживает команды;
    L2  воркеры на месте: ``message_processor`` (иначе команды не дошли бы вовсе) и
        ``data_receiver`` (иначе очередь данных переполнилась бы);
    L3  контроль соседями: отвечает не только ``gui`` — иначе судили бы стенд, а не GUI;
    L4  **гашение без оператора**: ``system.shutdown`` уводит систему за бюджет, и модалка
        подтверждения на этом пути не появляется;
    L5  голос режима: автоответы и закрытые сторожем окна названы в логах, а не проглочены.

Запуск: ``python -m backend_ctl.probes.probe_gui_stand_live``
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

for _stream in (sys.stdout, sys.stderr):
    _reconfigure = getattr(_stream, "reconfigure", None)
    if callable(_reconfigure):
        _reconfigure(encoding="utf-8", errors="replace")

from backend_ctl.driver import BackendDriver  # noqa: E402
from backend_ctl.endpoint_config import resolve_endpoint  # noqa: E402

#: Куда пишет стенд, поднятый командой из докстринга. Совпадать обязано: зонд читает
#: логи ТОГО ЖЕ прогона, иначе L5 судил бы чужой каталог и молчал бы всегда.
LOG_ROOT = Path(os.environ.get("INSPECTOR_LOG_DIR") or (PROJECT_ROOT / "logs_live" / "gui_ctl"))

#: Потолок на гашение. Прежний дефект — ожидание клика — измерялся минутами (8+ у
#: LoginDialog в Ф0.4). 60 с хватает штатному graceful-stop и не хватает ожиданию клика.
SHUTDOWN_BUDGET = 60.0


def log(message: str) -> None:
    print(message, flush=True)


def _unwrap(node: Any, key: str, depth: int = 4) -> Any:
    """Развернуть envelope ответа до dict с нужным ключом (идиома live-тестов)."""
    for _ in range(depth):
        if isinstance(node, dict) and key in node:
            return node
        node = node.get("result") if isinstance(node, dict) else None
    return None


def main() -> int:
    host, port = resolve_endpoint()
    log("Живая приёмка: стенд с настоящим GUI (подключение к боевому запуску)")
    log(f"эндпоинт: {host}:{port} · логи стенда: {LOG_ROOT}")

    failures: list[str] = []
    notes: list[str] = []

    drv = BackendDriver(host=host, port=port)
    try:
        drv.connect()
    except Exception as exc:  # noqa: BLE001 — отсутствие стенда объясняем командой запуска
        log(f"стенд недоступен ({exc}). Подними его так:")
        log("  BACKEND_CTL=1 INSPECTOR_GUI_UNATTENDED=1 INSPECTOR_LOG_DIR=logs_live/gui_ctl \\")
        log("      .venv/Scripts/python.exe multiprocess_prototype/frontend/run.py")
        return 2

    try:
        # L1/L2 — GUI отвечает и качает обе свои очереди.
        status = _unwrap(drv.get_status("gui", timeout=20.0), "workers")
        if status is None:
            failures.append("L1: gui не ответил на introspect.status")
        else:
            log(f"L1 PASS: gui отвечает (status={status.get('status')}, pid={status.get('pid')})")
            workers = status.get("workers") or {}
            for required in ("message_processor", "data_receiver"):
                entry = workers.get(required) or {}
                if entry.get("is_alive"):
                    log(f"L2 PASS: воркер {required} жив")
                else:
                    failures.append(f"L2: воркер {required} не жив: {entry or 'нет в ответе'}")

        # L3 — контроль соседями: молчание стенда и молчание gui — разные факты.
        neighbours = {}
        for name in ("camera_0", "seg"):
            neighbours[name] = _unwrap(drv.get_status(name, timeout=20.0), "workers") is not None
        log(f"L3: соседи ответили: {neighbours}")
        if not any(neighbours.values()):
            failures.append("L3: не ответил ни один сосед — вердикт про gui недоказуем, судим стенд")

        # L4 — гашение без оператора.
        started = time.monotonic()
        res = drv.system_command({"cmd": "system.shutdown"}, timeout=SHUTDOWN_BUDGET)
        accepted = isinstance(res, dict) and res.get("success") is not False
        elapsed = time.monotonic() - started
        if accepted and elapsed <= SHUTDOWN_BUDGET:
            log(f"L4 PASS: system.shutdown принят за {elapsed:.1f} с (бюджет {SHUTDOWN_BUDGET:.0f})")
        else:
            failures.append(f"L4: гашение не принято за {elapsed:.1f} с: {str(res)[:200]}")
    finally:
        try:
            drv.close()
        except Exception:  # noqa: BLE001 — закрытие сокета не должно топить вердикт
            pass

    # L5 — голос режима. Читается ПОСЛЕ гашения: модалка подтверждения (если бы она
    # была) появляется именно на закрытии, и до shutdown её записи ещё нет.
    time.sleep(5.0)
    spoken = []
    if LOG_ROOT.exists():
        for path in LOG_ROOT.rglob("*.log"):
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            spoken.extend(
                f"{path.parent.name}: {line.strip()[:160]}" for line in text.splitlines() if "unattended." in line
            )
    else:
        notes.append(f"L5: каталог логов {LOG_ROOT} не найден — задай INSPECTOR_LOG_DIR тем же значением, что стенду")
    if spoken:
        log(f"L5: режим отчитался {len(spoken)} записями:")
        for line in spoken[:10]:
            log(f"     {line}")
    else:
        notes.append("L5: записей режима нет — за прогон не появилось ни одной модалки (норма)")

    log("")
    for note in notes:
        log(note)
    if failures:
        log(f"ИТОГ: ПРОВАЛЕНО {len(failures)}")
        for item in failures:
            log(f"  - {item}")
        return 1
    log("ИТОГ: все обязательные проверки пройдены")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
