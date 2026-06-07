"""
Integration-тесты применения топологии через apply_topology.

Task 4.1 / Phase 2.3: replace_blueprint (алиас) удалён — все тесты переведены
на прямой вызов apply_topology (road C).

Покрытие (через road C):
    - Happy path: пустой blueprint, одиночная замена, множественная замена
    - Protected: skip protected, self всегда protected, флаг из конфига
    - Rollback: ошибка create, ошибка start -> snapshot восстановлен
    - SHM cleanup: вызов release_process_memory, отсутствие shared_resources
    - Blueprint transform: chain_targets/plugins вложены в config
    - Edge cases: None blueprint, двойная замена, debounce

Удалённые тесты (дубли test_apply_topology с ПОЛНЫМ покрытием):
    - test_no_rollback_on_success -> test_success_old_stopped_new_started (apply)
    - test_replace_logs_protected_skipped -> covered by apply monitor/protected tests
    - TestBlueprintReplaceCommand -> команда blueprint.replace СНЯТА в Task 4.1

Все тесты используют mock-объекты, без реальных OS-процессов.
"""

import copy

from .conftest import MockProcess, make_pm


# ===========================================================================
# Тесты
# ===========================================================================


class TestApplyTopology:
    """Happy path тесты apply_topology."""

    def test_apply_empty_blueprint_success(self) -> None:
        """Пустой новый blueprint, нет незащищённых -> success."""
        pm = make_pm()
        result = pm.apply_topology({})

        assert result["success"] is True
        assert result["rolled_back"] is False

    def test_apply_one_process(self) -> None:
        """1 незащищённый процесс, замена на новый -> старый остановлен, новый запущен."""
        pm = make_pm({"worker_1": {"class": "mod.Worker", "priority": "normal"}})

        new_blueprint = {
            "processes": [{"process_name": "worker_2", "process_class": "mod.Worker2", "priority": "normal"}]
        }
        result = pm.apply_topology(new_blueprint)

        assert result["success"] is True
        assert result["rolled_back"] is False
        # worker_2 должен быть в _process_configs
        assert "worker_2" in pm._process_configs
        # worker_1 должен быть удалён из _process_configs
        assert "worker_1" not in pm._process_configs

    def test_apply_multiple_processes(self) -> None:
        """3 незащищённых -> заменить на 2 новых."""
        pm = make_pm(
            {
                "w1": {"class": "m.W1"},
                "w2": {"class": "m.W2"},
                "w3": {"class": "m.W3"},
            }
        )

        new_blueprint = {
            "processes": [
                {"process_name": "n1", "process_class": "m.N1"},
                {"process_name": "n2", "process_class": "m.N2"},
            ]
        }
        result = pm.apply_topology(new_blueprint)

        assert result["success"] is True
        assert "n1" in pm._process_configs
        assert "n2" in pm._process_configs
        assert "w1" not in pm._process_configs
        assert "w2" not in pm._process_configs
        assert "w3" not in pm._process_configs

    def test_apply_empty_processes_in_new_blueprint(self) -> None:
        """new_blueprint = {"processes": []} -> все незащищённые остановлены, ничего не запущено."""
        pm = make_pm(
            {
                "w1": {"class": "m.W1"},
                "w2": {"class": "m.W2"},
            }
        )

        result = pm.apply_topology({"processes": []})

        assert result["success"] is True
        # _process_configs должен быть пуст (нет protected, новых нет)
        assert pm._process_configs == {}


class TestProtected:
    """Тесты protected-процессов."""

    def test_apply_skips_protected(self) -> None:
        """Процесс с protected=True не останавливается при apply_topology."""
        pm = make_pm(
            {
                "gui": {"class": "m.GUI", "protected": True},
                "worker": {"class": "m.Worker"},
            }
        )

        # Запоминаем оригинальный gui-процесс из реестра
        gui_proc = pm._process_registry.get_process_by_name("gui")
        # Сбрасываем _started чтобы убедиться, что start() не вызывался
        gui_proc._started = False

        new_blueprint = {"processes": [{"process_name": "new_worker", "process_class": "m.NW"}]}
        result = pm.apply_topology(new_blueprint)

        assert result["success"] is True
        # gui-процесс не был остановлен (alive не менялся)
        assert gui_proc._alive is True
        # start() для protected НЕ вызывался
        assert gui_proc._started is False, "start() не должен вызываться для protected-процесса"
        # gui остался в _process_configs
        assert "gui" in pm._process_configs

    def test_apply_self_is_always_protected(self) -> None:
        """ProcessManager сам себя всегда в protected, даже без флага в конфиге."""
        pm = make_pm(
            {
                "ProcessManager": {"class": "m.PM"},
                "worker": {"class": "m.Worker"},
            }
        )

        pm.apply_topology({"processes": []})

        assert "ProcessManager" in pm._process_configs

    def test_protected_names_includes_self(self) -> None:
        """_get_protected_names() всегда содержит имя PM."""
        pm = make_pm()
        protected = pm._get_protected_names()
        assert "ProcessManager" in protected

    def test_protected_flag_from_config(self) -> None:
        """Конфиг с protected=True -> имя в _get_protected_names()."""
        pm = make_pm(
            {
                "gui": {"class": "m.GUI", "protected": True},
                "worker": {"class": "m.Worker"},
            }
        )

        protected = pm._get_protected_names()
        assert "gui" in protected
        assert "worker" not in protected


class TestRollback:
    """Тесты rollback при partial failure.

    Road C rollback: apply_topology -> snapshot -> TopologyManager.apply (fail) ->
    _restore_from_snapshot. Единая обёртка apply_topology.
    """

    def test_rollback_on_create_failure(self) -> None:
        """create_and_register возвращает None -> rollback, _process_configs восстановлен."""
        pm = make_pm(
            {"w1": {"class": "m.W1"}, "w2": {"class": "m.W2"}},
            fail_on_create={"n1"},
        )

        snapshot_before = copy.deepcopy(pm._process_configs)

        result = pm.apply_topology({"processes": [{"process_name": "n1", "process_class": "m.N1"}]})

        assert result["success"] is False
        assert result["rolled_back"] is True
        # Конфиги восстановлены
        for name in snapshot_before:
            assert name in pm._process_configs

    def test_rollback_on_start_failure(self) -> None:
        """Новый процесс не стартует -> rollback, _process_configs восстановлен."""
        old_configs = {
            "w1": {"class": "m.W1", "priority": "normal"},
        }

        # Подготовим процесс, который упадёт при start
        failing_proc = MockProcess("n1", alive=False, fail_on_start=True)
        pm = make_pm(
            old_configs,
            next_process_factory={"n1": failing_proc},
        )

        # Сохраним snapshot конфигов до замены
        snapshot = copy.deepcopy(pm._process_configs)

        result = pm.apply_topology({"processes": [{"process_name": "n1", "process_class": "m.N1"}]})

        assert result["success"] is False
        assert result["rolled_back"] is True
        # _process_configs должен быть восстановлен (w1 обратно)
        assert "w1" in pm._process_configs
        assert pm._process_configs["w1"]["class"] == snapshot["w1"]["class"]

    def test_rollback_restores_process_configs(self) -> None:
        """После rollback _process_configs равен snapshot до apply."""
        original = {
            "w1": {"class": "m.W1", "priority": "high"},
            "w2": {"class": "m.W2", "priority": "low"},
        }
        pm = make_pm(original, fail_on_create={"n1"})

        snapshot_before = copy.deepcopy(pm._process_configs)

        pm.apply_topology({"processes": [{"process_name": "n1", "process_class": "m.N1"}]})

        # Все исходные конфиги должны быть восстановлены
        for name in snapshot_before:
            assert name in pm._process_configs
            assert pm._process_configs[name]["class"] == snapshot_before[name]["class"]

    def test_missing_process_class_defaults_to_generic(self) -> None:
        """Процесс без process_class -> дефолтный GenericProcess (как boot), без краша.

        GenericProcessConfig.process_class дефолтит на GenericProcess. Поэтому
        пропущенный process_class — не ошибка, а штатный дефолт (boot-консистентно).
        """
        pm = make_pm({"w1": {"class": "m.W1"}})

        # process_class отсутствует -> должен подставиться дефолтный GenericProcess
        result = pm.apply_topology({"processes": [{"process_name": "n1"}]})

        assert result["success"] is True
        assert result["rolled_back"] is False
        assert "n1" in pm._process_configs
        # class заполнен дефолтным GenericProcess (не пустой -> нет краша class_loader)
        assert "GenericProcess" in pm._process_configs["n1"]["class"]
        assert "w1" not in pm._process_configs  # заменён


class TestBlueprintTransform:
    """Raw-blueprint -> канонический proc_dict (road C через FakePlanner)."""

    def test_chain_targets_and_plugins_nested_into_config(self) -> None:
        """chain_targets/plugins из raw-blueprint попадают во вложенный config.

        Регресс-гард: процесс стартовал без плагинов (PluginOrchestrator не
        создавался) и без маршрутов (chain_targets=[]) -> данные не текли в GUI.
        Road C: FakePlanner._build_proc_dicts трансформирует blueprint через
        SystemBlueprint -> build_configs -> process (как boot).
        """
        pm = make_pm({"w1": {"class": "m.W1"}})

        result = pm.apply_topology(
            {
                "processes": [
                    {
                        "process_name": "camera_0",
                        "process_class": "m.Cam",
                        "chain_targets": ["detector"],
                        "plugins": [{"plugin_name": "capture", "plugin_class": "m.CapturePlugin"}],
                    }
                ]
            }
        )

        assert result["success"] is True
        cfg = pm._process_configs["camera_0"]
        # Канонический формат: class на верхнем уровне, остальное — во вложенном config
        assert cfg["class"] == "m.Cam"
        assert "config" in cfg
        assert cfg["config"]["chain_targets"] == ["detector"]
        assert cfg["config"]["plugins"] == [{"plugin_name": "capture", "plugin_class": "m.CapturePlugin"}]
        # Очередь data создаётся (нужна для приёма IPC) — DEFAULT_QUEUES
        assert "queues" in cfg


class TestShmCleanup:
    """Тесты SHM cleanup."""

    def test_shm_cleanup_called(self) -> None:
        """release_process_memory вызывается для каждого остановленного процесса."""
        pm = make_pm({"w1": {"class": "m.W1"}, "w2": {"class": "m.W2"}})

        pm.apply_topology({"processes": []})

        mm = pm.shared_resources.memory_manager
        calls = [c[0][0] for c in mm.release_process_memory.call_args_list]
        assert "w1" in calls
        assert "w2" in calls

    def test_shm_cleanup_not_required(self) -> None:
        """shared_resources is None -> apply_topology завершается без ошибки."""
        pm = make_pm(
            {"w1": {"class": "m.W1"}},
            shared_resources=None,
        )
        # shared_resources=None -> _topology_provision пропускает register + SHM,
        # _topology_cleanup -> _cleanup_process_resources graceful при None.
        result = pm.apply_topology({"processes": []})

        assert result["success"] is True


class TestEdgeCases:
    """Edge cases и дополнительные проверки."""

    def test_apply_updates_process_configs(self) -> None:
        """После успешного apply _process_configs содержит новые конфиги."""
        pm = make_pm({"w1": {"class": "m.W1"}})

        new_cfg = {"process_name": "new_w", "process_class": "m.New", "priority": "high"}
        pm.apply_topology({"processes": [new_cfg]})

        assert "new_w" in pm._process_configs
        # _process_configs нормализован к внутреннему ключу class (= process_class)
        assert pm._process_configs["new_w"]["class"] == "m.New"
        assert "w1" not in pm._process_configs

    def test_apply_none_blueprint_treated_as_empty(self) -> None:
        """blueprint = None -> трактуется как {}, не падает с AttributeError."""
        pm = make_pm({"w1": {"class": "m.W1"}})

        result = pm.apply_topology(None)

        assert result["success"] is True
        # w1 удалён (None -> {} -> processes отсутствует -> всё non-protected снесено)
        assert "w1" not in pm._process_configs

    def test_double_apply_sees_updated_configs(self) -> None:
        """Двойной вызов apply_topology -> второй видит актуальный _process_configs."""
        pm = make_pm({"w1": {"class": "m.W1"}})

        # Первое apply: w1 -> n1
        pm.apply_topology({"processes": [{"process_name": "n1", "process_class": "m.N1"}]})
        assert "n1" in pm._process_configs
        assert "w1" not in pm._process_configs

        # Второе apply: n1 -> n2
        pm.apply_topology({"processes": [{"process_name": "n2", "process_class": "m.N2"}]})
        assert "n2" in pm._process_configs
        assert "n1" not in pm._process_configs


class TestApplyTopologyDebounce:
    """Дебаунс hot-swap: in-flight guard + cooldown (единая точка коалесинга)."""

    def test_in_flight_guard_rejects_reentrant(self) -> None:
        """Пока замена идёт (_replace_in_progress=True) -> новый запрос отклоняется."""
        pm = make_pm({"w1": {"class": "m.W1"}})
        pm._replace_in_progress = True

        result = pm.apply_topology({"processes": [{"process_name": "n1", "process_class": "m.N1"}]})

        assert result["success"] is False
        assert result["debounced"] is True
        # Реальная замена не выполнялась — w1 на месте.
        assert "w1" in pm._process_configs
        assert "n1" not in pm._process_configs

    def test_cooldown_rejects_rapid_second(self) -> None:
        """С replace_debounce_s>0 повторный запрос в окне после завершения -> отклоняется."""
        pm = make_pm({"w1": {"class": "m.W1"}})
        pm.get_config = lambda key: {"stop_process_timeout": 1.0, "replace_debounce_s": 10.0}.get(key)

        # Первый apply проходит (last_replace_ts по умолчанию 0 -> окно давно вышло).
        r1 = pm.apply_topology({"processes": [{"process_name": "n1", "process_class": "m.N1"}]})
        assert r1["success"] is True

        # Второй сразу же — внутри cooldown (10с) -> debounced, n1 остаётся.
        r2 = pm.apply_topology({"processes": [{"process_name": "n2", "process_class": "m.N2"}]})
        assert r2["success"] is False
        assert r2["debounced"] is True
        assert "n1" in pm._process_configs
        assert "n2" not in pm._process_configs

    def test_cooldown_zero_disables_debounce(self) -> None:
        """replace_debounce_s=0 (дефолт тестов) -> дебаунс выключен, двойное apply работает."""
        pm = make_pm({"w1": {"class": "m.W1"}})
        # get_config по умолчанию возвращает None для replace_debounce_s -> 0.0.
        pm.apply_topology({"processes": [{"process_name": "n1", "process_class": "m.N1"}]})
        pm.apply_topology({"processes": [{"process_name": "n2", "process_class": "m.N2"}]})
        assert "n2" in pm._process_configs
        assert "n1" not in pm._process_configs

    def test_in_flight_flag_cleared_after_apply(self) -> None:
        """После apply флаг _replace_in_progress снят (finally), следующий проходит."""
        pm = make_pm({"w1": {"class": "m.W1"}})
        pm.apply_topology({"processes": [{"process_name": "n1", "process_class": "m.N1"}]})
        assert pm._replace_in_progress is False
        assert pm._last_replace_ts > 0.0
