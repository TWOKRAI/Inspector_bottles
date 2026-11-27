"""C-36: независимый акцептанс ДО реализации — рестарт со свежими очередями и осиротевший замок чтения.

Настоящие ``ProcessManagerProcess.restart_process``, ``SharedResourcesManager``, ``ReaderGoneQueue`` и
межпроцессный ``_rlock``. Двойники: реестр OS-процессов (``MockProcessRegistry`` из ``make_pm``),
``communication`` и методы логов PM.

Ожидания:
  * умолчание ``restart_reuse_queues`` — свежие очереди; ``true`` остаётся рабочим откатом;
  * осиротевший ``_rlock`` на рестарте — строка ``C-36`` с типом очереди и именем процесса и +1 к
    ``orphaned_read_locks`` (``supervision.status``) в обоих режимах;
  * ``reuse=false`` — WARNING без «глухо»; ``reuse=true`` — ERROR с «глухо», весь процесс уходит на свежие
    очереди и об этом свой ERROR;
  * вызов, метящий брошенные очереди, имеет срок: осиротевший замок метки не вешает рестарт.

Сценарии с несколькими проверками гоняются один раз (module-фикстура записывает наблюдения), тест
проверяет одно свойство.
"""

from __future__ import annotations

import threading
import time
from typing import Any
from unittest.mock import MagicMock

import pytest

from multiprocess_framework.modules.shared_resources_module import SharedResourcesManager

from ._c36_helpers import orphan_marker_event_lock, orphan_read_lock, spawn_read
from .conftest import make_pm

_CAM_CONFIG = {
    "class": "os.getpid",
    "priority": "normal",
    "queues": {"system": {"maxsize": 100}, "data": {"maxsize": 100}},
}


# ---------------------------------------------------------------------------
# Общие шаги
# ---------------------------------------------------------------------------


def _make_cam_pm(**config: Any):
    """PM с настоящим SRM и процессом ``cam`` (очереди system и data)."""
    srm = SharedResourcesManager()
    assert srm.initialize()
    assert srm.register_process("cam", _CAM_CONFIG)
    pm = make_pm({"cam": _CAM_CONFIG}, shared_resources=srm)
    pm.communication = MagicMock()
    pm._process_monitor.get_supervision_snapshot.return_value = {}
    for key, value in config.items():
        pm.update_config(key, value)
    return pm, srm


def _queues(srm) -> dict:
    return srm.queue_registry.get_process_queues("cam")


def _restart(pm, deadline_s: float = 30.0) -> bool:
    """``restart_process("cam")`` в daemon-потоке: повисший рестарт — красный тест, а не повисший прогон."""
    box: dict[str, Any] = {}

    def _run() -> None:
        try:
            box["result"] = pm.restart_process("cam")
        except BaseException as exc:  # noqa: BLE001 — переносим в поток теста
            box["error"] = exc

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    thread.join(deadline_s)
    assert not thread.is_alive(), f"restart_process не вернулся за {deadline_s} с"
    if "error" in box:
        raise box["error"]
    return box["result"]


def _texts(log_mock) -> list[str]:
    return [" ".join(str(a) for a in (*c.args, *c.kwargs.values())) for c in log_mock.call_args_list]


def _voices(pm) -> dict[str, list[str]]:
    """Все строки лога PM по уровням."""
    return {
        "info": _texts(pm._log_info),
        "warning": _texts(pm._log_warning),
        "error": _texts(pm._log_error),
    }


def _reset_voices(pm) -> None:
    pm._log_info.reset_mock()
    pm._log_warning.reset_mock()
    pm._log_error.reset_mock()


def _c36(lines: list[str]) -> list[str]:
    return [line for line in lines if "C-36" in line]


def _all_lines(voices: dict[str, list[str]]) -> list[str]:
    return voices["info"] + voices["warning"] + voices["error"]


def _naming(lines: list[str], queue_type: str) -> list[str]:
    return [line for line in _c36(lines) if f"очередь '{queue_type}'" in line and "процесса 'cam'" in line]


def _orphaned_counter(pm) -> Any:
    """``supervision.status`` → ``processes.cam.orphaned_read_locks`` (``None`` — поля нет)."""
    row = pm._cmd_supervision_status({"process": "cam"})["processes"]["cam"]
    return row.get("orphaned_read_locks")


def _release_queues(*queue_maps: dict) -> None:
    for queues in queue_maps:
        for q in queues.values():
            q.cancel_join_thread()
            q.close()


# ---------------------------------------------------------------------------
# (в) Умолчание: 10 раз осиротить замок system и перезапустить
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def ten_default_restarts():
    pm, srm = _make_cam_pm()
    seen: list[dict] = []
    queue_maps: list[dict] = []
    for i in range(10):
        queue_maps.append(_queues(srm))
        orphan_read_lock(queue_maps[-1]["system"])
        _reset_voices(pm)
        assert _restart(pm) is True
        voices = _voices(pm)
        new_system = _queues(srm)["system"]
        new_system.put({"command": "ping", "i": i})
        received = spawn_read(new_system, get_timeout_s=1.0)
        seen.append({"received": received, "voices": voices, "counter": _orphaned_counter(pm)})
    queue_maps.append(_queues(srm))
    yield seen
    _release_queues(*queue_maps)


def test_system_lock_orphaned_default_restart_reader_gets_command_10_of_10(ten_default_restarts) -> None:
    got_ok = sum(1 for i, step in enumerate(ten_default_restarts) if step["received"] == {"command": "ping", "i": i})
    assert got_ok == 10


def test_default_restart_counts_orphaned_system_lock_cumulatively(ten_default_restarts) -> None:
    assert [step["counter"] for step in ten_default_restarts] == [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]


def test_default_restart_warns_about_system_queue_every_time(ten_default_restarts) -> None:
    warned = [bool(_naming(step["voices"]["warning"], "system")) for step in ten_default_restarts]
    assert warned == [True] * 10


def test_default_restart_voice_has_no_gluho_and_no_c36_error(ten_default_restarts) -> None:
    voiced = [line for step in ten_default_restarts for line in _c36(_all_lines(step["voices"]))]
    errors = [line for step in ten_default_restarts for line in _c36(step["voices"]["error"])]
    assert voiced, "ни одной строки C-36 — проверять текст не на чем"
    assert [line for line in voiced if "глухо" in line.lower()] == []
    assert errors == []


# ---------------------------------------------------------------------------
# Явный restart_reuse_queues=false: осиротевший замок data / обоих типов
# ---------------------------------------------------------------------------


def _one_restart(orphan: tuple[str, ...], **config: Any):
    pm, srm = _make_cam_pm(**config)
    old = _queues(srm)
    for queue_type in orphan:
        orphan_read_lock(old[queue_type])
    assert _restart(pm) is True
    new = _queues(srm)
    return {"pm": pm, "old": old, "new": new, "voices": _voices(pm), "counter": _orphaned_counter(pm)}


@pytest.fixture(scope="module")
def fresh_mode_data_orphaned():
    seen = _one_restart(("data",), restart_reuse_queues=False)
    yield seen
    _release_queues(seen["old"], seen["new"])


def test_reuse_false_orphaned_data_lock_warns_without_gluho(fresh_mode_data_orphaned) -> None:
    voices = fresh_mode_data_orphaned["voices"]
    assert _naming(voices["warning"], "data"), voices
    assert [line for line in _c36(_all_lines(voices)) if "глухо" in line.lower()] == []
    assert _c36(voices["error"]) == []
    assert [line for line in _all_lines(voices) if "очередь 'system'" in line] == []


def test_reuse_false_orphaned_data_lock_is_counted_once(fresh_mode_data_orphaned) -> None:
    assert fresh_mode_data_orphaned["counter"] == 1


@pytest.fixture(scope="module")
def fresh_mode_both_orphaned():
    seen = _one_restart(("system", "data"), restart_reuse_queues=False)
    yield seen
    _release_queues(seen["old"], seen["new"])


def test_two_orphaned_read_locks_are_voiced_per_queue_type(fresh_mode_both_orphaned) -> None:
    warnings = fresh_mode_both_orphaned["voices"]["warning"]
    assert (bool(_naming(warnings, "system")), bool(_naming(warnings, "data"))) == (True, True), warnings


def test_two_orphaned_read_locks_count_two(fresh_mode_both_orphaned) -> None:
    assert fresh_mode_both_orphaned["counter"] == 2


# ---------------------------------------------------------------------------
# (г) restart_reuse_queues=true, осиротевший замок data
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def reuse_true_data_orphaned():
    seen = _one_restart(("data",), restart_reuse_queues=True)
    yield seen
    _release_queues(seen["old"], seen["new"])


def test_reuse_true_orphaned_data_lock_is_error_with_gluho_naming_data_only(reuse_true_data_orphaned) -> None:
    voices = reuse_true_data_orphaned["voices"]
    named = _naming(voices["error"], "data")
    assert named, voices
    assert [line for line in named if "глухо" not in line.lower()] == []
    assert [line for line in _all_lines(voices) if "очередь 'system'" in line] == []


def test_reuse_true_orphaned_data_lock_is_counted_once(reuse_true_data_orphaned) -> None:
    assert reuse_true_data_orphaned["counter"] == 1


def test_reuse_true_orphaned_data_lock_recreates_both_queues(reuse_true_data_orphaned) -> None:
    old, new = reuse_true_data_orphaned["old"], reuse_true_data_orphaned["new"]
    assert (new["data"] is not old["data"], new["system"] is not old["system"]) == (True, True)


def test_reuse_true_fallback_to_fresh_queues_has_its_own_error(reuse_true_data_orphaned) -> None:
    """Две ERROR-строки про ``cam``: о занятом замке и о переходе всего процесса на свежие очереди."""
    errors = [line for line in reuse_true_data_orphaned["voices"]["error"] if "'cam'" in line]
    assert len(errors) >= 2, errors


def test_reuse_true_fallback_marks_abandoned_data_queue_reader_gone(reuse_true_data_orphaned) -> None:
    assert reuse_true_data_orphaned["old"]["data"].is_reader_gone() is True


def test_reuse_true_fallback_marks_abandoned_system_queue_reader_gone(reuse_true_data_orphaned) -> None:
    """Выведено из «метка на брошенных очередях»: при переходе всего процесса system тоже брошена."""
    assert reuse_true_data_orphaned["old"]["system"].is_reader_gone() is True


# ---------------------------------------------------------------------------
# Умолчание без осиротевших замков: новые очереди, метка, incarnation, тишина
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def clean_default_restart():
    pm, srm = _make_cam_pm()
    old = _queues(srm)
    assert _restart(pm) is True
    new = _queues(srm)
    row = pm._cmd_supervision_status({"process": "cam"})["processes"]["cam"]
    yield {"old": old, "new": new, "voices": _voices(pm), "row": row}
    _release_queues(old, new)


def test_default_restart_hands_out_new_queues(clean_default_restart) -> None:
    old, new = clean_default_restart["old"], clean_default_restart["new"]
    assert (new["system"] is not old["system"], new["data"] is not old["data"]) == (True, True)


def test_default_restart_marks_old_queues_gone_and_leaves_new_unmarked(clean_default_restart) -> None:
    old, new = clean_default_restart["old"], clean_default_restart["new"]
    assert [old["system"].is_reader_gone(), old["data"].is_reader_gone()] == [True, True]
    assert [new["system"].is_reader_gone(), new["data"].is_reader_gone()] == [False, False]


def test_default_restart_bumps_incarnation(clean_default_restart) -> None:
    assert clean_default_restart["row"]["incarnation"] == 1


def test_default_restart_without_orphan_is_silent_and_counts_zero(clean_default_restart) -> None:
    assert _c36(_all_lines(clean_default_restart["voices"])) == []
    assert clean_default_restart["row"].get("orphaned_read_locks") == 0


# ---------------------------------------------------------------------------
# Откат restart_reuse_queues=true без осиротевших замков
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def clean_reuse_true_restart():
    pm, srm = _make_cam_pm(restart_reuse_queues=True)
    old = _queues(srm)
    assert _restart(pm) is True
    new = _queues(srm)
    yield {"old": old, "new": new}
    _release_queues(old)


def test_reuse_true_without_orphan_keeps_queue_identity(clean_reuse_true_restart) -> None:
    old, new = clean_reuse_true_restart["old"], clean_reuse_true_restart["new"]
    assert (new["system"] is old["system"], new["data"] is old["data"]) == (True, True)


def test_reuse_true_without_orphan_does_not_mark_reused_queues(clean_reuse_true_restart) -> None:
    new = clean_reuse_true_restart["new"]
    assert [new["system"].is_reader_gone(), new["data"].is_reader_gone()] == [False, False]


# ---------------------------------------------------------------------------
# Ложная тревога: замок data занят коротко и отпускается
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def short_hold_during_restart():
    """Замок data держится; с входа в рестарт (шпион ``remove_process``) отпускается через 15 мс."""
    pm, srm = _make_cam_pm(restart_reuse_queues=True)
    old = _queues(srm)
    data = old["data"]
    assert data._rlock.acquire(False) is True
    entry: dict[str, Any] = {"held": None, "timer": None}
    real_remove = pm._process_registry.remove_process

    def _spy(name: str) -> None:
        taken = data._rlock.acquire(False)
        entry["held"] = not taken
        if taken:
            data._rlock.release()
        else:
            entry["timer"] = threading.Timer(0.015, data._rlock.release)
            entry["timer"].start()
        real_remove(name)

    pm._process_registry.remove_process = _spy
    assert _restart(pm) is True
    if entry["timer"] is not None:
        entry["timer"].join(5.0)
    yield {"held": entry["held"], "old": old, "new": _queues(srm), "voices": _voices(pm), "pm": pm}
    _release_queues(old)


def _require_held(seen: dict) -> None:
    if seen["held"] is not True:
        pytest.skip("inconclusive: в момент входа в рестарт замок уже не был занят")


def test_short_read_lock_hold_is_not_an_alarm_and_keeps_queue(short_hold_during_restart) -> None:
    _require_held(short_hold_during_restart)
    assert _c36(_all_lines(short_hold_during_restart["voices"])) == []
    assert short_hold_during_restart["new"]["data"] is short_hold_during_restart["old"]["data"]


def test_short_read_lock_hold_is_not_counted(short_hold_during_restart) -> None:
    _require_held(short_hold_during_restart)
    assert _orphaned_counter(short_hold_during_restart["pm"]) == 0


# ---------------------------------------------------------------------------
# Hazard: замок Event-метки осиротел — рестарт не виснет
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def marker_event_lock_orphaned():
    pm, srm = _make_cam_pm()
    old = _queues(srm)
    orphan_marker_event_lock(old["data"])
    box: dict[str, Any] = {}

    def _run() -> None:
        started = time.monotonic()
        box["result"] = pm.restart_process("cam")
        box["elapsed"] = time.monotonic() - started

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    thread.join(5.0)
    returned = not thread.is_alive()
    yield {"returned": returned, "result": box.get("result"), "old": old, "new": _queues(srm)}
    # ``is_reader_gone`` на ``old["data"]`` звать нельзя: он берёт тот же осиротевший замок.


def test_orphaned_marker_event_lock_does_not_hang_restart(marker_event_lock_orphaned) -> None:
    assert (marker_event_lock_orphaned["returned"], marker_event_lock_orphaned["result"]) == (True, True)


def test_orphaned_marker_event_lock_restart_still_hands_out_new_queues(marker_event_lock_orphaned) -> None:
    old, new = marker_event_lock_orphaned["old"], marker_event_lock_orphaned["new"]
    assert (new["system"] is not old["system"], new["data"] is not old["data"]) == (True, True)
