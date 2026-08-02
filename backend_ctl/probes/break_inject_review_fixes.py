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


def rf11(text: str) -> str:
    """B-5-1: очередь-на-адресата снова становится потоком-на-действие — гонка порядка.

    Одна точка правила — маршрутизация в ``_run_when_child_ready``: все четыре
    вызывающих гейт идут через неё, поэтому одной инъекции хватает, чтобы снять
    упорядочивание для ЛЮБОЙ пары команд. Возврат к независимым daemon-потокам
    (модель до фикса): два действия одному ребёнку доживают до готовности без
    очереди и гонят порядок доставки.
    """
    return text.replace(
        """            busy = name in self._child_action_running
            deliver_now = not busy and (event is None or event.is_set())
            if not deliver_now:
                self._child_action_pipelines.setdefault(name, deque()).append(
                    (action, label, event, deadline_s, still_relevant)
                )
                if name not in self._child_action_running:
                    self._child_action_running.add(name)
                    start_worker = True
        if deliver_now:
            action()
            return False
        if start_worker:
            threading.Thread(
                target=self._drain_child_actions,
                args=(name,),
                name=f"ready-gate-{name}",
                daemon=True,
            ).start()
        return True""",
        """            busy = name in self._child_action_running  # noqa: F841
            deliver_now = not busy and (event is None or event.is_set())  # noqa: F841
        # RF11: поток-на-действие вместо очереди-на-адресата — гонка порядка
        if event is None or event.is_set():
            action()
            return False
        threading.Thread(
            target=self._run_child_action_after_ready,
            args=(name, action, label, event, deadline_s, still_relevant),
            name=f"ready-gate-{name}",
            daemon=True,
        ).start()
        return True""",
    )


def rf12(text: str) -> str:
    """B-5-1: forget_subscriber снова молчит детям — форвардер-сирота на каждом ребёнке."""
    return text.replace(
        "            self._fan_out(key, UNSUBSCRIBE_COMMAND, reason=REASON_COMMAND)\n",
        "",
    )


def rf13(text: str) -> str:
    """B-5-1: forget_session снова молчит детям — форвардеры мёртвой сессии живут."""
    return text.replace(
        """        for name in doomed:
            self._fan_out(name, UNSUBSCRIBE_COMMAND, reason=REASON_COMMAND)""",
        """        for name in []:  # RF13: снятие не рассылается детям
            self._fan_out(name, UNSUBSCRIBE_COMMAND, reason=REASON_COMMAND)""",
    )


def rf14(text: str) -> str:
    """Шов очереди: дренаж снова ждёт сигнал безусловно — действие с ``None`` теряется.

    Очередь завела путь, которого до неё не существовало: действие без сигнала
    готовности попадает в очередь (чтобы не обогнать её), а дренаж звал
    ``event.wait`` на ``None`` — падал в ``except`` и ронял действие, оставив одну
    строку в логе. Класс — «проглоченный сбой»: снаружи одна команда доехала,
    вторая исчезла.
    """
    return text.replace(
        "            ready = event is None\n            while not ready:",
        "            ready = False  # RF14: дренаж снова ждёт сигнал безусловно\n            while not ready:",
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
    ("RF11 очередь-на-адресата снова поток-на-действие", PM, rf11),
    ("RF12 forget_subscriber не рассылает снятие", BROKER, rf12),
    ("RF13 forget_session не рассылает снятие", BROKER, rf13),
    ("RF14 дренаж очереди ждёт сигнал безусловно", PM, rf14),
]

# Прогноз ДО прогона.
EXPECTED: dict[str, set[str]] = {
    # ФР-1 расширил набор: снятие актуальности сторожат уже не 3, а 7 тестов.
    # Переживают ровно те два, где ОБА конверта актуальны по построению —
    # проверка снятия к ним просто не применяется.
    "RF1 поколения рассылки нет": {
        "test_stale_envelope_is_dropped_when_a_newer_broadcast_follows",
        "test_stale_item_is_dropped_early_instead_of_burning_the_deadline",
        "test_a_fresher_broadcast_of_another_command_does_not_cancel_this_one",
        "test_two_empty_envelopes_still_collapse_to_the_last_one",
        "test_two_switch_envelopes_still_collapse_to_the_last_one",
        "test_a_covering_envelope_cancels_the_bare_pending_one",
        "test_concurrent_broadcasts_of_the_same_content_collapse_to_one",
    },
    # Дождавшийся поток везёт прошлое; ожидатель на МЁРТВОМ событии уходит по
    # проверке внутри цикла, поэтому два «стейл»-теста переживают. Умирают те,
    # где событие ВЗВОДИТСЯ и снятие может сработать только пост-проверкой.
    # Правка ожидания 2026-08-02 (после B-5-1): из набора УБРАН
    # `test_a_fresher_broadcast_of_another_command_does_not_cancel_this_one`.
    # Причина проверена запуском, а не выведена: очередь-на-адресата сериализовала
    # три рассылки ОДНОМУ ребёнку, и снятие стейла в этом сценарии теперь
    # срабатывает уже проверкой ПРИ ИЗВЛЕЧЕНИИ из очереди — то есть две проверки
    # стали взаимозаменяемы здесь. Тест не вакуумный: при снятии ОБЕИХ проверок он
    # падает (замерено). Остальные четыре по-прежнему держатся именно на
    # пост-проверке, поэтому она load-bearing и не удаляется.
    "RF2 нет перепроверки после ожидания": {
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
        # B-5-1: раз doomed пуст (ранний return []), фан-аут снятия детям не идёт.
        "test_forget_session_fans_out_unsubscribe_for_each_doomed_address",
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
    # B-5-1: возврат к потоку-на-действие. Детерминированно умирает тест «один
    # адресат — один воркер» (5 потоков вместо 1); тесты порядка умирают по гонке
    # (30/20 раундов, P выживания ~10⁻¹¹). ФР-1 collapse-тесты переживают: снятие
    # по поколению работает и в отдельном потоке (модель ДО B-5-1 такой и была).
    "RF14 дренаж очереди ждёт сигнал безусловно": {
        "test_action_queued_while_busy_survives_a_vanished_ready_event",
    },
    "RF11 очередь-на-адресата снова поток-на-действие": {
        "test_subscribe_then_unsubscribe_arrive_in_that_order",
        "test_any_two_commands_to_one_child_keep_enqueue_order",
        "test_one_worker_per_addressee_not_one_per_envelope",
        # Шов самой очереди: без неё действие с `event is None` уходит синхронно и
        # в очередь не попадает вовсе — страж этого пути обязан умирать вместе с ней.
        "test_action_queued_while_busy_survives_a_vanished_ready_event",
    },
    "RF12 forget_subscriber не рассылает снятие": {
        "test_forget_subscriber_fans_out_unsubscribe_to_children",
    },
    "RF13 forget_session не рассылает снятие": {
        "test_forget_session_fans_out_unsubscribe_for_each_doomed_address",
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
