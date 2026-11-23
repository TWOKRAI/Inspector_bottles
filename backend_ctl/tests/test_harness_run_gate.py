# -*- coding: utf-8 -*-
"""Приёмка вслепую (RED, до реализации): ``run_gate`` в harness и ``BackendHarness.start_run``.

Критерии (из брифа слепого tester'а, лента Ф 2.1):

  4. ``build_headless_launcher(..., run_gate: bool | None = None)``: не ``None`` -> присваивает
     ``sys_config.run_gate`` после загрузки манифеста; ``None`` -> как в манифесте.
     ``BackendHarness(run_gate: bool | None = False)``: умолчание ``False`` ПЕРЕОПРЕДЕЛЯЕТ манифест, ``True``
     включает, ``None`` — как в манифесте. ``run_gate=True`` вместе с ``launcher_factory`` -> ``ValueError``;
     с factory и умолчанием параметр не действует.
        Уровень (А): ``(манифест, аргумент) -> _orchestrator_config["run_gate"]``.
        Уровень (Б): через ``BackendHarness``; обёртка над ``harness.build_headless_launcher`` зовёт настоящую
        функцию, читает ключ и бросает сторожевое исключение ДО спавна процессов.
  5. ``BackendHarness.start_run(timeout=30.0)``: опрос ``system.run.status`` до ``start_allowed``, затем START;
     ``error == "not_ready"`` — повтор опроса и START в пределах timeout; вердикт только по итоговому
     ``state == "running"``; не наступило — ``AssertionError`` с состоянием и узлами-причинами;
     ``already_running`` не ошибка.

Состояние на ТЕКУЩЕМ коде — какие тесты красные:

  * Красные ВСЕ тесты, кроме контролей. (А): ``build_headless_launcher`` не знает аргумента (TypeError) и не кладёт
    ключ (``manifest`` с ``run_gate`` ещё и молча игнорируется схемой). (Б): ``BackendHarness`` не принимает
    ``run_gate`` / ключа в конфиге нет. (5): у harness нет ``start_run`` (AttributeError).
  * ЗЕЛЁНЫЕ контроли: ``test_control_*`` — подмена ``CONFIG_PATH`` работает и сборка идёт; сторожевая обёртка
    срабатывает до спавна; ``launcher_factory`` по умолчанию вызывается и ValueError не даёт; заглушка PM сама
    держит конечный автомат (проверена прямыми вызовами).

Процессов и сокетов нет: сборка ``SystemLauncher`` без ``start()``; PM — заглушка-подкласс ``BackendDriver`` с
подменённым ``request`` (так тест не зависит от того, ЧЕРЕЗ какой метод драйвера ходит ``start_run``:
``run_status``/``run_start`` или ``system_command``). Всё, что может зависнуть, — daemon-поток + join-дедлайн.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any, Callable

import pytest

from backend_ctl import harness as harness_module
from backend_ctl.driver import BackendDriver
from backend_ctl.harness import BackendHarness, build_headless_launcher

_CALL_DEADLINE_S = 30.0
_ABSENT = object()


@pytest.fixture(autouse=True)
def _no_log_dir_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Как в ``test_harness_log_dir.py``, но с ГАРАНТИЕЙ отката: ``build()`` присваивает ``INSPECTOR_LOG_DIR``.

    Env сильнее аргумента ``log_dir`` и снимается один раз при импорте ``launch``. Переменные сперва ставим, потом
    удаляем: так monkeypatch запомнит «не было» и снимет то, что выставит ``build()`` (голый ``delenv`` на
    отсутствующей переменной ничего не запоминает).
    """
    from multiprocess_prototype.backend import launch

    monkeypatch.setattr(launch, "_ENV_LOG_DIR_OVERRIDE", None)
    monkeypatch.setenv("MULTIPROCESS_LOG_DIR", "x")
    monkeypatch.setenv("INSPECTOR_LOG_DIR", "x")
    monkeypatch.delenv("MULTIPROCESS_LOG_DIR")
    monkeypatch.delenv("INSPECTOR_LOG_DIR")


def _bounded(fn: Callable[[], Any], deadline_s: float = _CALL_DEADLINE_S) -> Any:
    """Вызов в daemon-потоке с дедлайном: зависший вызов валит тест, а не набор."""
    box: dict[str, Any] = {}

    def run() -> None:
        try:
            box["value"] = fn()
        except BaseException as exc:  # noqa: BLE001
            box["error"] = exc

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    thread.join(deadline_s)
    assert not thread.is_alive(), f"вызов завис дольше {deadline_s} с"
    if "error" in box:
        raise box["error"]
    return box["value"]


# ---------------------------------------------------------------------------
# Критерий 4, уровень (А): build_headless_launcher(run_gate=...)
# ---------------------------------------------------------------------------


def _manifest(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, run_gate: bool) -> Path:
    """Подменить ``CONFIG_PATH`` прототипа tmp-файлом с заданным ``run_gate`` (импортируется ВНУТРИ функции)."""
    import multiprocess_prototype.main as proto_main

    system = tmp_path / "system.yaml"
    system.write_text(f"run_gate: {'true' if run_gate else 'false'}\n", encoding="utf-8")
    monkeypatch.setattr(proto_main, "CONFIG_PATH", system)
    return system


@pytest.mark.parametrize(
    ("manifest_value", "arg", "expected"),
    [
        pytest.param(False, None, False, id="manifest-false-arg-None"),
        pytest.param(True, None, True, id="manifest-true-arg-None"),
        pytest.param(False, True, True, id="manifest-false-arg-True"),
        pytest.param(True, False, False, id="manifest-true-arg-False"),
    ],
)
def test_build_headless_launcher_run_gate_matrix(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    manifest_value: bool,
    arg: bool | None,
    expected: bool,
) -> None:
    """Аргумент (если не ``None``) перебивает манифест; ``None`` оставляет манифест. Обе стороны каждой пары."""
    _manifest(tmp_path, monkeypatch, run_gate=manifest_value)

    launcher = build_headless_launcher(log_dir=tmp_path / "logs", run_gate=arg)

    assert launcher._orchestrator_config.get("run_gate", _ABSENT) is expected


def test_control_manifest_swap_and_build_work(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """КОНТРОЛЬ (зелёный уже сейчас): подмена ``CONFIG_PATH`` подхватывается сборкой, launcher собирается.

    Доказательство подхвата: ``stop_timeout`` из tmp-файла доезжает до launcher'а.
    """
    import multiprocess_prototype.main as proto_main

    system = tmp_path / "system.yaml"
    system.write_text("system:\n  stop_timeout: 7.5\n", encoding="utf-8")
    monkeypatch.setattr(proto_main, "CONFIG_PATH", system)

    launcher = build_headless_launcher(log_dir=tmp_path / "logs")

    assert launcher._stop_timeout == 7.5


# ---------------------------------------------------------------------------
# Критерий 4, уровень (Б): BackendHarness(run_gate=...)
# ---------------------------------------------------------------------------


class _StopBeforeSpawn(Exception):
    """Сторожевое исключение: обрывает ``BackendHarness.start()`` до ``launcher.start()`` (процессов нет)."""


def _harness_run_gate(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, **harness_kwargs: Any) -> Any:
    """Собрать систему через ``BackendHarness(**kwargs).start()`` и вернуть ``run_gate`` из конфига оркестратора.

    Обёртка зовёт НАСТОЯЩУЮ ``build_headless_launcher`` с теми же аргументами, что дал harness, читает ключ и
    бросает сторожа: до ``launcher.start()`` дело не доходит. ``_ABSENT`` — ключа в конфиге нет.
    """
    real = harness_module.build_headless_launcher
    seen: dict[str, Any] = {}

    def spy(**kwargs: Any) -> Any:
        launcher = real(**kwargs)
        seen["run_gate"] = launcher._orchestrator_config.get("run_gate", _ABSENT)
        raise _StopBeforeSpawn

    monkeypatch.setattr(harness_module, "build_headless_launcher", spy)
    harness = BackendHarness(port=8771, log_dir=tmp_path / "logs", **harness_kwargs)

    with pytest.raises(_StopBeforeSpawn):
        _bounded(harness.start)

    assert "run_gate" in seen, "обёртка не сработала: harness не дошёл до сборки"
    return seen["run_gate"]


@pytest.mark.parametrize(
    ("manifest_value", "harness_kwargs", "expected"),
    [
        pytest.param(True, {}, False, id="manifest-true-default-harness"),
        pytest.param(False, {}, False, id="manifest-false-default-harness"),
        pytest.param(False, {"run_gate": None}, False, id="manifest-false-None"),
        pytest.param(True, {"run_gate": None}, True, id="manifest-true-None"),
        pytest.param(False, {"run_gate": True}, True, id="manifest-false-True"),
        pytest.param(True, {"run_gate": False}, False, id="manifest-true-False"),
    ],
)
def test_backend_harness_run_gate_matrix(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    manifest_value: bool,
    harness_kwargs: dict[str, Any],
    expected: bool,
) -> None:
    """Умолчание harness (``False``) ПЕРЕОПРЕДЕЛЯЕТ манифест; ``True`` включает; ``None`` оставляет манифест."""
    _manifest(tmp_path, monkeypatch, run_gate=manifest_value)

    got = _harness_run_gate(monkeypatch, tmp_path, **harness_kwargs)

    assert got is expected, (got, manifest_value, harness_kwargs)


def test_control_spy_fires_before_any_spawn(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """КОНТРОЛЬ (зелёный уже сейчас): сторож срабатывает на пути ``BackendHarness().start()`` и env откатывается."""
    import os

    _manifest(tmp_path, monkeypatch, run_gate=False)
    before = {k: os.environ.get(k) for k in ("BACKEND_CTL", "BACKEND_CTL_PORT")}

    # Тот же вызов без run_gate: на текущем коде ключа в конфиге нет, но сторож обязан сработать.
    got = _harness_run_gate(monkeypatch, tmp_path)

    assert got is _ABSENT or isinstance(got, bool)
    assert {k: os.environ.get(k) for k in before} == before, "stop() не вернул env после обрыва старта"


def test_run_gate_true_with_launcher_factory_is_a_value_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """``run_gate=True`` + ``launcher_factory``: фабрика собирает launcher сама, включать ей шлюз нечем -> ValueError.

    Конструктор или ``start()`` — брифом не уточнено, судим оба вместе; важно, что фабрика НЕ вызвана.
    """
    calls: list[int] = []

    def factory() -> Any:
        calls.append(1)
        raise AssertionError("фабрика не должна вызываться")

    def attempt() -> None:
        BackendHarness(port=8772, run_gate=True, launcher_factory=factory).start()

    with pytest.raises(ValueError):
        _bounded(attempt)

    assert calls == []


def test_default_run_gate_with_launcher_factory_is_inert(monkeypatch: pytest.MonkeyPatch) -> None:
    """КОНТРОЛЬ (зелёный уже сейчас): с factory и умолчанием параметр не действует — фабрика вызвана, ValueError нет."""
    calls: list[int] = []

    class _FactoryCalled(Exception):
        pass

    def factory() -> Any:
        calls.append(1)
        raise _FactoryCalled

    with pytest.raises(_FactoryCalled):
        _bounded(lambda: BackendHarness(port=8773, launcher_factory=factory).start())

    assert calls == [1]


# ---------------------------------------------------------------------------
# Критерий 5: BackendHarness.start_run на заглушке PM с состоянием
# ---------------------------------------------------------------------------


def _ok(result: dict[str, Any]) -> dict[str, Any]:
    return {"type": "response", "command": "process.command.response", "success": True, "result": result}


def _fail(result: dict[str, Any]) -> dict[str, Any]:
    return {"type": "response", "command": "process.command.response", "success": False, "result": result}


class _FakePM(BackendDriver):
    """Настоящий ``BackendDriver`` без сокета, у которого ``request`` играет конечный автомат ProcessManager.

    Конверты — живого формата. ``running`` наступает ТОЛЬКО после START, принятого в ``ready``.
    ``events`` — журнал для проверки порядка: ``status:<state>``, ``start:accepted`` / ``start:rejected`` /
    ``start:already_running``.
    """

    NODE_REASON = "cam_front: no_frames"

    def __init__(
        self,
        *,
        state: str = "not_ready",
        not_ready_polls: int = 2,
        racy_rejects: int = 0,
        stuck: bool = False,
        lying_success: bool = False,
    ) -> None:
        super().__init__()
        self.state = state
        #: сколько ближайших ``status`` ответят ``not_ready`` (потом автомат сам становится ``ready``)
        self.not_ready_polls = not_ready_polls
        #: сколько START, пришедших в ``ready``, отвергнуть гонкой (``ready`` -> ``not_ready`` на 2 опроса)
        self.racy_rejects = racy_rejects
        #: ``ready`` навсегда: START всегда отвергается ``not_ready``, хотя status говорит ``ready``
        self.stuck = stuck
        #: START «принят» (success true), но состояние не ``running``
        self.lying_success = lying_success
        self.events: list[str] = []

    @property
    def accepted_in_ready(self) -> int:
        return self.events.count("start:accepted")

    def request(self, message: dict, timeout: float | None = None) -> dict:  # type: ignore[override]
        cmd = message["data"]["cmd"]
        if cmd == "system.run.status":
            return self._status()
        if cmd == "system.run.start":
            return self._start()
        return _fail({"success": False, "error": f"unexpected command {cmd}"})

    def _status(self) -> dict:
        if self.stuck:
            self.state = "ready"
        elif self.state == "not_ready":
            if self.not_ready_polls > 0:
                self.not_ready_polls -= 1
            else:
                self.state = "ready"
        # Узел-причина виден, пока система не готова, и в ``stuck`` (там ``ready``, но START не берётся).
        reasons = [self.NODE_REASON] if (self.state == "not_ready" or self.stuck) else []
        self.events.append(f"status:{self.state}")
        return _ok(
            {
                "state": self.state,
                "since": 1.0,
                "run_gate": True,
                "start_allowed": self.state == "ready",
                "ack_allowed": False,
                "reasons": reasons,
                "last_fault": None,
            }
        )

    def _reject(self) -> dict:
        self.events.append("start:rejected")
        return _fail({"success": False, "state": "not_ready", "error": "not_ready", "reasons": [self.NODE_REASON]})

    def _start(self) -> dict:
        if self.state == "running":
            self.events.append("start:already_running")
            return _fail({"success": False, "state": "running", "error": "already_running"})
        if self.state != "ready" or self.stuck:
            return self._reject()
        if self.racy_rejects > 0:
            self.racy_rejects -= 1
            self.state = "not_ready"
            self.not_ready_polls = 2
            return self._reject()
        if self.lying_success:
            self.events.append("start:accepted")
            return _ok({"success": True, "state": "ready"})
        self.state = "running"
        self.events.append("start:accepted")
        return _ok({"success": True, "state": "running"})


def _harness_with(fake: _FakePM) -> BackendHarness:
    harness = BackendHarness(port=8774)
    harness._driver = fake  # тот же шов, что у ``driver``-свойства; сокет и процессы не нужны
    return harness


def test_control_fake_pm_state_machine() -> None:
    """КОНТРОЛЬ (зелёный уже сейчас): заглушка PM сама ведёт себя по контракту — иначе красные ниже ничего не значат."""
    pm = _FakePM(not_ready_polls=2)
    states = [pm.request({"data": {"cmd": "system.run.status"}})["result"]["state"] for _ in range(3)]
    early = pm.request({"data": {"cmd": "system.run.start"}})  # после 3-го status автомат в ready -> принят

    assert states == ["not_ready", "not_ready", "ready"]
    assert early["success"] is True and early["result"] == {"success": True, "state": "running"}
    assert pm.state == "running" and pm.accepted_in_ready == 1

    cold = _FakePM(not_ready_polls=5)
    refused = cold.request({"data": {"cmd": "system.run.start"}})
    assert refused["success"] is False
    assert refused["result"] == {
        "success": False,
        "state": "not_ready",
        "error": "not_ready",
        "reasons": [_FakePM.NODE_REASON],
    }
    assert cold.state == "not_ready"


def test_start_run_waits_for_ready_then_starts_exactly_once() -> None:
    """Два ``not_ready`` -> ``ready`` -> START принят ровно один раз; до ``ready`` START не отправлен."""
    pm = _FakePM(not_ready_polls=2)

    _bounded(lambda: _harness_with(pm).start_run(timeout=20.0))

    assert pm.state == "running"
    assert pm.events[:4] == ["status:not_ready", "status:not_ready", "status:ready", "start:accepted"], pm.events
    assert pm.accepted_in_ready == 1, pm.events
    assert "start:rejected" not in pm.events, f"START ушёл раньше start_allowed: {pm.events}"


def test_start_run_retries_after_a_not_ready_refusal() -> None:
    """Гонка: status сказал ``ready``, START получил ``not_ready`` -> повтор опроса и START; в итоге ``running``."""
    pm = _FakePM(not_ready_polls=0, racy_rejects=1)

    _bounded(lambda: _harness_with(pm).start_run(timeout=20.0))

    assert pm.state == "running", pm.events
    assert pm.events.count("start:rejected") == 1, pm.events
    assert pm.accepted_in_ready == 1, pm.events
    # после отказа обязателен новый опрос до повторного START
    first_reject = pm.events.index("start:rejected")
    accepted = pm.events.index("start:accepted")
    assert "status:ready" in pm.events[first_reject + 1 : accepted], pm.events


def test_start_run_stuck_in_ready_raises_assertion_with_state_and_nodes() -> None:
    """``ready`` навсегда (START не берётся) + малый timeout -> ``AssertionError`` (состояние и узел-причина)."""
    pm = _FakePM(stuck=True)

    with pytest.raises(AssertionError) as info:
        _bounded(lambda: _harness_with(pm).start_run(timeout=1.0), deadline_s=15.0)

    text = str(info.value)
    assert "ready" in text, text
    assert "cam_front" in text, f"в сообщении нет узла-причины: {text!r}"
    assert pm.accepted_in_ready == 0


def test_start_run_never_ready_raises_assertion_with_state_and_nodes() -> None:
    """``not_ready`` навсегда: опрос не дождался ``start_allowed`` -> ``AssertionError``, START не отправлялся."""
    pm = _FakePM(not_ready_polls=10_000)

    with pytest.raises(AssertionError) as info:
        _bounded(lambda: _harness_with(pm).start_run(timeout=1.0), deadline_s=15.0)

    assert "not_ready" in str(info.value), str(info.value)
    assert "start:accepted" not in pm.events
    assert "start:rejected" not in pm.events, f"START ушёл в not_ready: {pm.events}"


def test_start_run_verdict_is_state_running_not_the_success_flag() -> None:
    """START вернул ``success: true``, но ``state`` не ``running`` -> это не запуск: ``AssertionError``."""
    pm = _FakePM(not_ready_polls=0, lying_success=True)

    with pytest.raises(AssertionError):
        _bounded(lambda: _harness_with(pm).start_run(timeout=1.0), deadline_s=15.0)

    assert pm.state != "running"


def test_start_run_already_running_polled_is_not_an_error() -> None:
    """Система уже ``running`` на первом опросе: вызов возвращается без ошибки, повторного запуска нет."""
    pm = _FakePM(state="running")

    _bounded(lambda: _harness_with(pm).start_run(timeout=5.0))

    assert pm.state == "running"
    assert pm.accepted_in_ready == 0, pm.events


def test_start_run_already_running_reply_is_not_an_error() -> None:
    """Гонка: status ``ready``, START получил ``already_running`` (запустил кто-то другой) — не ошибка."""
    pm = _FakePM(not_ready_polls=0)
    real_start = pm._start

    def racing_start() -> dict:
        pm.state = "running"  # между status и START систему запустили извне
        return real_start()

    pm._start = racing_start  # type: ignore[method-assign]

    _bounded(lambda: _harness_with(pm).start_run(timeout=5.0))

    assert pm.state == "running"
    assert "start:already_running" in pm.events, pm.events
