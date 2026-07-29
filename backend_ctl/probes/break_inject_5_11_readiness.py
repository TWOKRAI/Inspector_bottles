# -*- coding: utf-8 -*-
"""Слом-инъекция по гарантиям правки 5.11 (readiness-гейт раздачи).

Каждая инъекция откатывает РОВНО одну гарантию текстовой заплатой, гоняет
целевые тесты и печатает, кто умер. Файлы восстанавливаются из бэкапа всегда.

Ожидаемый набор умерших объявляется ДО прогона — иначе это не доказательство,
а отчёт. Прогон 2026-07-29: 6 инъекций, 6/6 совпали с прогнозом.

Запуск: ``python -m backend_ctl.probes.break_inject_5_11_readiness``.
Заплаты текстовые: после правки кода под ними они перестанут применяться и
скажут об этом («ЗАПЛАТА НЕ ПРИМЕНИЛАСЬ») — это сигнал обновить их, а не
считать гарантию проверенной.
"""

from __future__ import annotations

import re
import shutil
import subprocess  # nosec B404 — dev-утилита: гоняет pytest проекта, как scripts/
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PY = ROOT / ".venv" / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")

PM = ROOT / "multiprocess_framework/modules/process_manager_module/process/process_manager_process.py"
RUNNER = ROOT / "multiprocess_framework/modules/process_manager_module/runner/process_runner.py"
PMOD = ROOT / "multiprocess_framework/modules/process_module/core/process_module.py"

TESTS = [
    "multiprocess_framework/modules/process_manager_module/tests/test_process_runner.py",
    "multiprocess_framework/modules/process_manager_module/tests/test_observability_broker.py",
    "multiprocess_framework/modules/process_module/tests/test_process_module.py",
]


def br1(text: str) -> str:
    """Готовность объявляется ДО регистрации команд."""
    text = text.replace(
        '        self._log_info(f"Process \'{self.name}\' started", module="lifecycle")',
        '        self._log_info(f"Process \'{self.name}\' started", module="lifecycle")\n        pass  # BR1',
    )
    # перенос вызова в самое начало run()
    text = text.replace(
        """        self._announce_ready()""",
        "",
    )
    return text.replace(
        '''    def run(self):
        """Запуск процесса — статус RUNNING, старт воркеров, heartbeat."""
        self.update_process_state(status=ProcessStatus.RUNNING.value)''',
        '''    def run(self):
        """Запуск процесса — статус RUNNING, старт воркеров, heartbeat."""
        self._announce_ready()  # BR1: объявляем ДО регистрации команд
        self.update_process_state(status=ProcessStatus.RUNNING.value)''',
    )


def br2(text: str) -> str:
    """Runner снова взводит событие сам (прежний контракт Ф3.2)."""
    return text.replace(
        '                attach = getattr(process_instance, "attach_ready_event", None)',
        "                ready_event.set()  # BR2\n"
        '                attach = getattr(process_instance, "attach_ready_event", None)',
    )


def br3(text: str) -> str:
    """Гейта нет — раздача сразу со шва (поведение до правки)."""
    return text.replace(
        "        started[name] = time.time()\n        self._replay_observability_when_ready(name)",
        "        started[name] = time.time()\n"
        '        self._replay_observability_subscriptions("instance.started", target=name)  # BR3',
    )


def br4(text: str) -> str:
    """По истечении дедлайна раздача НЕ идёт (молчаливый отказ).

    После резидуала 5.11-R4 ожидание живёт в общем ``_run_child_action_after_ready``:
    заплата бьёт по нему, а гарантия у 5.11 и R4 теперь буквально одна.
    """
    return text.replace(
        '                    "действую вслепую (команда может не застать обработчик)"\n                )',
        '                    "действую вслепую (команда может не застать обработчик)"\n'
        "                )\n                return  # BR4",
    )


def br5(text: str) -> str:
    """Guard «намерений нет» снят — поток заводится на каждом старте."""
    return text.replace(
        "        if broker is None or not broker.subscriber_names():\n"
        "            # Намерений нет — ни потока, ни раздачи: платить за них на КАЖДОМ\n"
        "            # старте процесса не за что.\n"
        "            return",
        "        if False:  # BR5\n            return",
    )


def br6(text: str) -> str:
    """Ожидание готовности синхронное — шов блокирует message-loop.

    Цель переехала в общий примитив (см. :func:`br4`).
    """
    return text.replace(
        """        threading.Thread(
            target=self._run_child_action_after_ready,
            args=(name, action, label, event, deadline_s),
            name=f"ready-gate-{label}-{name}",
            daemon=True,
        ).start()""",
        "        self._run_child_action_after_ready(name, action, label, event, deadline_s)  # BR6",
    )


INJECTIONS = [
    ("BR1 готовность до регистрации команд", PMOD, br1),
    ("BR2 runner взводит событие сам", RUNNER, br2),
    ("BR3 гейта нет — раздача сразу", PM, br3),
    ("BR4 по дедлайну не раздавать", PM, br4),
    ("BR5 guard «нет подписчиков» снят", PM, br5),
    ("BR6 ожидание синхронное", PM, br6),
]


def run_tests() -> tuple[int, list[str]]:
    proc = subprocess.run(  # nosec B603 — аргументы литеральные, внешнего ввода нет
        [str(PY), "-m", "pytest", *TESTS, "-q"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    out = proc.stdout + proc.stderr
    failed = sorted(set(re.findall(r"FAILED [^\s:]+::[^\s:]+::(\w+)", out)))
    if not failed:
        failed = sorted(set(re.findall(r"FAILED [^\s:]+::(\w+)", out)))
    return proc.returncode, failed


def main() -> int:
    for title, path, patch in INJECTIONS:
        backup = path.with_suffix(path.suffix + ".bak")
        shutil.copy2(path, backup)
        try:
            original = path.read_text(encoding="utf-8")
            broken = patch(original)
            if broken == original:
                print(f"{title}: ЗАПЛАТА НЕ ПРИМЕНИЛАСЬ — инъекция недействительна")
                continue
            path.write_text(broken, encoding="utf-8")
            code, failed = run_tests()
            print(f"{title}: exit={code} умерли={failed or 'НИКТО'}", flush=True)
        finally:
            shutil.copy2(backup, path)
            backup.unlink(missing_ok=True)
    code, failed = run_tests()
    print(f"контроль (без слома): exit={code} умерли={failed or 'НИКТО'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
