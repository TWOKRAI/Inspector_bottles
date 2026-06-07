"""Тесты TopologyManager — 6 типов команд, apply, observability (Task 2.0).

Покрытие:
- 6 типов команд: stop_all, stop, cleanup, provision, create, start — каждый зовёт свой сид.
- process.stop_all: bulk-параллельная остановка (паритет stop_many дороги B).
- apply: порядок исполнения, коммит _current_topology при успехе.
- apply: НЕ коммитит при exception (hard-fail).
- apply: НЕ коммитит при soft-fail (сид вернул success=False).
- Back-compat: register_update → success True; конструктор без новых сидов.
- Observability: _log_info/_record_metric доходят до fake-менеджеров.
- Lifecycle: initialize/shutdown.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from ..process.topology_manager import TopologyManager


# ---------------------------------------------------------------------------
# Фикстуры
# ---------------------------------------------------------------------------


class FakeLogger:
    """Минимальный fake logger для проверки observability."""

    def __init__(self) -> None:
        self.messages: list[tuple[str, str]] = []

    def info(self, msg: str, **kwargs) -> None:
        self.messages.append(("info", msg))

    def warning(self, msg: str, **kwargs) -> None:
        self.messages.append(("warning", msg))

    def error(self, msg: str, **kwargs) -> None:
        self.messages.append(("error", msg))

    def debug(self, msg: str, **kwargs) -> None:
        self.messages.append(("debug", msg))

    def critical(self, msg: str, **kwargs) -> None:
        self.messages.append(("critical", msg))


class FakeStats:
    """Минимальный fake stats для проверки observability."""

    def __init__(self) -> None:
        self.metrics: list[tuple[str, ...]] = []
        self.timings: list[tuple[str, ...]] = []

    def record_metric(self, name: str, value=1, tags=None) -> None:
        self.metrics.append((name, value, tags))

    def record_timing(self, name: str, duration: float, tags=None) -> None:
        self.timings.append((name, duration, tags))


class FakeError:
    """Минимальный fake error manager."""

    def __init__(self) -> None:
        self.errors: list[tuple] = []

    def track_error(self, error: Exception, context: dict | None = None) -> None:
        self.errors.append((error, context))


def _make_seeds():
    """Создать fake-сиды — MagicMock'и, чтобы следить за вызовами."""
    return {
        "stop": MagicMock(return_value=True),
        "stop_all": MagicMock(return_value=True),
        "cleanup": MagicMock(return_value=True),
        "provision": MagicMock(return_value=True),
        "create": MagicMock(return_value=True),
        "start": MagicMock(return_value=True),
    }


def _make_tm(
    seeds: dict | None = None,
    diff_fn=None,
    commands_fn=None,
    *,
    logger=None,
    error=None,
    stats=None,
) -> TopologyManager:
    """Создать TopologyManager с fake-сидами и опциональной observability."""
    s = seeds or _make_seeds()
    return TopologyManager(
        create_process_fn=s.get("create"),
        stop_process_fn=s.get("stop"),
        stop_all_process_fn=s.get("stop_all"),
        cleanup_process_fn=s.get("cleanup"),
        provision_process_fn=s.get("provision"),
        start_process_fn=s.get("start"),
        diff_fn=diff_fn,
        commands_fn=commands_fn,
        logger=logger,
        error=error,
        stats=stats,
    )


# ===========================================================================
# Тесты
# ===========================================================================


class TestTopologyManagerLifecycle:
    """BaseManager lifecycle: initialize / shutdown."""

    def test_initialize(self) -> None:
        tm = _make_tm()
        assert not tm.is_initialized
        assert tm.initialize() is True
        assert tm.is_initialized

    def test_shutdown(self) -> None:
        tm = _make_tm()
        tm.initialize()
        tm._current_topology = {"some": "data"}
        assert tm.shutdown() is True
        assert not tm.is_initialized
        assert tm._current_topology is None


class TestExecuteCommand:
    """Каждый тип команды вызывает ровно свой сид."""

    def test_process_stop_all_success(self) -> None:
        """process.stop_all вызывает stop_all_process_fn с list имён."""
        seeds = _make_seeds()
        tm = _make_tm(seeds)
        result = tm._execute_command({"cmd": "process.stop_all", "process_names": ["A", "B"]})
        assert result["success"] is True
        assert result["process_names"] == ["A", "B"]
        seeds["stop_all"].assert_called_once_with(["A", "B"])
        # Одиночный stop НЕ вызван
        seeds["stop"].assert_not_called()

    def test_process_stop_all_failure(self) -> None:
        """stop_all_process_fn вернул False → success=False."""
        seeds = _make_seeds()
        seeds["stop_all"].return_value = False
        tm = _make_tm(seeds)
        result = tm._execute_command({"cmd": "process.stop_all", "process_names": ["X"]})
        assert result["success"] is False

    def test_process_stop_all_not_configured(self) -> None:
        """process.stop_all без сида → success=False, error."""
        tm = TopologyManager()
        result = tm._execute_command({"cmd": "process.stop_all", "process_names": ["A"]})
        assert result["success"] is False
        assert "not configured" in result.get("error", "")

    def test_process_stop(self) -> None:
        seeds = _make_seeds()
        tm = _make_tm(seeds)
        result = tm._execute_command({"cmd": "process.stop", "process_name": "A"})
        assert result["success"] is True
        seeds["stop"].assert_called_once_with("A")
        seeds["create"].assert_not_called()
        seeds["provision"].assert_not_called()
        seeds["start"].assert_not_called()
        seeds["cleanup"].assert_not_called()

    def test_process_cleanup(self) -> None:
        seeds = _make_seeds()
        tm = _make_tm(seeds)
        result = tm._execute_command({"cmd": "process.cleanup", "process_name": "B"})
        assert result["success"] is True
        seeds["cleanup"].assert_called_once_with("B")

    def test_process_provision(self) -> None:
        seeds = _make_seeds()
        tm = _make_tm(seeds)
        pd = {"class": "mod.X", "memory": {"slot": (1, (480, 640, 3), "uint8")}}
        result = tm._execute_command({"cmd": "process.provision", "process_name": "C", "proc_dict": pd})
        assert result["success"] is True
        seeds["provision"].assert_called_once_with("C", pd)

    def test_process_create(self) -> None:
        seeds = _make_seeds()
        tm = _make_tm(seeds)
        pd = {"class": "mod.Y"}
        result = tm._execute_command({"cmd": "process.create", "process_name": "D", "proc_dict": pd})
        assert result["success"] is True
        seeds["create"].assert_called_once_with("D", pd)
        # create НЕ вызывает start
        seeds["start"].assert_not_called()

    def test_process_start(self) -> None:
        seeds = _make_seeds()
        tm = _make_tm(seeds)
        result = tm._execute_command({"cmd": "process.start", "process_name": "E"})
        assert result["success"] is True
        seeds["start"].assert_called_once_with("E")

    def test_register_update_backcompat(self) -> None:
        """Back-compat: register_update → success True, не падает."""
        tm = _make_tm()
        result = tm._execute_command({"cmd": "register_update", "process_name": "F"})
        assert result["success"] is True
        assert "note" in result

    def test_unknown_command(self) -> None:
        tm = _make_tm()
        result = tm._execute_command({"cmd": "unknown.foo", "process_name": "X"})
        assert result["success"] is False
        assert "Unknown" in result.get("error", "")

    def test_seed_exception(self) -> None:
        """Exception в сиде ловится, возвращается success=False."""
        seeds = _make_seeds()
        seeds["stop"].side_effect = RuntimeError("boom")
        tm = _make_tm(seeds)
        result = tm._execute_command({"cmd": "process.stop", "process_name": "A"})
        assert result["success"] is False
        assert "boom" in result.get("error", "")


class TestApplyOrdering:
    """apply() исполняет команды строго по порядку списка."""

    def test_provision_create_start_order(self) -> None:
        """provision A, provision B, create A, create B, start A, start B
        → сиды вызваны строго в этом порядке."""
        call_log: list[str] = []

        def stop_fn(n):
            call_log.append(f"stop:{n}")
            return True

        def cleanup_fn(n):
            call_log.append(f"cleanup:{n}")
            return True

        def provision_fn(n, pd):
            call_log.append(f"provision:{n}")
            return True

        def create_fn(n, pd):
            call_log.append(f"create:{n}")
            return True

        def start_fn(n):
            call_log.append(f"start:{n}")
            return True

        commands = [
            {"cmd": "process.provision", "process_name": "A", "proc_dict": {}},
            {"cmd": "process.provision", "process_name": "B", "proc_dict": {}},
            {"cmd": "process.create", "process_name": "A", "proc_dict": {}},
            {"cmd": "process.create", "process_name": "B", "proc_dict": {}},
            {"cmd": "process.start", "process_name": "A"},
            {"cmd": "process.start", "process_name": "B"},
        ]

        diff_fn = MagicMock(return_value={"has_changes": True})
        commands_fn = MagicMock(return_value=commands)

        tm = TopologyManager(
            stop_process_fn=stop_fn,
            cleanup_process_fn=cleanup_fn,
            provision_process_fn=provision_fn,
            create_process_fn=create_fn,
            start_process_fn=start_fn,
            diff_fn=diff_fn,
            commands_fn=commands_fn,
        )

        result = tm.apply({"desired": True})
        assert result["success"] is True
        assert result["applied"] == 6
        assert call_log == [
            "provision:A",
            "provision:B",
            "create:A",
            "create:B",
            "start:A",
            "start:B",
        ]

    def test_full_five_phase_order_with_stop_all(self) -> None:
        """Полный 5-фазный цикл: stop_all → cleanup → provision → create → start."""
        call_log: list[str] = []

        def stop_all_fn(names):
            call_log.append(f"stop_all:{','.join(sorted(names))}")
            return True

        def make_fn(label):
            def fn(name, *args):
                call_log.append(f"{label}:{name}")
                return True

            return fn

        commands = [
            {"cmd": "process.stop_all", "process_names": ["old_1", "old_2"]},
            {"cmd": "process.cleanup", "process_name": "old_1"},
            {"cmd": "process.cleanup", "process_name": "old_2"},
            {"cmd": "process.provision", "process_name": "new_1", "proc_dict": {}},
            {"cmd": "process.provision", "process_name": "new_2", "proc_dict": {}},
            {"cmd": "process.create", "process_name": "new_1", "proc_dict": {}},
            {"cmd": "process.create", "process_name": "new_2", "proc_dict": {}},
            {"cmd": "process.start", "process_name": "new_1"},
            {"cmd": "process.start", "process_name": "new_2"},
        ]

        tm = TopologyManager(
            stop_all_process_fn=stop_all_fn,
            stop_process_fn=make_fn("stop"),
            cleanup_process_fn=make_fn("cleanup"),
            provision_process_fn=make_fn("provision"),
            create_process_fn=make_fn("create"),
            start_process_fn=make_fn("start"),
            diff_fn=MagicMock(return_value={"has_changes": True}),
            commands_fn=MagicMock(return_value=commands),
        )

        result = tm.apply({"desired": True})
        assert result["success"] is True
        assert call_log == [
            "stop_all:old_1,old_2",
            "cleanup:old_1",
            "cleanup:old_2",
            "provision:new_1",
            "provision:new_2",
            "create:new_1",
            "create:new_2",
            "start:new_1",
            "start:new_2",
        ]

    def test_full_five_phase_order_legacy_per_process_stop(self) -> None:
        """Back-compat: per-process stop (legacy) тоже работает."""
        call_log: list[str] = []

        def make_fn(label):
            def fn(name, *args):
                call_log.append(f"{label}:{name}")
                return True

            return fn

        commands = [
            {"cmd": "process.stop", "process_name": "old_1"},
            {"cmd": "process.stop", "process_name": "old_2"},
            {"cmd": "process.cleanup", "process_name": "old_1"},
            {"cmd": "process.cleanup", "process_name": "old_2"},
            {"cmd": "process.provision", "process_name": "new_1", "proc_dict": {}},
            {"cmd": "process.provision", "process_name": "new_2", "proc_dict": {}},
            {"cmd": "process.create", "process_name": "new_1", "proc_dict": {}},
            {"cmd": "process.create", "process_name": "new_2", "proc_dict": {}},
            {"cmd": "process.start", "process_name": "new_1"},
            {"cmd": "process.start", "process_name": "new_2"},
        ]

        tm = TopologyManager(
            stop_process_fn=make_fn("stop"),
            cleanup_process_fn=make_fn("cleanup"),
            provision_process_fn=make_fn("provision"),
            create_process_fn=make_fn("create"),
            start_process_fn=make_fn("start"),
            diff_fn=MagicMock(return_value={"has_changes": True}),
            commands_fn=MagicMock(return_value=commands),
        )

        result = tm.apply({"desired": True})
        assert result["success"] is True
        assert call_log == [
            "stop:old_1",
            "stop:old_2",
            "cleanup:old_1",
            "cleanup:old_2",
            "provision:new_1",
            "provision:new_2",
            "create:new_1",
            "create:new_2",
            "start:new_1",
            "start:new_2",
        ]


class TestApplyFailPaths:
    """apply() НЕ коммитит _current_topology при неуспехе."""

    def _simple_diff(self, current, desired):
        return {"has_changes": True}

    def _simple_commands(self, diff, desired):
        return [
            {"cmd": "process.stop", "process_name": "A"},
            {"cmd": "process.create", "process_name": "B", "proc_dict": {}},
            {"cmd": "process.start", "process_name": "B"},
            {"cmd": "process.start", "process_name": "C"},
        ]

    def test_exception_in_seed_no_commit(self) -> None:
        """Exception в сиде на 2-й из 4 команд → success False, topology НЕ изменён."""
        call_count = {"n": 0}

        def stop_fn(name):
            return True

        def create_fn(name, pd):
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise RuntimeError("inject fail on 2nd cmd")
            return True

        def start_fn(name):
            return True

        tm = TopologyManager(
            stop_process_fn=stop_fn,
            create_process_fn=create_fn,
            start_process_fn=start_fn,
            diff_fn=self._simple_diff,
            commands_fn=self._simple_commands,
        )

        old_topo = {"old": True}
        tm._current_topology = old_topo

        result = tm.apply({"new": True})
        assert result["success"] is False
        # topology НЕ изменена
        assert tm._current_topology is old_topo

    def test_soft_fail_no_commit(self) -> None:
        """Сид вернул success=False (без exception) → apply success False, topology НЕ изменён."""
        seeds = _make_seeds()
        # Второй вызов — create — вернёт False
        seeds["create"].return_value = False

        tm = _make_tm(
            seeds,
            diff_fn=self._simple_diff,
            commands_fn=self._simple_commands,
        )

        old_topo = {"original": True}
        tm._current_topology = old_topo

        result = tm.apply({"new": True})
        assert result["success"] is False
        assert "failed_at" in result
        # topology НЕ изменена
        assert tm._current_topology is old_topo

    def test_success_commits_topology(self) -> None:
        """Все команды успешны → _current_topology обновлён."""
        tm = _make_tm(
            diff_fn=self._simple_diff,
            commands_fn=self._simple_commands,
        )

        assert tm._current_topology is None
        desired = {"new_topo": True}
        result = tm.apply(desired)
        assert result["success"] is True
        assert tm._current_topology == desired

    def test_no_changes_no_commit(self) -> None:
        """diff.has_changes=False → success True, topology НЕ обновлена."""
        tm = _make_tm(
            diff_fn=lambda c, d: {"has_changes": False},
            commands_fn=lambda d, des: [],
        )
        old_topo = {"old": True}
        tm._current_topology = old_topo

        result = tm.apply({"new": True})
        assert result["success"] is True
        assert tm._current_topology is old_topo

    def test_exception_in_diff_fn(self) -> None:
        """Exception в diff_fn → success False, topology НЕ изменён."""

        def bad_diff(c, d):
            raise ValueError("diff explosion")

        tm = _make_tm(diff_fn=bad_diff, commands_fn=lambda d, des: [])
        old_topo = {"old": True}
        tm._current_topology = old_topo

        result = tm.apply({"new": True})
        assert result["success"] is False
        assert tm._current_topology is old_topo


class TestApplyBackcompat:
    """Back-compat: старые конструкции работают без падений."""

    def test_register_update_in_apply(self) -> None:
        """apply со старым register_update → success True."""
        commands = [
            {"cmd": "register_update", "process_name": "X", "data": {}},
        ]
        tm = _make_tm(
            diff_fn=lambda c, d: {"has_changes": True},
            commands_fn=lambda d, des: commands,
        )
        result = tm.apply({"topo": True})
        assert result["success"] is True
        assert tm._current_topology == {"topo": True}

    def test_constructor_without_new_seeds(self) -> None:
        """Старый конструктор (только create_process_fn/stop_process_fn) не падает."""
        tm = TopologyManager(
            create_process_fn=MagicMock(),
            stop_process_fn=MagicMock(),
        )
        assert tm._cleanup_process is None
        assert tm._provision_process is None
        assert tm._start_process is None
        # apply без diff/commands → not configured
        result = tm.apply({"x": True})
        assert result["success"] is False
        assert "not configured" in result.get("error", "")

    def test_configure_new_seeds_after_creation(self) -> None:
        """configure() принимает новые сиды после создания."""
        tm = TopologyManager(
            create_process_fn=MagicMock(),
            stop_process_fn=MagicMock(),
        )
        new_cleanup = MagicMock(return_value=True)
        new_provision = MagicMock(return_value=True)
        tm.configure(
            cleanup_process_fn=new_cleanup,
            provision_process_fn=new_provision,
        )
        assert tm._cleanup_process is new_cleanup
        assert tm._provision_process is new_provision


class TestObservability:
    """TopologyManager — наблюдаемый: логи и метрики доходят до fake-менеджеров."""

    def test_log_info_on_apply(self) -> None:
        """apply → _log_info доходит до fake logger."""
        fake_logger = FakeLogger()
        tm = _make_tm(
            diff_fn=lambda c, d: {"has_changes": True},
            commands_fn=lambda d, des: [],
            logger=fake_logger,
        )
        tm.apply({"x": 1})
        info_msgs = [m for level, m in fake_logger.messages if level == "info"]
        assert len(info_msgs) >= 1, f"Ожидались info-сообщения, получено: {fake_logger.messages}"

    def test_record_metric_on_apply(self) -> None:
        """apply → _record_metric("topology.commands", N) доходит до fake stats."""
        fake_stats = FakeStats()
        commands = [
            {"cmd": "process.start", "process_name": "A"},
            {"cmd": "process.start", "process_name": "B"},
        ]
        seeds = _make_seeds()
        tm = _make_tm(
            seeds,
            diff_fn=lambda c, d: {"has_changes": True},
            commands_fn=lambda d, des: commands,
            stats=fake_stats,
        )
        tm.apply({"x": 1})
        metric_names = [m[0] for m in fake_stats.metrics]
        assert "topology.commands" in metric_names

    def test_record_timing_on_apply(self) -> None:
        """apply → _record_timing("topology.apply_ms", ...) доходит до fake stats."""
        fake_stats = FakeStats()
        tm = _make_tm(
            diff_fn=lambda c, d: {"has_changes": True},
            commands_fn=lambda d, des: [],
            stats=fake_stats,
        )
        tm.apply({"x": 1})
        timing_names = [t[0] for t in fake_stats.timings]
        assert "topology.apply_ms" in timing_names

    def test_track_error_on_exception(self) -> None:
        """Exception в apply → _track_error доходит до fake error manager."""
        fake_error = FakeError()

        def bad_diff(c, d):
            raise RuntimeError("test boom")

        tm = _make_tm(
            diff_fn=bad_diff,
            commands_fn=lambda d, des: [],
            error=fake_error,
        )
        tm.apply({"x": 1})
        assert len(fake_error.errors) >= 1
        assert isinstance(fake_error.errors[0][0], RuntimeError)

    def test_log_error_on_soft_fail(self) -> None:
        """Soft-fail → _log_error вызван."""
        fake_logger = FakeLogger()
        seeds = _make_seeds()
        seeds["stop"].return_value = False

        tm = _make_tm(
            seeds,
            diff_fn=lambda c, d: {"has_changes": True},
            commands_fn=lambda d, des: [{"cmd": "process.stop", "process_name": "X"}],
            logger=fake_logger,
        )
        tm.apply({"x": 1})
        error_msgs = [m for level, m in fake_logger.messages if level == "error"]
        assert len(error_msgs) >= 1


class TestSeedNotConfigured:
    """Команда при отсутствии соответствующего сида → success False (не exception)."""

    def test_stop_all_without_seed(self) -> None:
        tm = TopologyManager()
        result = tm._execute_command({"cmd": "process.stop_all", "process_names": ["A"]})
        assert result["success"] is False
        assert "not configured" in result.get("error", "")

    def test_stop_without_seed(self) -> None:
        tm = TopologyManager()
        result = tm._execute_command({"cmd": "process.stop", "process_name": "A"})
        assert result["success"] is False
        assert "not configured" in result.get("error", "")

    def test_cleanup_without_seed(self) -> None:
        tm = TopologyManager()
        result = tm._execute_command({"cmd": "process.cleanup", "process_name": "A"})
        assert result["success"] is False

    def test_provision_without_seed(self) -> None:
        tm = TopologyManager()
        result = tm._execute_command({"cmd": "process.provision", "process_name": "A", "proc_dict": {}})
        assert result["success"] is False

    def test_create_without_seed(self) -> None:
        tm = TopologyManager()
        result = tm._execute_command({"cmd": "process.create", "process_name": "A", "proc_dict": {}})
        assert result["success"] is False

    def test_start_without_seed(self) -> None:
        tm = TopologyManager()
        result = tm._execute_command({"cmd": "process.start", "process_name": "A"})
        assert result["success"] is False
