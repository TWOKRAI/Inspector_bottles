"""
Headless integration-тест полного switch топологии.

Без GUI, без реальных OS-процессов — через mock-Process с реалистичным
lifecycle (conftest.MockProcess/MockProcessRegistry/MockSharedResources).

Прогоняет ВСЕ 5 фаз (stop_all → cleanup → provision → create → start)
и проверяет консистентность:
- registry (реестр процессов)
- _process_configs (конфигурации)
- shared_resources._registered (provisioned-очереди)
- shared_resources.memory_manager (SHM — вызовы release/create)

Мокается:
- OS-процессы (MockProcess) — вместо multiprocessing.Process.
  Причина: реальный spawn в pytest нестабилен (IPC-таймауты,
  OS-ограничения), а нам нужна детерминированная проверка state.
- SharedResourcesManager (MockSharedResources) — вместо реального
  менеджера SHM/очередей. Причина: нет реальных shared-memory
  сегментов в тестовом окружении.
- ProcessRegistry (MockProcessRegistry) — враппер с контролируемым
  поведением create/stop/remove. Все фазы lifecycle (alive, pid,
  start/stop) эмулируются.

НЕ мокается:
- TopologyManager — реальный код (topology_manager.py).
- PM-сиды (_topology_stop/_topology_cleanup/etc.) — реальный код.
- FakePlanner — генерирует 5-фазные команды как продовый planner.
- _rollback_to_snapshot — реальный код (rollback тем же 5-фазным
  конвейером, Task 1.2 topology-switch-hardening; заменил прежние
  _teardown_partial + _restore_from_snapshot).

Этот тест должен ловить все 3 сессионные регрессии + BLOCKER утечки.
"""

import copy

from .conftest import make_pm, wire_planner


class TestSwitchIntegrationHappyPath:
    """Полный switch: old topology → new topology."""

    def test_full_switch_old_dead_new_alive(self) -> None:
        """Switch: 2 старых процесса заменяются 3 новыми.

        Проверяет:
        - Старые non-protected мертвы/сняты с registry
        - Новые живы/зарегистрированы
        - Очереди старых очищены (нет утечки)
        - _process_configs консистентен
        """
        pm = make_pm(
            {
                "gui": {"class": "m.GUI", "protected": True},
                "camera_0": {"class": "m.Cam", "memory": {"frame": "640x480"}},
                "detector": {"class": "m.Det"},
            }
        )

        sr = pm.shared_resources

        new_bp = {
            "processes": [
                {"process_name": "cam_hd", "process_class": "m.CamHD"},
                {"process_name": "detector_v2", "process_class": "m.DetV2"},
                {"process_name": "merger", "process_class": "m.Merge"},
            ]
        }
        result = pm.apply_topology(new_bp)

        # --- Успех ---
        assert result["success"] is True
        assert result["rolled_back"] is False

        # --- Старые: мертвы/сняты ---
        assert "camera_0" not in pm._process_configs
        assert "detector" not in pm._process_configs
        assert pm._process_registry.get_process_by_name("camera_0") is None
        assert pm._process_registry.get_process_by_name("detector") is None

        # --- Новые: живы/зарегистрированы ---
        for name in ("cam_hd", "detector_v2", "merger"):
            assert name in pm._process_configs, f"новый '{name}' не в _process_configs"
            proc = pm._process_registry.get_process_by_name(name)
            assert proc is not None, f"новый '{name}' не в registry"
            assert proc._started is True, f"новый '{name}' не стартован"

        # --- Protected не тронут ---
        assert "gui" in pm._process_configs
        gui_proc = pm._process_registry.get_process_by_name("gui")
        assert gui_proc is not None
        assert gui_proc._alive is True

        # --- SHM release вызван для старых ---
        mm = sr.memory_manager
        release_calls = [c.args[0] for c in mm.release_process_memory.call_args_list]
        assert "camera_0" in release_calls
        assert "detector" in release_calls

        # --- Provisioned-очереди новых зарегистрированы ---
        for name in ("cam_hd", "detector_v2", "merger"):
            assert name in sr._registered, f"provisioned-очередь '{name}' не создана"

    def test_sequential_switches(self) -> None:
        """Два последовательных switch: A→B→C. Нет утечки от первого switch."""
        pm = make_pm(
            {
                "gui": {"class": "m.GUI", "protected": True},
                "proc_a": {"class": "m.A"},
            }
        )

        # Switch 1: A → B
        bp_b = {"processes": [{"process_name": "proc_b", "process_class": "m.B"}]}
        r1 = pm.apply_topology(bp_b)
        assert r1["success"] is True
        assert "proc_a" not in pm._process_configs
        assert "proc_b" in pm._process_configs

        # Switch 2: B → C
        bp_c = {
            "processes": [
                {"process_name": "proc_c1", "process_class": "m.C1"},
                {"process_name": "proc_c2", "process_class": "m.C2"},
            ]
        }
        r2 = pm.apply_topology(bp_c)
        assert r2["success"] is True

        # Только C1,C2 + protected gui
        non_protected = {k for k, v in pm._process_configs.items() if not v.get("protected")}
        assert non_protected == {"proc_c1", "proc_c2"}

        # Нет утечки от proc_a или proc_b
        assert "proc_a" not in pm._process_configs
        assert "proc_b" not in pm._process_configs
        assert pm._process_registry.get_process_by_name("proc_a") is None
        assert pm._process_registry.get_process_by_name("proc_b") is None


class TestSwitchIntegrationRollback:
    """Switch с провалом — проверка BLOCKER fix."""

    def test_rollback_cleans_new_restores_old(self) -> None:
        """Провал на create → новые снесены, старые восстановлены.

        Проверяет: registry, _process_configs, shared_resources._registered,
        SHM-вызовы — полная консистентность после rollback.
        """
        pm = make_pm(
            {
                "gui": {"class": "m.GUI", "protected": True},
                "old_cam": {"class": "m.Cam"},
                "old_det": {"class": "m.Det"},
            }
        )
        sr = pm.shared_resources
        snapshot_before = copy.deepcopy(pm._process_configs)

        # Инъекция: create 2-го нового процесса падает
        create_count = {"n": 0}
        original_create = pm._topology_create

        def failing_create(name: str, proc_dict: dict) -> bool:
            create_count["n"] += 1
            if create_count["n"] == 2:
                raise RuntimeError(f"injected failure on create #{create_count['n']}")
            return original_create(name, proc_dict)

        pm._topology_manager.configure(create_process_fn=failing_create)
        wire_planner(pm)

        bp = {
            "processes": [
                {"process_name": "new_1", "process_class": "m.N1"},
                {"process_name": "new_2", "process_class": "m.N2"},
                {"process_name": "new_3", "process_class": "m.N3"},
            ]
        }
        result = pm.apply_topology(bp)

        assert result["success"] is False
        assert result["rolled_back"] is True

        # --- Старые восстановлены ---
        for name in ("old_cam", "old_det"):
            assert name in pm._process_configs
            assert pm._process_configs[name]["class"] == snapshot_before[name]["class"]
            proc = pm._process_registry.get_process_by_name(name)
            assert proc is not None, f"старый '{name}' не восстановлен в registry"

        # --- НОВЫЕ процессы полностью очищены (BLOCKER fix) ---
        for new_name in ("new_1", "new_2", "new_3"):
            assert new_name not in pm._process_configs, f"призрачный конфиг '{new_name}' после rollback"
            assert pm._process_registry.get_process_by_name(new_name) is None, (
                f"призрачный процесс '{new_name}' в registry"
            )
            assert new_name not in sr._registered, f"provisioned-очередь '{new_name}' утекла"

        # --- Protected не тронут ---
        assert "gui" in pm._process_configs

        # --- _current_topology НЕ закоммичен ---
        assert pm._topology_manager._current_topology is None

    def test_rollback_then_successful_switch(self) -> None:
        """Неудачный switch → успешный switch. Второй switch чист
        (не загрязнён остатками первого).

        Это ключевой сценарий BLOCKER: без корректного отката
        (_rollback_to_snapshot) второй switch строит diff/snapshot от
        загрязнённого состояния.
        """
        pm = make_pm(
            {
                "worker": {"class": "m.W"},
            }
        )
        sr = pm.shared_resources

        # Switch 1: провал
        pm._process_registry._fail_on_create = {"bad_proc"}
        wire_planner(pm)

        bp_bad = {
            "processes": [
                {"process_name": "bad_proc", "process_class": "m.Bad"},
            ]
        }
        r1 = pm.apply_topology(bp_bad)
        assert r1["success"] is False
        assert r1["rolled_back"] is True

        # Проверка чистоты после первого switch
        assert "bad_proc" not in pm._process_configs
        assert "bad_proc" not in sr._registered
        assert "worker" in pm._process_configs

        # Switch 2: успех (убираем fail_on_create)
        pm._process_registry._fail_on_create = set()
        wire_planner(pm)

        bp_good = {
            "processes": [
                {"process_name": "good_proc", "process_class": "m.Good"},
            ]
        }
        r2 = pm.apply_topology(bp_good)
        assert r2["success"] is True

        # Только good_proc (не worker, не bad_proc)
        non_protected = {k for k, v in pm._process_configs.items() if not v.get("protected") and k != "ProcessManager"}
        assert non_protected == {"good_proc"}
        assert "bad_proc" not in pm._process_configs
        assert "worker" not in pm._process_configs

    def test_provision_all_then_first_create_fails(self) -> None:
        """Provision прошёл для ВСЕХ, create[0] упал → ни одной
        provisioned-очереди не осталось.

        Воспроизводит точный сценарий ревьюера: provision бежит для ВСЕХ
        до create, при падении на create[0] provisioned-очереди утекают.
        """
        pm = make_pm({"old": {"class": "m.Old"}})
        sr = pm.shared_resources

        # ВСЕ create будут падать
        pm._process_registry._fail_on_create = {"p1", "p2", "p3"}
        wire_planner(pm)

        bp = {
            "processes": [
                {"process_name": "p1", "process_class": "m.P1"},
                {"process_name": "p2", "process_class": "m.P2"},
                {"process_name": "p3", "process_class": "m.P3"},
            ]
        }
        result = pm.apply_topology(bp)

        assert result["success"] is False
        assert result["rolled_back"] is True

        # Ни одной новой provisioned-очереди
        for name in ("p1", "p2", "p3"):
            assert name not in sr._registered, f"provisioned-очередь '{name}' утекла после rollback"
            assert name not in pm._process_configs
            assert pm._process_registry.get_process_by_name(name) is None

        # Старый восстановлен
        assert "old" in pm._process_configs


class TestSwitchIntegrationEdgeCases:
    """Граничные сценарии switch."""

    def test_empty_to_populated(self) -> None:
        """Switch с пустой топологии (только protected) на заполненную."""
        pm = make_pm(
            {
                "gui": {"class": "m.GUI", "protected": True},
            }
        )

        bp = {
            "processes": [
                {"process_name": "cam", "process_class": "m.Cam"},
                {"process_name": "det", "process_class": "m.Det"},
            ]
        }
        result = pm.apply_topology(bp)

        assert result["success"] is True
        assert "cam" in pm._process_configs
        assert "det" in pm._process_configs
        assert "gui" in pm._process_configs

    def test_populated_to_empty(self) -> None:
        """Switch на пустую топологию (только protected остаётся)."""
        pm = make_pm(
            {
                "gui": {"class": "m.GUI", "protected": True},
                "worker_1": {"class": "m.W1"},
                "worker_2": {"class": "m.W2"},
            }
        )

        result = pm.apply_topology({"processes": []})

        assert result["success"] is True
        # Только protected
        non_protected = {k for k, v in pm._process_configs.items() if not v.get("protected") and k != "ProcessManager"}
        assert non_protected == set()
        assert "gui" in pm._process_configs

    def test_debounce_does_not_leak(self) -> None:
        """Debounced вызов не оставляет side-effects."""
        pm = make_pm({"w": {"class": "m.W"}})
        pm._replace_in_progress = True

        result = pm.apply_topology({"processes": []})

        assert result["debounced"] is True
        # Никаких side-effects
        assert "w" in pm._process_configs
        assert pm._process_registry.get_process_by_name("w") is not None
