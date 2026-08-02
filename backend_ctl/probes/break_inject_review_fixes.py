# -*- coding: utf-8 -*-
"""Слом-инъекция по гарантиям фиксов ревью Fable (находки 1, 2, R1).

Каждая инъекция откатывает РОВНО одну гарантию текстовой заплатой, гоняет целевые
тесты и печатает, кто умер. Файлы восстанавливаются из бэкапа всегда.

**Прогноз объявлен ЗДЕСЬ, до прогона** — в ``EXPECTED``. Расхождение в любую
сторону — находка: либо тест не сторожит то, что заявлено, либо прогноз неверен, и
разбирать надо оба случая.

Запуск: ``python -m backend_ctl.probes.break_inject_review_fixes``.
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
BROKER = ROOT / "multiprocess_framework/modules/process_manager_module/process/observability_broker.py"
SOCK = ROOT / "multiprocess_framework/modules/router_module/channels/socket_channel.py"

TESTS = [
    "multiprocess_framework/modules/process_manager_module/tests/test_ready_gate_redelivery.py",
    "multiprocess_framework/modules/process_manager_module/tests/test_observability_broker.py",
    "multiprocess_framework/modules/process_manager_module/tests/test_wire_reissue.py",
    "multiprocess_framework/modules/router_module/tests/test_socket_channel.py",
]


def rf1(text: str) -> str:
    """Поколения нет — досылка не знает, что её конверт устарел (находка 1).

    Снимается ИМЕННО аргумент, а не одна из проверок: у ``still_relevant`` три
    точки исполнения (вход, срезы цикла, пост-ожидание), и частичная инъекция
    даёт ложный «зелёный» — урок I-7 сквозного ревью Ф5.
    """
    return text.replace(
        "                still_relevant=lambda m=marks: self._broadcast_envelope_relevant(m),\n",
        "",
    )


def rf2(text: str) -> str:
    """Нет перепроверки ПОСЛЕ ожидания — дождавшийся поток везёт прошлое."""
    return text.replace(
        """            if still_relevant is not None and not still_relevant():
                self._log_info(f"[ready-gate:{label}] '{name}': досылка снята (рассылка того же типа ушла позже)")
                return
            if not ready:""",
        "            if not ready:",
    )


def rf3(text: str) -> str:
    """Адресный telemetry-replay снова идёт мимо гейта (находка 2)."""
    return text.replace(
        """                deferred = self._run_when_child_ready(
                    target,
                    lambda t=target, p=payload: self._send_child_command(t, "telemetry.reconfigure", p),
                    label="telemetry-replay",
                    deadline_s=self._late_delivery_deadline() or 15.0,
                )""",
        "                deferred = False  # RF3\n"
        '                self._send_child_command(target, "telemetry.reconfigure", payload)',
    )


def rf4(text: str) -> str:
    """wire re-issue снова шлёт немедленно и метит провод активным авансом."""
    return text.replace(
        """            deferred = self._run_when_child_ready(
                process_name,
                _do,
                label="wire-reissue",
                deadline_s=self._late_delivery_deadline() or 15.0,
            )""",
        "            deferred = False  # RF4\n            _do()",
    )


def rf5(text: str) -> str:
    """Снятие подписчика по закрытию сессии не работает (R1)."""
    return text.replace(
        '        sid = str(session_id or "").strip()\n        if not sid:\n            return []',
        "        return []  # RF5\n",
    )


def rf6(text: str) -> str:
    """Привязка сессии снова только при session_isolation — фикс R1 мёртв в дефолте."""
    return text.replace(
        '        sid = msg.get("session")\n        if sid:\n            self._bind_session(str(sid), client)',
        "        if self._session_isolation:  # RF6\n"
        '            sid = msg.get("session")\n'
        "            if sid:\n"
        "                self._bind_session(str(sid), client)",
    )


def rf7(text: str) -> str:
    """Канал не оповещает о закрытии сессии вовсе."""
    return text.replace(
        "        for sid in closed_sessions:\n"
        "            if self._on_session_closed is None:\n                continue",
        "        for sid in []:  # RF7\n            if self._on_session_closed is None:\n                continue",
    )


def rf8(text: str) -> str:
    """ФР-1: дорожка поколений снова по ИМЕНИ команды — конверты одной команды слиты."""
    return text.replace(
        "            return tuple(sorted(str(key) for key in data))",
        "            return (ProcessManagerProcess._EMPTY_ENVELOPE_KEY,)  # RF8",
    )


def rf9(text: str) -> str:
    """ФР-1: у пустого конверта нет своей дорожки — он не гасит даже сам себя."""
    return text.replace(
        "        return (ProcessManagerProcess._EMPTY_ENVELOPE_KEY,)\n",
        "        return ()  # RF9\n",
    )


def rf10(text: str) -> str:
    """ФР-1: частичное перекрытие считается полным (``any`` → ``all``)."""
    return text.replace(
        "            return any(self._broadcast_generations.get(lane, 0) == generation for lane, generation in marks.items())",  # noqa: E501
        "            return all(self._broadcast_generations.get(lane, 0) == generation for lane, generation in marks.items())  # RF10",  # noqa: E501
    )


INJECTIONS = [
    ("RF1 поколения рассылки нет", PM, rf1),
    ("RF2 нет перепроверки после ожидания", PM, rf2),
    ("RF3 адресный telemetry мимо гейта", PM, rf3),
    ("RF4 wire re-issue мимо гейта", PM, rf4),
    ("RF5 forget_session не снимает", BROKER, rf5),
    ("RF6 привязка сессии только при изоляции", SOCK, rf6),
    ("RF7 канал молчит о закрытии сессии", SOCK, rf7),
    ("RF8 дорожка поколений снова по имени команды", PM, rf8),
    ("RF9 у пустого конверта нет своей дорожки", PM, rf9),
    ("RF10 частичное перекрытие считается полным", PM, rf10),
]

# Прогноз ДО прогона.
EXPECTED: dict[str, set[str]] = {
    # ФР-1 расширил набор: снятие актуальности сторожат уже не 3, а 7 тестов.
    # Переживают ровно те два, где ОБА конверта актуальны по построению —
    # проверка снятия к ним просто не применяется.
    "RF1 поколения рассылки нет": {
        "test_stale_envelope_is_dropped_when_a_newer_broadcast_follows",
        "test_stale_waiter_stops_early_instead_of_burning_the_deadline",
        "test_a_fresher_broadcast_of_another_command_does_not_cancel_this_one",
        "test_two_empty_envelopes_still_collapse_to_the_last_one",
        "test_two_switch_envelopes_still_collapse_to_the_last_one",
        "test_a_covering_envelope_cancels_the_bare_pending_one",
        "test_concurrent_broadcasts_of_the_same_content_collapse_to_one",
    },
    # Дождавшийся поток везёт прошлое; ожидатель на МЁРТВОМ событии уходит по
    # проверке внутри цикла, поэтому два «стейл»-теста переживают. Умирают те,
    # где событие ВЗВОДИТСЯ и снятие может сработать только пост-проверкой.
    "RF2 нет перепроверки после ожидания": {
        "test_a_fresher_broadcast_of_another_command_does_not_cancel_this_one",
        "test_two_empty_envelopes_still_collapse_to_the_last_one",
        "test_two_switch_envelopes_still_collapse_to_the_last_one",
        "test_a_covering_envelope_cancels_the_bare_pending_one",
        "test_concurrent_broadcasts_of_the_same_content_collapse_to_one",
    },
    "RF3 адресный telemetry мимо гейта": {
        "test_addressed_telemetry_replay_waits_for_readiness",
    },
    "RF4 wire re-issue мимо гейта": {
        "test_wire_reissue_waits_and_marks_active_only_after_send",
    },
    "RF5 forget_session не снимает": {
        "test_session_close_drops_exactly_that_subscriber",
        "test_reconnect_cycles_do_not_accumulate_intents",
        "test_dead_subscriber_is_not_replayed_to_fresh_incarnations",
    },
    # Тесты канала с isolation=True переживают — их привязка работает; умирает
    # ровно тот, что проверяет ДЕФОЛТНЫЙ режим (дыра, найденная живым прогоном).
    "RF6 привязка сессии только при изоляции": {
        "test_signal_fires_in_the_DEFAULT_mode_too",
    },
    "RF7 канал молчит о закрытии сессии": {
        "test_closed_session_is_reported_once",
        "test_signal_fires_in_the_DEFAULT_mode_too",
    },
    # Ровно дефект ФР-1: конверты одной команды снова на общей дорожке. Умирают
    # два теста — репро находки и его зеркало (бедный конверт гасит богатый).
    # Все «одинаковое содержимое гасится» переживают: там дорожка и так одна.
    "RF8 дорожка поколений снова по имени команды": {
        "test_a_later_empty_envelope_does_not_cancel_the_switch_envelope",
        "test_a_partial_envelope_does_not_cancel_the_richer_pending_one",
    },
    # Пустой конверт перестаёт гасить себя (и гаситься) — умирает ровно тот тест,
    # что сторожит «стейл для ОДИНАКОВОГО содержимого по-прежнему снимается».
    "RF9 у пустого конверта нет своей дорожки": {
        "test_two_empty_envelopes_still_collapse_to_the_last_one",
    },
    # `all` вместо `any`: конверт, перекрытый по ОДНОМУ ключу, снимается целиком.
    "RF10 частичное перекрытие считается полным": {
        "test_a_partial_envelope_does_not_cancel_the_richer_pending_one",
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


def main(argv: list[str] | None = None) -> int:
    # Фильтр по ID (``... RF8 RF9``) — чтобы правка одной гарантии не требовала
    # часового прогона всех инъекций. Без аргументов гоняются все. Сверка по
    # ПЕРВОМУ слову, а не по префиксу: «RF1» иначе цепляло бы и «RF10».
    wanted = set(argv or [])
    mismatches = 0
    for title, path, patch in INJECTIONS:
        if wanted and title.split(maxsplit=1)[0] not in wanted:
            continue
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
        extra, missing = failed - expected, expected - failed
        if extra or missing:
            mismatches += 1
        print(f"{title}: {'СОВПАЛО' if not extra and not missing else 'РАСХОЖДЕНИЕ'} умерли={len(failed)}", flush=True)
        if missing:
            print(f"    выжили вопреки прогнозу: {sorted(missing)}")
        if extra:
            print(f"    умерли сверх прогноза:   {sorted(extra)}")

    code, failed = run_tests()
    print(f"\nконтроль (без слома): exit={code} умерли={sorted(failed) or 'НИКТО'}")
    print(f"расхождений с прогнозом: {mismatches}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
