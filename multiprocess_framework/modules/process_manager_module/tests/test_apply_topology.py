"""
Integration-тесты для PM.apply_topology (Task 2.2).

Покрытие:
    - Happy path: успешный apply с 5-фазными командами (stop->cleanup->provision->create->start).
    - Protected: не трогаются при apply, _topology_current_names исключает protected.
    - Rollback: инъекция падения на фазе create 3-го процесса -> первые 2 откатаны.
    - Soft-fail: сид вернул success=False -> rollback, _current_topology НЕ закоммичен.
    - Debounce: in-flight guard (второй вызов во время apply) -> debounced.
    - Cooldown: второй вызов в окне cooldown -> debounced.
    - _snapshot_processes: исключает protected.
    - _topology_current_names: live minus protected.
    - Monitor pause/resume: monitor paused на время apply, resumed после.
    - Topology not configured: apply без diff_fn/commands_fn -> graceful error.

Phase 2.3: Mock-классы вынесены в conftest.py (shared с test_replace_blueprint).

Все тесты используют mock-объекты, без реальных OS-процессов.
Framework-level: НЕ импортирует prototype (FullReplacePlanner), использует
fake diff_fn/commands_fn, эмитящие 5-фазные команды.
"""

import copy
from unittest.mock import MagicMock

from .conftest import make_pm, wire_planner


# ===========================================================================
# Тесты
# ===========================================================================


class TestSnapshotAndCurrentNames:
    """_snapshot_processes и _topology_current_names."""

    def test_snapshot_excludes_protected(self) -> None:
        """Protected процессы (включая self) не попадают в snapshot."""
        pm = make_pm(
            {
                "ProcessManager": {"class": "m.PM", "protected": True},
                "gui": {"class": "m.GUI", "protected": True},
                "worker_1": {"class": "m.W1"},
                "worker_2": {"class": "m.W2"},
            }
        )
        snap = pm._snapshot_processes()
        assert "ProcessManager" not in snap
        assert "gui" not in snap
        assert "worker_1" in snap
        assert "worker_2" in snap

    def test_snapshot_is_deep_copy(self) -> None:
        """Snapshot — deep copy: мутация оригинала не затрагивает snapshot."""
        pm = make_pm({"w1": {"class": "m.W1", "data": [1, 2]}})
        snap = pm._snapshot_processes()
        pm._process_configs["w1"]["data"].append(3)
        assert snap["w1"]["data"] == [1, 2]

    def test_current_names_excludes_protected(self) -> None:
        """_topology_current_names = live minus protected."""
        pm = make_pm(
            {
                "ProcessManager": {"class": "m.PM"},
                "gui": {"class": "m.GUI", "protected": True},
                "camera_0": {"class": "m.Cam"},
                "detector": {"class": "m.Det"},
            }
        )
        names = pm._topology_current_names()
        assert "ProcessManager" not in names
        assert "gui" not in names
        assert "camera_0" in names
        assert "detector" in names


class TestApplyTopologyHappyPath:
    """Успешный apply_topology."""

    def test_success_old_stopped_new_started(self) -> None:
        """Старые non-protected остановлены+очищены, новые provisioned+created+started."""
        pm = make_pm(
            {
                "gui": {"class": "m.GUI", "protected": True},
                "old_worker": {"class": "m.OldW"},
            }
        )

        new_bp = {
            "processes": [
                {"process_name": "new_cam", "process_class": "m.Cam"},
                {"process_name": "new_det", "process_class": "m.Det"},
            ]
        }
        result = pm.apply_topology(new_bp)

        assert result["success"] is True
        assert result["rolled_back"] is False
        # Старый worker удалён из конфигов
        assert "old_worker" not in pm._process_configs
        # Новые присутствуют
        assert "new_cam" in pm._process_configs
        assert "new_det" in pm._process_configs
        # Protected не тронут
        assert "gui" in pm._process_configs

    def test_topology_committed_on_success(self) -> None:
        """При успехе _current_topology обновлён (коммит в TopologyManager)."""
        pm = make_pm({"w1": {"class": "m.W1"}})

        bp = {"processes": [{"process_name": "n1", "process_class": "m.N1"}]}
        pm.apply_topology(bp)

        assert pm._topology_manager._current_topology == bp

    def test_protected_not_touched(self) -> None:
        """Protected-процесс не останавливается и не пересоздаётся."""
        pm = make_pm(
            {
                "gui": {"class": "m.GUI", "protected": True},
                "worker": {"class": "m.W"},
            }
        )

        gui_proc = pm._process_registry.get_process_by_name("gui")
        gui_proc._started = False

        pm.apply_topology({"processes": [{"process_name": "n1", "process_class": "m.N1"}]})

        # GUI процесс жив, start() не вызывался
        assert gui_proc._alive is True
        assert gui_proc._started is False
        assert "gui" in pm._process_configs

    def test_monitor_paused_and_resumed(self) -> None:
        """Monitor останавливается на время apply и возобновляется после."""
        pm = make_pm({"w1": {"class": "m.W1"}})

        pm.apply_topology({"processes": []})

        pm._process_monitor.stop.assert_called()
        pm._process_monitor.start.assert_called()


class TestApplyTopologyRollback:
    """Rollback при failure."""

    def test_create_failure_rolls_back(self) -> None:
        """Падение на create 3-го процесса -> старые восстановлены,
        НОВЫЕ частично-созданные процессы полностью снесены.

        Проверяет BLOCKER: _teardown_partial сносит provisioned/created
        процессы ДО _restore_from_snapshot. Без этого — утечка очередей,
        SHM-сегментов и призрачные конфиги.
        """
        pm = make_pm(
            {
                "old_1": {"class": "m.O1"},
                "old_2": {"class": "m.O2"},
            }
        )

        # Инъекция: create 3-го процесса (proc_c) падает
        create_count = {"n": 0}
        original_create = pm._topology_create

        def failing_create(name: str, proc_dict: dict) -> bool:
            create_count["n"] += 1
            if create_count["n"] == 3:
                raise RuntimeError(f"injected failure on create #{create_count['n']} ({name})")
            return original_create(name, proc_dict)

        pm._topology_manager.configure(create_process_fn=failing_create)
        wire_planner(pm)

        snapshot_before = copy.deepcopy(pm._process_configs)

        bp = {
            "processes": [
                {"process_name": "proc_a", "process_class": "m.A"},
                {"process_name": "proc_b", "process_class": "m.B"},
                {"process_name": "proc_c", "process_class": "m.C"},
            ]
        }
        result = pm.apply_topology(bp)

        assert result["success"] is False
        assert result["rolled_back"] is True
        # Конфиги восстановлены из snapshot
        for name in snapshot_before:
            assert name in pm._process_configs
            assert pm._process_configs[name]["class"] == snapshot_before[name]["class"]
        # _current_topology НЕ закоммичен
        assert pm._topology_manager._current_topology is None

        # --- BLOCKER fix assertions ---
        # НОВЫЕ процессы (proc_a, proc_b, proc_c) ОТСУТСТВУЮТ в _process_configs
        for new_name in ("proc_a", "proc_b", "proc_c"):
            assert new_name not in pm._process_configs, f"призрачный конфиг '{new_name}' остался после rollback"
        # НОВЫЕ процессы отсутствуют в registry
        for new_name in ("proc_a", "proc_b", "proc_c"):
            assert pm._process_registry.get_process_by_name(new_name) is None, (
                f"призрачный процесс '{new_name}' остался в registry после rollback"
            )
        # Provisioned-очереди новых процессов очищены из shared_resources
        sr = pm.shared_resources
        for new_name in ("proc_a", "proc_b", "proc_c"):
            assert new_name not in sr._registered, (
                f"provisioned-очередь '{new_name}' осталась в shared_resources (утечка)"
            )

    def test_first_create_failure_cleans_all_provisioned(self) -> None:
        """Падение на ПЕРВОМ create — ВСЕ provisioned-очереди новых процессов снесены.

        Сценарий: planner генерирует provision для ВСЕХ новых процессов ДО create.
        create[0] падает → ни одной provisioned-очереди не должно остаться.
        Это ловит баг, подтверждённый ревьюером: provision бежит для ВСЕХ
        до create, и при падении на первом create оставались provisioned-очереди.
        """
        pm = make_pm(
            {
                "old_w": {"class": "m.OW"},
            }
        )

        # Инъекция: КАЖДЫЙ create падает (fail_on_create в registry)
        pm._process_registry._fail_on_create = {"new_a", "new_b", "new_c"}
        wire_planner(pm)

        bp = {
            "processes": [
                {"process_name": "new_a", "process_class": "m.A"},
                {"process_name": "new_b", "process_class": "m.B"},
                {"process_name": "new_c", "process_class": "m.C"},
            ]
        }
        result = pm.apply_topology(bp)

        assert result["success"] is False
        assert result["rolled_back"] is True

        # Старый процесс восстановлен
        assert "old_w" in pm._process_configs

        # НИ ОДНОГО нового процесса нет в конфигах, registry, shared_resources
        sr = pm.shared_resources
        for new_name in ("new_a", "new_b", "new_c"):
            assert new_name not in pm._process_configs, f"призрачный конфиг '{new_name}' после rollback"
            assert pm._process_registry.get_process_by_name(new_name) is None, (
                f"призрачный процесс '{new_name}' в registry"
            )
            assert new_name not in sr._registered, f"provisioned-очередь '{new_name}' осталась (утечка SHM/queue)"

    def test_soft_fail_rolls_back(self) -> None:
        """Сид вернул success=False (без exception) -> rollback, topology НЕ закоммичен."""
        pm = make_pm({"w1": {"class": "m.W1"}})

        # Подменяем start_process_fn чтобы возвращал False
        pm._topology_manager.configure(start_process_fn=lambda name: False)
        wire_planner(pm)

        old_topo = {"old": True}
        pm._topology_manager._current_topology = old_topo

        result = pm.apply_topology({"processes": [{"process_name": "n1", "process_class": "m.N1"}]})

        assert result["success"] is False
        assert result["rolled_back"] is True
        assert pm._topology_manager._current_topology is old_topo

    def test_monitor_resumed_after_failure(self) -> None:
        """Monitor возобновляется даже при failure."""
        pm = make_pm({"w1": {"class": "m.W1"}})
        pm._topology_manager.configure(start_process_fn=lambda name: False)
        wire_planner(pm)

        pm.apply_topology({"processes": [{"process_name": "n1", "process_class": "m.N1"}]})

        pm._process_monitor.start.assert_called()


class TestApplyTopologyDebounce:
    """Debounce: in-flight guard + cooldown."""

    def test_in_flight_guard(self) -> None:
        """Пока apply выполняется (_replace_in_progress=True) -> второй debounced."""
        pm = make_pm({"w1": {"class": "m.W1"}})
        pm._replace_in_progress = True

        result = pm.apply_topology({"processes": []})

        assert result["success"] is False
        assert result["debounced"] is True
        # Реальная замена не выполнялась
        assert "w1" in pm._process_configs

    def test_cooldown_rejects_rapid_second(self) -> None:
        """С replace_debounce_s>0 повторный запрос в окне -> debounced."""
        pm = make_pm({"w1": {"class": "m.W1"}})
        pm.get_config = lambda key: {
            "stop_process_timeout": 1.0,
            "replace_debounce_s": 10.0,
        }.get(key)

        # Первый apply проходит
        r1 = pm.apply_topology({"processes": [{"process_name": "n1", "process_class": "m.N1"}]})
        assert r1["success"] is True

        # Второй сразу же — в пределах cooldown
        r2 = pm.apply_topology({"processes": [{"process_name": "n2", "process_class": "m.N2"}]})
        assert r2["success"] is False
        assert r2["debounced"] is True
        assert "n1" in pm._process_configs
        assert "n2" not in pm._process_configs

    def test_in_flight_flag_cleared_after_apply(self) -> None:
        """После apply (успех или нет) флаг _replace_in_progress снят."""
        pm = make_pm({"w1": {"class": "m.W1"}})

        pm.apply_topology({"processes": []})

        assert pm._replace_in_progress is False
        assert pm._last_replace_ts > 0.0

    def test_in_flight_flag_cleared_after_failure(self) -> None:
        """Флаг снимается даже при failure (finally)."""
        pm = make_pm({"w1": {"class": "m.W1"}})
        pm._topology_manager.configure(
            start_process_fn=lambda name: False,
        )
        wire_planner(pm)

        pm.apply_topology({"processes": [{"process_name": "n1", "process_class": "m.N1"}]})

        assert pm._replace_in_progress is False


class TestApplyTopologyNotConfigured:
    """apply_topology без конфигурации планировщика."""

    def test_no_topology_manager(self) -> None:
        """_topology_manager is None -> graceful error."""
        pm = make_pm()
        pm._topology_manager = None

        result = pm.apply_topology({"processes": []})
        assert result["success"] is False
        assert "not initialized" in result.get("error", "")

    def test_no_commands_fn(self) -> None:
        """commands_fn не установлен -> graceful error."""
        pm = make_pm()
        # Сбросить commands_fn (make_pm уже подключил FakePlanner)
        pm._topology_manager._commands_fn = None

        result = pm.apply_topology({"processes": []})
        assert result["success"] is False
        assert "not configured" in result.get("error", "")


class TestCmdTopologyApplyRouting:
    """_cmd_topology_apply маршрутизирует в apply_topology."""

    def test_cmd_routes_to_apply_topology(self) -> None:
        """_cmd_topology_apply вызывает apply_topology, не напрямую manager.apply."""
        pm = make_pm()

        # Подменяем apply_topology чтобы проверить маршрутизацию
        pm.apply_topology = MagicMock(return_value={"success": True})

        bp = {"some": "topology"}
        pm._cmd_topology_apply({"topology_dict": bp})

        pm.apply_topology.assert_called_once_with(bp)

    def test_cmd_no_topology_dict(self) -> None:
        """Без topology_dict -> error."""
        pm = make_pm()
        result = pm._cmd_topology_apply({})
        assert "error" in result
