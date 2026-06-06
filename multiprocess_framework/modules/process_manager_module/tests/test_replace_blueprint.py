"""
Integration-тесты для replace_blueprint (Task 5.4).

Покрытие:
    - Happy path: пустой blueprint, одиночная замена, множественная замена
    - Protected: skip protected, self всегда protected, флаг из конфига
    - Rollback: ошибка stop, ошибка start, восстановление _process_configs
    - SHM cleanup: вызов release_process_memory, отсутствие shared_resources
    - Команда: blueprint.replace зарегистрирована, вызов без аргумента
    - Edge cases: логирование protected skipped, пустой processes в новом blueprint

Все тесты используют mock-объекты, без реальных OS-процессов.
"""

import copy
from unittest.mock import MagicMock, patch

from ..process.process_manager_process import ProcessManagerProcess


# ---------------------------------------------------------------------------
# Mock-классы
# ---------------------------------------------------------------------------


class MockProcess:
    """Имитация OS-процесса (multiprocessing.Process) без реального запуска."""

    def __init__(
        self,
        name: str,
        *,
        alive: bool = True,
        pid: int = 1000,
        fail_on_start: bool = False,
    ) -> None:
        self.name = name
        self._alive = alive
        self.pid = pid
        self._fail_on_start = fail_on_start
        self._started = False

    def is_alive(self) -> bool:
        return self._alive

    def start(self) -> None:
        if self._fail_on_start:
            raise RuntimeError(f"MockProcess '{self.name}': start failure (injected)")
        self._alive = True
        self._started = True

    def stop(self) -> None:
        self._alive = False

    def join(self, timeout: float | None = None) -> None:
        pass

    def terminate(self) -> None:
        self._alive = False

    def kill(self) -> None:
        self._alive = False


class MockProcessRegistry:
    """Имитация ProcessRegistry с контролируемым поведением stop/create."""

    def __init__(
        self,
        *,
        fail_on_stop: set[str] | None = None,
        fail_on_create: set[str] | None = None,
    ) -> None:
        self._processes: dict[str, MockProcess] = {}
        self._fail_on_stop: set[str] = fail_on_stop or set()
        self._fail_on_create: set[str] = fail_on_create or set()
        # Фабрика для создания новых MockProcess (можно подменить в тесте)
        self._next_process_factory: dict[str, MockProcess] = {}

    def get_process_by_name(self, name: str) -> MockProcess | None:
        return self._processes.get(name)

    def create_and_register(
        self,
        name: str,
        class_path: str,
        config: dict | None = None,
        priority: str = "normal",
    ) -> MockProcess | None:
        if name in self._fail_on_create:
            return None
        proc = self._next_process_factory.get(name) or MockProcess(name, alive=False, pid=hash(name) % 10000)
        self._processes[name] = proc
        return proc

    def remove_process(self, name: str) -> None:
        self._processes.pop(name, None)

    def stop_one(self, name: str, timeout: float = 5.0) -> bool:
        if name in self._fail_on_stop:
            return False
        proc = self._processes.get(name)
        if proc is None:
            return False
        proc._alive = False
        return True

    def stop_many(self, names: list[str], timeout: float = 5.0) -> dict[str, bool]:
        result: dict[str, bool] = {}
        for name in names:
            if name in self._fail_on_stop:
                result[name] = False
                continue
            proc = self._processes.get(name)
            if proc is None:
                result[name] = False
                continue
            proc._alive = False
            result[name] = True
        return result

    def stop_all(self, timeout: float = 5.0) -> None:
        for proc in self._processes.values():
            proc._alive = False

    @property
    def os_processes(self) -> list[MockProcess]:
        return list(self._processes.values())


class MockSharedResources:
    """Имитация SharedResourcesManager с опциональным memory_manager."""

    def __init__(self, *, with_memory_manager: bool = True) -> None:
        if with_memory_manager:
            self.memory_manager = MagicMock()
            self.memory_manager.release_process_memory = MagicMock()
        else:
            self.memory_manager = None

        self.process_state_registry = MagicMock()
        self.process_state_registry.queue_registry = None
        self._registered: dict[str, dict] = {}

    def register_process(self, name: str, config: dict) -> None:
        self._registered[name] = config

    def get_process_data(self, name: str) -> MagicMock:
        mock_data = MagicMock()
        mock_data.custom = {}
        mock_data.state = {"status": "running"}
        return mock_data

    def get_process_names(self) -> list[str]:
        return list(self._registered.keys())


# ---------------------------------------------------------------------------
# Фабрика: создание ProcessManagerProcess с моками
# ---------------------------------------------------------------------------


def make_pm(
    process_configs: dict[str, dict] | None = None,
    *,
    fail_on_stop: set[str] | None = None,
    fail_on_create: set[str] | None = None,
    with_memory_manager: bool = True,
    shared_resources: MockSharedResources | None = ...,
    next_process_factory: dict[str, MockProcess] | None = None,
) -> ProcessManagerProcess:
    """Создать минимальный ProcessManagerProcess с mock-компонентами.

    Не вызывает ``initialize()`` — только ручная настройка атрибутов.
    """
    # Обход __init__: создаём объект напрямую
    with patch.object(ProcessManagerProcess, "__init__", lambda self, *a, **kw: None):
        pm = ProcessManagerProcess.__new__(ProcessManagerProcess)

    pm.name = "ProcessManager"
    pm.config = {}
    pm.config_handler = None

    # SharedResources
    if shared_resources is ...:
        pm.shared_resources = MockSharedResources(with_memory_manager=with_memory_manager)
    else:
        pm.shared_resources = shared_resources

    # ProcessRegistry
    registry = MockProcessRegistry(
        fail_on_stop=fail_on_stop,
        fail_on_create=fail_on_create,
    )
    if next_process_factory:
        registry._next_process_factory = next_process_factory
    pm._process_registry = registry

    # ProcessMonitor (mock: поддерживает start/stop, _monitoring)
    pm._process_monitor = MagicMock()
    pm._process_monitor._monitoring = True

    # Priority (mock: все вызовы noop)
    pm._priority = MagicMock()

    # ProcessStatusMonitor (не нужен для replace_blueprint)
    pm._status = MagicMock()

    # Конфиги процессов
    pm._process_configs = copy.deepcopy(process_configs or {})
    pm._active_wires = {}

    # Заполнить реестр реальными MockProcess для каждого конфига
    for pname in pm._process_configs:
        proc = MockProcess(pname, alive=True, pid=hash(pname) % 10000)
        registry._processes[pname] = proc

    # Логирование — заглушки (ObservableMixin)
    pm._log_info = MagicMock()
    pm._log_warning = MagicMock()
    pm._log_error = MagicMock()

    # get_config — возвращает None для любого ключа (или разумные defaults)
    def _get_config(key: str):
        defaults = {"stop_process_timeout": 1.0, "shutdown_timeout": 1.0}
        return defaults.get(key)

    pm.get_config = _get_config

    return pm


# ===========================================================================
# Тесты
# ===========================================================================


class TestReplaceBlueprint:
    """Happy path тесты."""

    def test_replace_empty_blueprint_success(self) -> None:
        """Пустой новый blueprint, нет незащищённых → success, replaced=[]."""
        pm = make_pm()
        result = pm.replace_blueprint({})

        assert result["success"] is True
        assert result["replaced"] == []
        assert result["rolled_back"] is False
        assert result["error"] is None

    def test_replace_one_process(self) -> None:
        """1 незащищённый процесс, замена на новый → старый остановлен, новый запущен."""
        pm = make_pm({"worker_1": {"class": "mod.Worker", "priority": "normal"}})

        new_blueprint = {
            "processes": [{"process_name": "worker_2", "process_class": "mod.Worker2", "priority": "normal"}]
        }
        result = pm.replace_blueprint(new_blueprint)

        assert result["success"] is True
        assert "worker_1" in result["replaced"]
        assert result["rolled_back"] is False
        # worker_2 должен быть в _process_configs
        assert "worker_2" in pm._process_configs
        # worker_1 должен быть удалён из _process_configs
        assert "worker_1" not in pm._process_configs

    def test_replace_multiple_processes(self) -> None:
        """3 незащищённых → заменить на 2 новых."""
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
        result = pm.replace_blueprint(new_blueprint)

        assert result["success"] is True
        assert sorted(result["replaced"]) == ["w1", "w2", "w3"]
        assert "n1" in pm._process_configs
        assert "n2" in pm._process_configs
        assert "w1" not in pm._process_configs

    def test_no_rollback_on_success(self) -> None:
        """Успешный replace → rolled_back=False."""
        pm = make_pm({"w1": {"class": "m.W1"}})

        result = pm.replace_blueprint({"processes": [{"process_name": "w2", "process_class": "m.W2"}]})
        assert result["rolled_back"] is False

    def test_replace_empty_processes_in_new_blueprint(self) -> None:
        """new_blueprint = {"processes": []} → все незащищённые остановлены, ничего не запущено."""
        pm = make_pm(
            {
                "w1": {"class": "m.W1"},
                "w2": {"class": "m.W2"},
            }
        )

        result = pm.replace_blueprint({"processes": []})

        assert result["success"] is True
        assert sorted(result["replaced"]) == ["w1", "w2"]
        # _process_configs должен быть пуст (нет protected, новых нет)
        assert pm._process_configs == {}


class TestProtected:
    """Тесты protected-процессов."""

    def test_replace_skips_protected(self) -> None:
        """Процесс с protected=True не останавливается при replace.

        AC: MockProcess.start() для protected НЕ вызывается повторно.
        """
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
        result = pm.replace_blueprint(new_blueprint)

        assert result["success"] is True
        assert "gui" in result["skipped_protected"]
        assert "worker" in result["replaced"]
        # gui-процесс не был остановлен (alive не менялся)
        assert gui_proc._alive is True
        # start() для protected НЕ вызывался
        assert gui_proc._started is False, "start() не должен вызываться для protected-процесса"
        # gui остался в _process_configs
        assert "gui" in pm._process_configs

    def test_replace_self_is_always_protected(self) -> None:
        """ProcessManager сам себя всегда в protected, даже без флага в конфиге."""
        pm = make_pm(
            {
                "ProcessManager": {"class": "m.PM"},
                "worker": {"class": "m.Worker"},
            }
        )

        result = pm.replace_blueprint({"processes": []})

        assert "ProcessManager" in result["skipped_protected"]
        assert "ProcessManager" in pm._process_configs

    def test_protected_names_includes_self(self) -> None:
        """_get_protected_names() всегда содержит имя PM."""
        pm = make_pm()
        protected = pm._get_protected_names()
        assert "ProcessManager" in protected

    def test_protected_flag_from_config(self) -> None:
        """Конфиг с protected=True → имя в _get_protected_names()."""
        pm = make_pm(
            {
                "gui": {"class": "m.GUI", "protected": True},
                "worker": {"class": "m.Worker"},
            }
        )

        protected = pm._get_protected_names()
        assert "gui" in protected
        assert "worker" not in protected

    def test_replace_logs_protected_skipped(self) -> None:
        """Логируется информация о пропущенных protected-процессах."""
        pm = make_pm(
            {
                "gui": {"class": "m.GUI", "protected": True},
                "worker": {"class": "m.Worker"},
            }
        )

        pm.replace_blueprint({"processes": []})

        # Проверяем что _log_info вызывался с упоминанием protected
        info_calls = [str(c) for c in pm._log_info.call_args_list]
        any_protected_logged = any("protected" in call.lower() or "gui" in call for call in info_calls)
        assert any_protected_logged, f"Ожидалось логирование protected-процессов, но вызовы _log_info: {info_calls}"


class TestRollback:
    """Тесты rollback при partial failure."""

    def test_rollback_on_stop_failure(self) -> None:
        """stop_one возвращает False → rolled_back=True, процессы восстановлены."""
        pm = make_pm(
            {"w1": {"class": "m.W1"}, "w2": {"class": "m.W2"}},
            fail_on_stop={"w2"},
        )

        result = pm.replace_blueprint({"processes": [{"process_name": "n1", "process_class": "m.N1"}]})

        assert result["success"] is False
        assert result["rolled_back"] is True

    def test_rollback_on_start_failure(self) -> None:
        """Новый процесс не стартует → rollback, _process_configs восстановлен."""
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

        result = pm.replace_blueprint({"processes": [{"process_name": "n1", "process_class": "m.N1"}]})

        assert result["success"] is False
        assert result["rolled_back"] is True
        # _process_configs должен быть восстановлен (w1 обратно)
        assert "w1" in pm._process_configs
        assert pm._process_configs["w1"]["class"] == snapshot["w1"]["class"]

    def test_rollback_restores_process_configs(self) -> None:
        """После rollback _process_configs равен snapshot до replace."""
        original = {
            "w1": {"class": "m.W1", "priority": "high"},
            "w2": {"class": "m.W2", "priority": "low"},
        }
        pm = make_pm(original, fail_on_stop={"w2"})

        snapshot_before = copy.deepcopy(pm._process_configs)

        pm.replace_blueprint({"processes": []})

        # Все исходные конфиги должны быть восстановлены
        for name in snapshot_before:
            assert name in pm._process_configs
            assert pm._process_configs[name]["class"] == snapshot_before[name]["class"]

    def test_missing_process_class_defaults_to_generic(self) -> None:
        """Процесс без process_class → дефолтный GenericProcess (как boot), без краха.

        Раньше replace передавал raw-dict напрямую и пустой class_path падал
        невнятным "not enough values to unpack" в class_loader. Теперь replace
        трансформирует blueprint ТЕМ ЖЕ путём, что boot (_build_proc_dicts →
        SystemBlueprint.build_configs → process), а GenericProcessConfig.process_class
        дефолтит на GenericProcess. Поэтому пропущенный process_class — не ошибка,
        а штатный дефолт (boot-консистентно). Регресс-гард class vs process_class
        теперь структурный: build() всегда даёт валидный class.
        """
        pm = make_pm({"w1": {"class": "m.W1"}})

        # process_class отсутствует → должен подставиться дефолтный GenericProcess
        result = pm.replace_blueprint({"processes": [{"process_name": "n1"}]})

        assert result["success"] is True
        assert result["rolled_back"] is False
        assert "n1" in pm._process_configs
        # class заполнен дефолтным GenericProcess (не пустой → нет краша class_loader)
        assert "GenericProcess" in pm._process_configs["n1"]["class"]
        assert "w1" not in pm._process_configs  # заменён


class TestBlueprintTransform:
    """Raw-blueprint → канонический proc_dict (фикс «картинка не меняется»)."""

    def test_chain_targets_and_plugins_nested_into_config(self) -> None:
        """chain_targets/plugins из raw-blueprint попадают во вложенный config.

        Регресс-гард корня бага: replace передавал raw recipe-dict напрямую, и
        процесс стартовал без плагинов (PluginOrchestrator не создавался) и без
        маршрутов (chain_targets=[]) → данные не текли в GUI. Теперь _build_proc_dicts
        трансформирует blueprint как boot → config.plugins / config.chain_targets.
        """
        pm = make_pm({"w1": {"class": "m.W1"}})

        result = pm.replace_blueprint(
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

        pm.replace_blueprint({"processes": []})

        mm = pm.shared_resources.memory_manager
        calls = [c[0][0] for c in mm.release_process_memory.call_args_list]
        assert "w1" in calls
        assert "w2" in calls

    def test_shm_cleanup_not_required(self) -> None:
        """shared_resources is None → replace завершается без ошибки."""
        pm = make_pm(
            {"w1": {"class": "m.W1"}},
            shared_resources=None,
        )

        result = pm.replace_blueprint({"processes": []})

        assert result["success"] is True
        assert "w1" in result["replaced"]


class TestBlueprintReplaceCommand:
    """Тесты команды blueprint.replace."""

    def test_cmd_blueprint_replace_registered(self) -> None:
        """command_manager.register_command вызывается с 'blueprint.replace'."""
        pm = make_pm()
        mock_cm = MagicMock()
        mock_cm.register_command.return_value = True
        pm.command_manager = mock_cm

        pm._register_builtin_commands()

        registered_names = [call_args[0][0] for call_args in mock_cm.register_command.call_args_list]
        assert "blueprint.replace" in registered_names

    def test_cmd_blueprint_replace_no_blueprint_arg(self) -> None:
        """Вызов команды без blueprint → {"error": "blueprint required"}."""
        pm = make_pm()

        result = pm._cmd_blueprint_replace()
        assert "error" in result
        assert "blueprint" in result["error"].lower()


class TestEdgeCases:
    """Edge cases и дополнительные проверки."""

    def test_replace_updates_process_configs(self) -> None:
        """После успешного replace _process_configs содержит новые конфиги."""
        pm = make_pm({"w1": {"class": "m.W1"}})

        new_cfg = {"process_name": "new_w", "process_class": "m.New", "priority": "high"}
        pm.replace_blueprint({"processes": [new_cfg]})

        assert "new_w" in pm._process_configs
        # _process_configs нормализован к внутреннему ключу class (= process_class)
        assert pm._process_configs["new_w"]["class"] == "m.New"
        assert "w1" not in pm._process_configs

    def test_replace_none_blueprint_treated_as_empty(self) -> None:
        """new_blueprint = None → трактуется как {}, не падает с AttributeError."""
        pm = make_pm({"w1": {"class": "m.W1"}})

        result = pm.replace_blueprint(None)

        assert result["success"] is True
        assert "w1" in result["replaced"]
        assert pm._process_configs == {}

    def test_double_replace_sees_updated_configs(self) -> None:
        """Двойной вызов replace_blueprint → второй видит актуальный _process_configs."""
        pm = make_pm({"w1": {"class": "m.W1"}})

        # Первый replace: w1 → n1
        pm.replace_blueprint({"processes": [{"process_name": "n1", "process_class": "m.N1"}]})
        assert "n1" in pm._process_configs
        assert "w1" not in pm._process_configs

        # Второй replace: n1 → n2
        pm.replace_blueprint({"processes": [{"process_name": "n2", "process_class": "m.N2"}]})
        assert "n2" in pm._process_configs
        assert "n1" not in pm._process_configs


class TestReplaceBlueprintDebounce:
    """Дебаунс hot-swap: in-flight guard + cooldown (единая точка коалесинга)."""

    def test_in_flight_guard_rejects_reentrant(self) -> None:
        """Пока замена идёт (_replace_in_progress=True) — новый запрос отклоняется."""
        pm = make_pm({"w1": {"class": "m.W1"}})
        pm._replace_in_progress = True

        result = pm.replace_blueprint({"processes": [{"process_name": "n1", "process_class": "m.N1"}]})

        assert result["success"] is False
        assert result["debounced"] is True
        # Реальная замена не выполнялась — w1 на месте.
        assert "w1" in pm._process_configs
        assert "n1" not in pm._process_configs

    def test_cooldown_rejects_rapid_second(self) -> None:
        """С replace_debounce_s>0 повторный запрос в окне после завершения — отклоняется."""
        pm = make_pm({"w1": {"class": "m.W1"}})
        pm.get_config = lambda key: {"stop_process_timeout": 1.0, "replace_debounce_s": 10.0}.get(key)

        # Первая замена проходит (last_replace_ts по умолчанию 0 → окно давно вышло).
        r1 = pm.replace_blueprint({"processes": [{"process_name": "n1", "process_class": "m.N1"}]})
        assert r1["success"] is True

        # Вторая сразу же — внутри cooldown (10с) → debounced, n1 остаётся.
        r2 = pm.replace_blueprint({"processes": [{"process_name": "n2", "process_class": "m.N2"}]})
        assert r2["success"] is False
        assert r2["debounced"] is True
        assert "n1" in pm._process_configs
        assert "n2" not in pm._process_configs

    def test_cooldown_zero_disables_debounce(self) -> None:
        """replace_debounce_s=0 (дефолт тестов) → дебаунс выключен, двойная замена работает."""
        pm = make_pm({"w1": {"class": "m.W1"}})
        # get_config по умолчанию возвращает None для replace_debounce_s → 0.0.
        pm.replace_blueprint({"processes": [{"process_name": "n1", "process_class": "m.N1"}]})
        pm.replace_blueprint({"processes": [{"process_name": "n2", "process_class": "m.N2"}]})
        assert "n2" in pm._process_configs
        assert "n1" not in pm._process_configs

    def test_in_flight_flag_cleared_after_replace(self) -> None:
        """После замены флаг _replace_in_progress снят (finally), следующая проходит."""
        pm = make_pm({"w1": {"class": "m.W1"}})
        pm.replace_blueprint({"processes": [{"process_name": "n1", "process_class": "m.N1"}]})
        assert pm._replace_in_progress is False
        assert pm._last_replace_ts > 0.0
