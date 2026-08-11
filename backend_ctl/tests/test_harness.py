# -*- coding: utf-8 -*-
"""Тесты BackendHarness (Ф1 Task 1.3): честный headless + гарантированный teardown.

- headless-воплощение gui — сборка headless-топологии не несёт Qt-класса (юнит);
- harness_smoke — live-прогон: старт → introspect.status пары процессов → стоп < 30с;
- регресс из 1.1: state_subscribe → set_register → ожидаем push state.changed в
  событийном канале (events_page). Помечен xfail — push физически не доходит до
  внешнего сокет-клиента (диагноз в тесте).
"""

from __future__ import annotations

import time

import pytest

from backend_ctl.harness import BackendHarness
from backend_ctl.tests.conftest import wait_for_events as _wait_events


class TestHeadlessIncarnation:
    """Юнит: честный headless = процесс презентации БЕЗ Qt, а не его отсутствие.

    Harness топологию больше не правит (план D8): рецепт объявляет `gui` в
    headless-воплощении, Qt-класс ставит только presentation-overlay, который
    harness не подмешивает. Тест судит РЕЗУЛЬТАТ сборки, а не наличие функции-
    фильтра: прежний `strip_gui` был зелен на своих юнитах и при этом НЕ-операцией
    на дефолтной топологии harness (после Ф2 ни `region_pipeline`, ни `base.yaml`
    процесса `gui` не объявляли — вырезать было нечего, а шторм отказов шёл).
    """

    QT_CLASS = "multiprocess_prototype.frontend.process.GuiProcess"
    HEADLESS_CLASS = "multiprocess_prototype.frontend.headless_process.HeadlessGuiProcess"

    def _headless_processes(self, *, with_base: bool) -> dict:
        """Процессы headless-топологии harness: {имя: process_class}."""
        from pathlib import Path as _Path

        from multiprocess_prototype.backend.launch import load_topology_dict, merge_topologies
        from multiprocess_prototype.main import DEFAULT_BLUEPRINT, HERE

        blueprint = load_topology_dict(_Path(DEFAULT_BLUEPRINT))
        if with_base:
            blueprint = merge_topologies(load_topology_dict(HERE / "backend" / "topology" / "base.yaml"), blueprint)
        return {
            proc.get("process_name"): proc.get("process_class")
            for proc in blueprint["processes"]
            if isinstance(proc, dict)
        }

    @pytest.mark.parametrize("with_base", [False, True])
    def test_headless_topology_carries_gui_without_qt(self, with_base: bool) -> None:
        procs = self._headless_processes(with_base=with_base)
        assert "gui" in procs, "приёмник презентации обязан существовать — иначе адрес gui без адресата"
        assert procs["gui"] == self.HEADLESS_CLASS
        assert self.QT_CLASS not in procs.values(), "headless не должен нести Qt-класс ни у одного процесса"

    def test_every_chain_target_has_a_declared_process(self) -> None:
        """Адрес без объявленного процесса — это и есть корень шторма D8."""
        from multiprocess_framework.modules.process_manager_module.topology.blueprint import (
            SystemBlueprint,
        )
        from pathlib import Path as _Path

        from multiprocess_prototype.backend.launch import load_topology_dict, merge_topologies
        from multiprocess_prototype.main import DEFAULT_BLUEPRINT, HERE

        blueprint = merge_topologies(
            load_topology_dict(HERE / "backend" / "topology" / "base.yaml"),
            load_topology_dict(_Path(DEFAULT_BLUEPRINT)),
        )
        assert SystemBlueprint.model_validate(blueprint)._unaddressable_chain_targets() == []


@pytest.mark.harness_smoke
def test_harness_smoke_start_status_stop() -> None:
    """Live smoke: honest headless старт → introspect.status пары процессов → стоп < 30с.

    with_base=True: топология включает фундамент (always-on инфра), как в проде.
    Qt/LoginDialog не поднимается потому, что harness не подмешивает
    presentation-overlay, а рецепт объявляет gui в headless-воплощении (Ф0.4).
    Порт 8766 — чтобы не конфликтовать с session-фикстурой headless_backend (8765).
    """
    t0 = time.monotonic()
    harness = BackendHarness(with_base=True, port=8766)
    try:
        drv = harness.start()
        for proc in ("preprocessor", "region_splitter"):
            res = drv.introspect_status(proc, timeout=8.0)
            assert res.get("success") is True, f"{proc}: introspect.status не success: {res}"
    finally:
        harness.stop()
    elapsed = time.monotonic() - t0
    assert elapsed < 30.0, f"старт+стоп {elapsed:.1f}s ≥ 30s (бюджет acceptance)"


@pytest.mark.harness_smoke
def test_state_changed_push_reaches_driver_regression() -> None:
    """Регресс 1.1 (закрыт Ф1.1b): живой бэкенд, state_subscribe('**') → set_register → push в событийный канал.

    Мост push→SocketChannel (RouterManager._deliver_by_targets): DeltaDispatcher шлёт
    state.changed с targets=['backend_ctl'] + queue_type='system'; очереди
    'backend_ctl_system' нет (backend_ctl не процесс), но зарегистрирован SocketChannel
    'backend_ctl' → доставка идёт через канал во внешний driver. Раньше — silent drop.
    """
    harness = BackendHarness(with_base=True, port=8767)
    try:
        drv = harness.start()
        sub = drv.state_subscribe("**", timeout=8.0)
        assert (sub.get("result") or {}).get("status") == "ok" or sub.get("success"), sub
        # Verify-probe (Ф1.6): запись реально применилась, не молчаливый no-op.
        # Исторический урок: тут писали plugin_name+width (несуществующие ключ и
        # поле) — тест зеленел на чужих state.changed от heartbeat'ов.
        res = drv.set_register_verified("preprocessor", "resize", "target_width", 512, timeout=8.0)
        assert res["verified"], res
        evts, _ = _wait_events(drv, timeout=5.0)
        changed = [e for e in evts if e.get("command") == "state.changed"]
        assert changed, "push state.changed не дошёл до событийного канала driver'а"
    finally:
        harness.stop()


# --- Task 0.4: env-restore (без живого бэкенда — мокаем тяжёлые части) ---


class _FakeLauncher:
    def start(self):
        pass

    def wait_until_ready(self, timeout):
        return True

    def get_status(self):
        return {"process": {"pid": None}}

    def stop(self):
        pass


class _FakeDriver:
    def __init__(self, *args, **kwargs):
        pass

    def connect(self, timeout=5.0):
        pass

    def introspect_status(self, process, *, timeout=None):
        return {"success": True}

    def close(self):
        pass


class TestEnvRestore:
    def test_env_restored_to_prior_state_after_stop(self, monkeypatch) -> None:
        import os as _os

        from backend_ctl import harness as _h

        # Прежнее окружение: BACKEND_CTL задан, PORT отсутствует, PID_FILE задан.
        monkeypatch.setenv("BACKEND_CTL", "orig")
        monkeypatch.delenv("BACKEND_CTL_PORT", raising=False)
        monkeypatch.setenv("INSPECTOR_PID_FILE", "orig_pid")
        keys = ("BACKEND_CTL", "BACKEND_CTL_PORT", "INSPECTOR_PID_FILE")
        before = {k: _os.environ.get(k) for k in keys}

        h = BackendHarness(port=8799, launcher_factory=_FakeLauncher)
        monkeypatch.setattr(_h, "BackendDriver", _FakeDriver)
        monkeypatch.setattr(_h, "_subtree", lambda pid: [])
        monkeypatch.setattr(_h, "_shutdown_with_watchdog", lambda *a, **k: None)

        h.start()
        # Во время работы окружение замучено под endpoint.
        assert _os.environ["BACKEND_CTL"] == "1"
        assert _os.environ["BACKEND_CTL_PORT"] == "8799"

        h.stop()
        after = {k: _os.environ.get(k) for k in keys}
        assert after == before, f"env не восстановлен: {before} → {after}"

    def test_env_restored_when_start_raises(self, monkeypatch) -> None:
        # Регресс на MAJOR #4 ревью: исключение на пути start() (до wait_until_ready)
        # не должно оставлять env-мутации (__exit__ не зовётся при падении __enter__).
        import os as _os

        from backend_ctl import harness as _h

        monkeypatch.setenv("BACKEND_CTL", "orig")
        monkeypatch.delenv("BACKEND_CTL_PORT", raising=False)
        monkeypatch.delenv("INSPECTOR_PID_FILE", raising=False)
        keys = ("BACKEND_CTL", "BACKEND_CTL_PORT", "INSPECTOR_PID_FILE")
        before = {k: _os.environ.get(k) for k in keys}

        def _boom_factory():
            raise RuntimeError("launcher build failed")

        h = BackendHarness(port=8798, launcher_factory=_boom_factory)
        monkeypatch.setattr(_h, "_subtree", lambda pid: [])
        monkeypatch.setattr(_h, "_shutdown_with_watchdog", lambda *a, **k: None)

        with pytest.raises(RuntimeError, match="launcher build failed"):
            h.start()

        after = {k: _os.environ.get(k) for k in keys}
        assert after == before, f"env утёк после падения start(): {before} → {after}"


# --- Task 5.1: kill-net на таймауте readiness (регресс ultra-ревью) ---


class _TimeoutLauncher:
    """Launcher, у которого процесс поднимается (pid доступен), но readiness не подтверждается."""

    def start(self):
        pass

    def wait_until_ready(self, timeout):
        return False

    def get_status(self):
        return {"process": {"pid": 4242}}

    def stop(self):
        pass


class TestKillNetOnReadinessTimeout:
    def test_force_kill_tree_gets_target_when_wait_until_ready_fails(self, monkeypatch) -> None:
        """Регресс: раньше pid/дерево снимались ПОСЛЕ wait_until_ready — таймаут readiness
        поднимал RuntimeError раньше снимка, и stop()->_force_kill_tree получал (None, []),
        оставляя осиротевшие процессы. Снимок теперь снимается сразу после launcher.start(),
        ДО wait_until_ready, поэтому даже на таймауте цель для force-kill есть.
        """
        from backend_ctl import harness as _h

        captured: dict = {}

        def _fake_shutdown(launcher, timeout, orchestrator_pid, snapshot, *, log):
            captured["orchestrator_pid"] = orchestrator_pid
            captured["snapshot"] = snapshot

        monkeypatch.setattr(_h, "_subtree", lambda pid: [f"proc-{pid}"] if pid else [])
        monkeypatch.setattr(_h, "_shutdown_with_watchdog", _fake_shutdown)

        h = BackendHarness(port=8797, launcher_factory=_TimeoutLauncher, ready_timeout=0.01)
        with pytest.raises(RuntimeError, match="wait_until_ready timeout"):
            h.start()

        assert captured.get("orchestrator_pid") == 4242, "force-kill не получил pid оркестратора"
        assert captured.get("snapshot") == ["proc-4242"], "force-kill не получил снимок поддерева"

    def test_stop_falls_back_to_capturing_pid_if_start_missed_it(self, monkeypatch) -> None:
        """Fallback (Task 5.1): если ранний снимок в start() не зафиксировал pid (например,
        get_status() на тот момент ещё не отдавал pid), stop() обязан повторить попытку перед
        teardown — иначе force-kill останется без цели даже на штатном пути.
        """
        from backend_ctl import harness as _h

        class _LatePidLauncher:
            def __init__(self):
                self._ready = False

            def start(self):
                pass

            def wait_until_ready(self, timeout):
                self._ready = True
                return True

            def get_status(self):
                # pid появляется только ПОСЛЕ готовности — ранний снимок в start() его не увидит.
                return {"process": {"pid": 7777 if self._ready else None}}

            def stop(self):
                pass

        captured: dict = {}

        def _fake_shutdown(launcher, timeout, orchestrator_pid, snapshot, *, log):
            captured["orchestrator_pid"] = orchestrator_pid
            captured["snapshot"] = snapshot

        monkeypatch.setattr(_h, "BackendDriver", _FakeDriver)
        monkeypatch.setattr(_h, "_subtree", lambda pid: [f"proc-{pid}"] if pid else [])
        monkeypatch.setattr(_h, "_shutdown_with_watchdog", _fake_shutdown)

        h = BackendHarness(port=8796, launcher_factory=_LatePidLauncher)
        h.start()
        assert h._orch_pid is None, "ранний снимок не должен был увидеть ещё не готовый pid"

        h.stop()
        assert captured.get("orchestrator_pid") == 7777, "stop() не подхватил pid fallback'ом"
        assert captured.get("snapshot") == ["proc-7777"]


# --- Н-8: ПАРА ручек PID-реестра — второй стенд не смеет реапить чужой ---


class TestPidRegistryEnvPair:
    """Изоляция реестра держится ОБЕИМИ ручками пары, а не одной.

    Дефект (найден 2026-08-11 бисектом каталога `backend_ctl/tests`, 11 красных):
    harness ставил и восстанавливал только `INSPECTOR_PID_FILE`, а
    `pid_registry.pid_file_path()` читает пару по приоритету и `MULTIPROCESS_PID_FILE`
    СИЛЬНЕЕ. `SystemLauncher._prepare_pid_registry` после резолва пишет обе ручки —
    значит первый стенд оставлял в окружении сильную ручку со своим реестром, второй
    читал именно её и реапил ЧУЖОЙ ЖИВОЙ реестр, убивая процессы первого стенда.
    """

    def _fake_run(self, monkeypatch, port: int) -> BackendHarness:
        from backend_ctl import harness as _h

        monkeypatch.setattr(_h, "BackendDriver", _FakeDriver)
        monkeypatch.setattr(_h, "_subtree", lambda pid: [])
        monkeypatch.setattr(_h, "_shutdown_with_watchdog", lambda *a, **k: None)
        return BackendHarness(port=port, launcher_factory=_FakeLauncher)

    def test_stronger_handle_of_the_pair_points_at_our_own_file(self, monkeypatch) -> None:
        """Сильная ручка обязана указывать на файл ЭТОГО инстанса.

        Судится именно сильная: слабая могла быть выставлена и раньше — и была, а
        реап всё равно шёл по чужому реестру.
        """
        import os as _os

        monkeypatch.setenv("MULTIPROCESS_PID_FILE", "чужой_живой_реестр.jsonl")
        h = self._fake_run(monkeypatch, 8795)

        h.start()
        try:
            strong = _os.environ["MULTIPROCESS_PID_FILE"]
            weak = _os.environ["INSPECTOR_PID_FILE"]
            assert strong == weak, f"ручки пары разъехались: {strong!r} != {weak!r}"
            assert f"_harness_{_os.getpid()}_8795" in strong, f"сильная ручка смотрит не на свой файл: {strong!r}"
        finally:
            h.stop()

    def test_both_handles_restored_after_stop(self, monkeypatch) -> None:
        """Обе ручки возвращаются к прежнему состоянию, включая «переменной не было».

        Прежний набор ключей в тесте восстановления не включал сильную ручку — и
        остался бы зелёным при живом дефекте.
        """
        import os as _os

        monkeypatch.setenv("MULTIPROCESS_PID_FILE", "orig_mp")
        monkeypatch.delenv("INSPECTOR_PID_FILE", raising=False)
        keys = ("MULTIPROCESS_PID_FILE", "INSPECTOR_PID_FILE")
        before = {k: _os.environ.get(k) for k in keys}

        h = self._fake_run(monkeypatch, 8794)
        h.start()
        h.stop()

        after = {k: _os.environ.get(k) for k in keys}
        assert after == before, f"пара ручек не восстановлена: {before} → {after}"

    def test_pair_matches_the_framework_priority_list(self) -> None:
        """Список harness'а сверяется с ИСТОЧНИКОМ, а не живёт своей копией.

        Переименование или разворот приоритета во фреймворке обязаны ломать проверку
        здесь: копия, расходящаяся с оригиналом молча, — это ровно тот дефект, который
        и был (harness знал одну ручку из двух).
        """
        from backend_ctl.harness import _PID_FILE_ENV_KEYS
        from multiprocess_framework.modules.process_manager_module.launcher.pid_registry import _ENV_KEYS

        assert tuple(_PID_FILE_ENV_KEYS) == tuple(_ENV_KEYS), (
            f"пара ручек разошлась с фреймворком: harness={_PID_FILE_ENV_KEYS}, реестр={_ENV_KEYS}"
        )


@pytest.mark.harness_smoke
def test_second_stand_does_not_reap_the_live_one() -> None:
    """Живая пара: пока второй стенд поднимается и гаснет, ПЕРВЫЙ остаётся жив.

    Это и есть дефект Н-8 в его наблюдаемой форме: юнит выше сторожит механизм
    (ручки), а здесь судится следствие — драйвер первого стенда продолжает отвечать.
    Без правки первый ProcessManager исчезает в момент старта второго, и драйвер
    получает WinError 10054 (воспроизведено вне pytest).
    """
    import tempfile
    from pathlib import Path as _Path

    # Порты ОБОИМ стендам заданы явно: дефолтный занят сессионной фикстурой каталога,
    # и тест, молча садящийся на него, судил бы соседа, а не себя.
    first = BackendHarness(with_base=True, port=8792, log_dir=_Path(tempfile.mkdtemp(prefix="pair_first_")))
    drv = first.start()
    try:
        assert (drv.introspect_status("ProcessManager", timeout=8.0) or {}).get("success"), "первый стенд не отвечает"

        second = BackendHarness(with_base=True, port=8793, log_dir=_Path(tempfile.mkdtemp(prefix="pair_second_")))
        second.start()
        try:
            alive = (drv.introspect_status("ProcessManager", timeout=8.0) or {}).get("success")
            assert alive, "первый стенд умер, пока второй был жив — реап ушёл в чужой реестр"
        finally:
            second.stop()

        assert (drv.introspect_status("ProcessManager", timeout=8.0) or {}).get("success"), (
            "первый стенд не пережил гашение второго"
        )
    finally:
        first.stop()
