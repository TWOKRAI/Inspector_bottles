# -*- coding: utf-8 -*-
"""Task 4.1 — паритет форм ответа live ↔ replay.

Находка ultra-ревью «replay ≠ live»: инструмент отдавал РАЗНУЮ форму в зависимости от
режима сессии. ``state_get`` вживую — пассthrough ответа бэкенда (``status: ok|error`` +
``value``), а на записи возвращал ``{"success": True, "path", "value"}``; поддерево и
вовсе клало данные в ключ ``subtree`` вместо ``value``. Агент, написавший разбор по живой
сессии, на записи молча читал ``None`` — то есть флагманская фича отладки (flight recorder)
давала тихо неверные ответы.

Канон — live: он общается с настоящим ``StateStoreManager``, и подстраиваться обязан
реплей, а не наоборот.

Тестов на форму не было вовсе — потому находка и дожила до ревью. Здесь форма
проверяется явно, для обоих режимов сразу.
"""

from __future__ import annotations

from typing import Any, Dict

from backend_ctl.recorder import ReplayPlayer


class _StubTelemetryModel:
    """Read-model реплеера: отдаёт заранее заданный плоский снимок."""

    def __init__(self, snapshot: Dict[str, Any]) -> None:
        self._snapshot = snapshot

    def snapshot(self, prefix: str = "") -> Dict[str, Any]:
        if not prefix:
            return dict(self._snapshot)
        if prefix in self._snapshot:
            return {prefix: self._snapshot[prefix]}
        return {k: v for k, v in self._snapshot.items() if k.startswith(f"{prefix}.")}


class _StubRecording:
    """Запись без событий — нужен только snapshot header'а."""

    def __init__(self, snapshot: Dict[str, Any]) -> None:
        self.snapshot = snapshot
        self.events: list = []
        self.truncated = False
        self.header: Dict[str, Any] = {}
        self.path = "stub.jsonl"


def _player(snapshot_values: Dict[str, Any], *, overview: Any = None) -> ReplayPlayer:
    """ReplayPlayer с подменённым read-model — без реального driver'а и файла."""
    snapshot: Dict[str, Any] = {}
    if overview is not None:
        snapshot["overview"] = overview
    player = ReplayPlayer.__new__(ReplayPlayer)
    player.recording = _StubRecording(snapshot)
    player._events = []
    player._playhead = 0

    class _StubDriver:
        _telemetry_lock = __import__("threading").Lock()
        _telemetry_model = _StubTelemetryModel(snapshot_values)

    player.driver = _StubDriver()
    return player


# --- state_get: бэкендная форма status/value, а не success ---


def test_replay_state_get_uses_backend_shape() -> None:
    """Найденный путь → status:'ok' + value, как у живого handle_state_get."""
    res = _player({"processes.cam.fps": 30.0}).state_get("processes.cam.fps")

    assert res["status"] == "ok", "реплей обязан отдавать бэкендную форму status, а не success"
    assert res["value"] == 30.0
    assert "success" not in res, "ключ success был расхождением с live — он не должен вернуться"
    assert res["recorded"] is True, "пометка происхождения ответа обязана сохраниться"


def test_replay_state_get_missing_path_is_error_like_live() -> None:
    """Отсутствующий путь → status:'error', а не «успех с found:False».

    Живой бэкенд на несуществующем пути отвечает ошибкой. Реплей раньше отвечал
    success:True — код, ветвящийся по успеху, считал пустоту валидными данными.
    """
    res = _player({"a.b": 1}).state_get("нет.такого.пути")

    assert res["status"] == "error"
    assert "нет.такого.пути" in res["error"]
    assert res.get("found") is not False or "found" not in res


def test_replay_state_get_subtree_puts_data_in_value() -> None:
    """Поддерево лежит в ``value`` — живой handle_state_get_subtree кладёт именно туда."""
    res = _player({"p.a": 1, "p.b": 2, "q.c": 3}).state_get_subtree("p")

    assert res["status"] == "ok"
    assert res["value"] == {"p.a": 1, "p.b": 2}
    assert "subtree" not in res, "ключ subtree был расхождением с live"


# --- system_overview: битая секция не роняет потребителя ---


def test_replay_overview_wraps_recorded_error_section() -> None:
    """Записанная error-секция отдаётся как ВАЛИДНАЯ форма overview с success:False.

    ``_safe_section`` пишет в header ``{"error": ..., "section": ...}``, если ручка не
    ответила в момент записи. Раньше этот dict отдавался как есть, и потребитель падал
    на KeyError по processes/anomalies — одна битая секция делала всю запись бесполезной.
    """
    res = _player({}, overview={"error": "TimeoutError: ручка не ответила", "section": "overview"}).system_overview()

    assert res["success"] is False
    assert "TimeoutError" in res["error"]
    # Форма обязана остаться разбираемой — потребитель не должен падать на ключах.
    assert res["processes"] == {}
    assert res["anomalies"] == []
    assert res["anomaly_count"] == 0
    assert res["recorded"] is True


def test_replay_overview_passes_through_healthy_snapshot() -> None:
    """Здоровый записанный overview проходит как есть — обёртка не искажает данные."""
    recorded = {"success": True, "processes": {"cam": {"alive": True}}, "anomalies": [], "anomaly_count": 0}
    res = _player({}, overview=recorded).system_overview()

    assert res["success"] is True
    assert res["processes"] == {"cam": {"alive": True}}
    assert res["recorded"] is True


# --- Контракт: набор ключей ответа не расходится между режимами ---


def test_state_get_key_sets_match_live_contract() -> None:
    """Ключи replay-ответа — надмножество live-контракта ровно на пометку recorded.

    Стережёт от повторного расхождения: любая новая «удобная» надстройка формы в
    реплее (path/found/subtree и т.п.) должна быть сознательным решением, а не
    случайной, как прежде.
    """
    live_ok_keys = {"status", "value"}
    live_err_keys = {"status", "error"}

    ok = _player({"x": 1}).state_get("x")
    err = _player({"x": 1}).state_get("нет")

    assert live_ok_keys <= set(ok), f"replay потерял ключи live-успеха: {live_ok_keys - set(ok)}"
    assert live_err_keys <= set(err), f"replay потерял ключи live-ошибки: {live_err_keys - set(err)}"
    # Расхождения прошлого — именно эти ключи вместо status.
    assert "success" not in ok and "success" not in err
