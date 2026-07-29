# -*- coding: utf-8 -*-
"""Слом-инъекция по гарантиям резидуала 5.11-R4 (readiness-гейт рассылки).

Каждая инъекция откатывает РОВНО одну гарантию текстовой заплатой, гоняет
целевые тесты и печатает, кто умер. Файлы восстанавливаются из бэкапа всегда.

**Прогноз объявлен ЗДЕСЬ, до прогона** — в ``EXPECTED``. Скрипт сам сверяет
факт с прогнозом и печатает расхождения: тест, переживший собственный слом, не
существует, а расхождение в любую сторону — находка, а не помеха.

Запуск: ``python -m backend_ctl.probes.break_inject_r4_ready_gate``.
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

TESTS = [
    "multiprocess_framework/modules/process_manager_module/tests/test_ready_gate_redelivery.py",
    "multiprocess_framework/modules/process_manager_module/tests/test_observability_broker.py",
]


def rg1(text: str) -> str:
    """Досылки нет вовсе — поведение до R4."""
    return text.replace(
        "        reached = int(comm.broadcast(msg, exclude_self=True))\n"
        "        self._redeliver_to_unready_children(command, data, queue_type=queue_type)\n"
        "        return reached",
        "        return int(comm.broadcast(msg, exclude_self=True))  # RG1",
    )


def rg2(text: str) -> str:
    """Отбора по готовности нет — досылка уходит ВСЕМ подряд."""
    return text.replace(
        "            event = self._child_ready_event(name)\n"
        "            if event is None or event.is_set():\n"
        "                continue\n",
        "            event = self._child_ready_event(name)  # RG2\n",
    )


def rg3(text: str) -> str:
    """Снимок payload не делается — уезжает живая ссылка вызывающего."""
    return text.replace(
        "                snapshot = copy.deepcopy(data)",
        "                snapshot = data  # RG3",
    )


def rg4(text: str) -> str:
    """Ожидание готовности синхронное — гейт блокирует message-loop."""
    return text.replace(
        """        threading.Thread(
            target=self._run_child_action_after_ready,
            args=(name, action, label, event, deadline_s, still_relevant),
            name=f"ready-gate-{label}-{name}",
            daemon=True,
        ).start()""",
        "        self._run_child_action_after_ready(name, action, label, event, deadline_s, still_relevant)  # RG4",
    )


def rg5(text: str) -> str:
    """По истечении дедлайна действие НЕ выполняется (молчаливый отказ)."""
    return text.replace(
        '                    "действую вслепую (команда может не застать обработчик)"\n                )',
        '                    "действую вслепую (команда может не застать обработчик)"\n'
        "                )\n                return  # RG5",
    )


def rg6(text: str) -> str:
    """Выключатель не работает — нулевой дедлайн игнорируется."""
    return text.replace(
        "        deadline = self._late_delivery_deadline()\n        if deadline <= 0:\n            return []",
        "        deadline = self._late_delivery_deadline() or 15.0  # RG6",
    )


def rg7(text: str) -> str:
    """Регресс 5.11: раздача подписок снова идёт мимо гейта, сразу."""
    return text.replace(
        '        timeout = self.get_config("observability_replay_ready_timeout_s")\n'
        "        self._run_when_child_ready(\n"
        "            name,\n"
        '            lambda: self._replay_observability_subscriptions("instance.started", target=name),\n'
        '            label="observability",\n'
        "            deadline_s=30.0 if timeout is None else float(timeout),\n"
        "        )",
        '        self._replay_observability_subscriptions("instance.started", target=name)  # RG7',
    )


INJECTIONS = [
    ("RG1 досылки нет вовсе", PM, rg1),
    ("RG2 досылка всем подряд", PM, rg2),
    ("RG3 payload без снимка", PM, rg3),
    ("RG4 ожидание синхронное", PM, rg4),
    ("RG5 по дедлайну молчать", PM, rg5),
    ("RG6 выключатель не работает", PM, rg6),
    ("RG7 раздача подписок мимо гейта", PM, rg7),
]

# Прогноз ДО прогона: какие тесты обязана убить каждая инъекция.
EXPECTED: dict[str, set[str]] = {
    "RG1 досылки нет вовсе": {
        "test_unready_child_gets_the_envelope_after_it_declares_readiness",
        "test_only_unready_children_are_redelivered",
        "test_deadline_expiry_redelivers_anyway_and_says_so",
        "test_redelivered_payload_is_a_snapshot_of_what_was_broadcast",
        "test_routing_refresh_is_redelivered",
        "test_telemetry_reconfigure_is_redelivered",
        "test_config_reload_is_redelivered",
        # Добавлены после фиксов ревью: тесты «досылка не везёт прошлое» тоже
        # опираются на существование досылки — без неё им нечего сторожить.
        "test_stale_envelope_is_dropped_when_a_newer_broadcast_follows",
        "test_stale_waiter_stops_early_instead_of_burning_the_deadline",
        "test_generations_are_per_command",
    },
    # Прогон 1 добавил сюда тест брокера 5.11: он считает конверты, а досылка
    # всем подряд даёт лишний. Прогноз был неполон — гарантия настоящая.
    "RG2 досылка всем подряд": {
        "test_ready_child_gets_exactly_one_envelope",
        "test_registry_without_ready_signal_keeps_the_old_behaviour",
        "test_only_unready_children_are_redelivered",
        "test_command_subscribe_all_reaches_children_through_pm_broadcast",
    },
    "RG3 payload без снимка": {
        "test_redelivered_payload_is_a_snapshot_of_what_was_broadcast",
    },
    # Три switch-теста добавлены после прогона 1: они проверяют «до готовности —
    # тишина», а синхронное ожидание доставляет ДО возврата из вызова.
    "RG4 ожидание синхронное": {
        "test_broadcast_returns_immediately_when_a_child_is_not_ready",
        "test_unready_child_gets_the_envelope_after_it_declares_readiness",
        "test_seam_does_not_block_the_message_loop",
        "test_replay_held_back_until_the_instance_declares_readiness",
        "test_replay_still_waits_for_readiness",
        "test_routing_refresh_is_redelivered",
        "test_telemetry_reconfigure_is_redelivered",
        "test_config_reload_is_redelivered",
        # Добавлены после фиксов ревью: все они проверяют «до готовности — тишина»,
        # а синхронное ожидание доставляет ДО возврата из вызова.
        "test_stale_envelope_is_dropped_when_a_newer_broadcast_follows",
        "test_stale_waiter_stops_early_instead_of_burning_the_deadline",
        "test_generations_are_per_command",
        "test_addressed_telemetry_replay_waits_for_readiness",
        "test_wire_reissue_waits_and_marks_active_only_after_send",
    },
    "RG5 по дедлайну молчать": {
        "test_deadline_expiry_redelivers_anyway_and_says_so",
        "test_deadline_expiry_still_delivers_and_says_so",
    },
    "RG6 выключатель не работает": {
        "test_zero_timeout_disables_redelivery",
    },
    # Прогон 1 снял отсюда «шов не блокирует message-loop»: он и не мог умереть —
    # инъекция УБИРАЕТ ожидание, а тест сторожит его отсутствие. Ошибка прогноза,
    # не дыра в тесте.
    "RG7 раздача подписок мимо гейта": {
        "test_replay_held_back_until_the_instance_declares_readiness",
        "test_replay_still_waits_for_readiness",
        "test_deadline_expiry_still_delivers_and_says_so",
    },
}


def run_tests() -> tuple[int, set[str]]:
    proc = subprocess.run(  # nosec B603 — аргументы литеральные, внешнего ввода нет
        [str(PY), "-m", "pytest", *TESTS, "-q"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    out = proc.stdout + proc.stderr
    failed = set(re.findall(r"FAILED [^\s:]+::[^\s:]+::(\w+)", out))
    failed |= set(re.findall(r"FAILED [^\s:]+::(test_\w+)", out))
    return proc.returncode, failed


def main() -> int:
    mismatches = 0
    for title, path, patch in INJECTIONS:
        backup = path.with_suffix(path.suffix + ".bak")
        shutil.copy2(path, backup)
        try:
            original = path.read_text(encoding="utf-8")
            broken = patch(original)
            if broken == original:
                print(f"{title}: ЗАПЛАТА НЕ ПРИМЕНИЛАСЬ — инъекция недействительна")
                mismatches += 1
                continue
            path.write_text(broken, encoding="utf-8")
            _code, failed = run_tests()
        finally:
            shutil.copy2(backup, path)
            backup.unlink(missing_ok=True)
        expected = EXPECTED.get(title, set())
        extra = failed - expected
        missing = expected - failed
        verdict = "СОВПАЛО" if not extra and not missing else "РАСХОЖДЕНИЕ"
        if extra or missing:
            mismatches += 1
        print(f"{title}: {verdict} умерли={len(failed)}", flush=True)
        if missing:
            print(f"    выжили вопреки прогнозу: {sorted(missing)}")
        if extra:
            print(f"    умерли сверх прогноза:   {sorted(extra)}")

    code, failed = run_tests()
    print(f"\nконтроль (без слома): exit={code} умерли={sorted(failed) or 'НИКТО'}")
    print(f"расхождений с прогнозом: {mismatches}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
