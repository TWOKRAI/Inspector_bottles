"""Тесты FullReplacePlanner — стратегия полной замены (Task 2.1).

Покрытие:
- commands даёт порядок: stop_all → cleanup → provision → create → start.
- Фаза stop — одна bulk-команда process.stop_all (паритет stop_many дороги B).
- protected исключены из ВСЕХ фаз.
- Невалидный blueprint (proc_dicts_fn бросает BlueprintInvalid) →
  commands пробрасывает ДО любой stop-команды.
- old берётся из current_provider (не из аргумента current):
  current=None, current_provider→{a,b} → stop_all/cleanup для a,b.
- diff и commands согласованы: команды покрывают ровно old ∪ new.
- Observability: fake stats получает planner.commands metric.
- Lifecycle: initialize/shutdown.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from multiprocess_prototype.backend.assembly.assembler import BlueprintInvalid
from multiprocess_prototype.backend.assembly.planner import FullReplacePlanner


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class FakeLogger:
    """Минимальный fake logger."""

    def __init__(self) -> None:
        self.messages: list[tuple[str, str]] = []

    def info(self, msg: str, **kw) -> None:
        self.messages.append(("info", msg))

    def warning(self, msg: str, **kw) -> None:
        self.messages.append(("warning", msg))

    def error(self, msg: str, **kw) -> None:
        self.messages.append(("error", msg))

    def debug(self, msg: str, **kw) -> None:
        self.messages.append(("debug", msg))


class FakeStats:
    """Минимальный fake stats."""

    def __init__(self) -> None:
        self.metrics: list[tuple[str, ...]] = []
        self.timings: list[tuple[str, ...]] = []

    def record_metric(self, name: str, value=1, tags=None) -> None:
        self.metrics.append((name, value, tags))

    def record_timing(self, name: str, duration: float, tags=None) -> None:
        self.timings.append((name, duration, tags))


def _make_planner(
    proc_dicts: dict[str, dict] | None = None,
    protected: set[str] | None = None,
    current: set[str] | None = None,
    *,
    proc_dicts_fn=None,
    logger=None,
    stats=None,
) -> FullReplacePlanner:
    """Создать FullReplacePlanner с fake-провайдерами.

    Args:
        proc_dicts: что вернёт proc_dicts_fn (по умолчанию).
        protected: что вернёт protected_provider.
        current: что вернёт current_provider (non-protected живые).
        proc_dicts_fn: кастомный callable (перекрывает proc_dicts).
    """
    if proc_dicts_fn is None:
        _pd = proc_dicts or {}
        proc_dicts_fn = MagicMock(return_value=_pd)

    return FullReplacePlanner(
        proc_dicts_fn=proc_dicts_fn,
        protected_provider=lambda: protected or set(),
        current_provider=lambda: current or set(),
        logger=logger,
        stats=stats,
    )


# ===========================================================================
# Lifecycle
# ===========================================================================


class TestPlannerLifecycle:
    def test_initialize(self) -> None:
        p = _make_planner()
        assert not p.is_initialized
        assert p.initialize() is True
        assert p.is_initialized

    def test_shutdown(self) -> None:
        p = _make_planner()
        p.initialize()
        assert p.shutdown() is True
        assert not p.is_initialized


# ===========================================================================
# diff
# ===========================================================================


class TestPlannerDiff:
    def test_always_has_changes(self) -> None:
        """Full-replace: diff ВСЕГДА возвращает has_changes=True."""
        p = _make_planner()
        result = p.diff(None, {"processes": []})
        assert result["has_changes"] is True

    def test_with_current(self) -> None:
        """diff с непустой current тоже has_changes=True."""
        p = _make_planner()
        result = p.diff({"old": True}, {"new": True})
        assert result["has_changes"] is True


# ===========================================================================
# commands — порядок фаз
# ===========================================================================


class TestPlannerCommandsOrder:
    def test_stop_all_cleanup_provision_create_start(self) -> None:
        """commands даёт порядок: stop_all → cleanup → provision → create → start."""
        proc_dicts = {
            "new_a": {"class": "A"},
            "new_b": {"class": "B"},
        }
        p = _make_planner(
            proc_dicts=proc_dicts,
            current={"old_x", "old_y"},
        )
        cmds = p.commands({"has_changes": True}, {"desired": True})

        # Извлечь типы команд по порядку
        cmd_types = [c["cmd"] for c in cmds]

        # Фаза A: 1 bulk stop_all (вместо N×process.stop)
        assert cmd_types.count("process.stop_all") == 1
        assert cmd_types.count("process.stop") == 0  # больше нет per-process stop
        assert cmd_types.count("process.cleanup") == 2
        assert cmd_types.count("process.provision") == 2
        assert cmd_types.count("process.create") == 2
        assert cmd_types.count("process.start") == 2

        # Проверить порядок фаз (stop_all ПЕРЕД cleanup ПЕРЕД ...)
        stop_all_idx = cmd_types.index("process.stop_all")
        cleanup_start = min(i for i, c in enumerate(cmds) if c["cmd"] == "process.cleanup")
        cleanup_end = max(i for i, c in enumerate(cmds) if c["cmd"] == "process.cleanup")
        provision_start = min(i for i, c in enumerate(cmds) if c["cmd"] == "process.provision")
        provision_end = max(i for i, c in enumerate(cmds) if c["cmd"] == "process.provision")
        create_start = min(i for i, c in enumerate(cmds) if c["cmd"] == "process.create")
        create_end = max(i for i, c in enumerate(cmds) if c["cmd"] == "process.create")
        start_start = min(i for i, c in enumerate(cmds) if c["cmd"] == "process.start")

        assert stop_all_idx < cleanup_start
        assert cleanup_end < provision_start
        assert provision_end < create_start
        assert create_end < start_start

    def test_stop_all_contains_old_names(self) -> None:
        """stop_all содержит sorted(old) имена; cleanup/provision/create/start — per-process."""
        proc_dicts = {"alpha": {"class": "A"}, "beta": {"class": "B"}}
        p = _make_planner(proc_dicts=proc_dicts, current={"gamma", "delta"})
        cmds = p.commands({"has_changes": True}, {})

        # stop_all — одна команда с process_names
        stop_all_cmds = [c for c in cmds if c["cmd"] == "process.stop_all"]
        assert len(stop_all_cmds) == 1
        assert set(stop_all_cmds[0]["process_names"]) == {"gamma", "delta"}
        assert stop_all_cmds[0]["process_names"] == sorted({"gamma", "delta"})

        cleanup_names = {c["process_name"] for c in cmds if c["cmd"] == "process.cleanup"}
        provision_names = {c["process_name"] for c in cmds if c["cmd"] == "process.provision"}
        create_names = {c["process_name"] for c in cmds if c["cmd"] == "process.create"}
        start_names = {c["process_name"] for c in cmds if c["cmd"] == "process.start"}

        assert cleanup_names == {"gamma", "delta"}
        assert provision_names == {"alpha", "beta"}
        assert create_names == {"alpha", "beta"}
        assert start_names == {"alpha", "beta"}


# ===========================================================================
# commands — protected
# ===========================================================================


class TestPlannerProtected:
    def test_protected_excluded_from_all_phases(self) -> None:
        """protected исключены из всех фаз.

        current_provider уже возвращает non-protected имена (фильтрация
        на стороне PM). Но proc_dicts может содержать protected-имя —
        planner обязан исключить его из new-фаз.
        """
        # "gui" — protected; proc_dicts_fn вернёт его, но planner исключает
        proc_dicts = {
            "gui": {"class": "GUI"},  # protected в proc_dicts
            "worker": {"class": "W"},
        }
        p = _make_planner(
            proc_dicts=proc_dicts,
            protected={"gui"},
            # current_provider уже без gui (PM фильтрует)
            current={"old_worker"},
        )
        cmds = p.commands({"has_changes": True}, {})

        # gui не должен появляться ни в каких командах
        all_per_process = {c["process_name"] for c in cmds if "process_name" in c}
        all_bulk_names: set[str] = set()
        for c in cmds:
            if "process_names" in c:
                all_bulk_names.update(c["process_names"])
        assert "gui" not in all_per_process
        assert "gui" not in all_bulk_names

        # old_worker — не protected, должен быть в stop_all
        stop_all_cmds = [c for c in cmds if c["cmd"] == "process.stop_all"]
        assert len(stop_all_cmds) == 1
        assert "old_worker" in stop_all_cmds[0]["process_names"]

        # worker — не protected, должен быть в provision/create/start
        start_names = {c["process_name"] for c in cmds if c["cmd"] == "process.start"}
        assert "worker" in start_names

    def test_all_protected_empty_commands(self) -> None:
        """Если все процессы protected → пустой список команд."""
        proc_dicts = {"gui": {"class": "G"}}
        p = _make_planner(
            proc_dicts=proc_dicts,
            protected={"gui"},
            current=set(),
        )
        cmds = p.commands({"has_changes": True}, {})
        assert cmds == []


# ===========================================================================
# commands — BlueprintInvalid
# ===========================================================================


class TestPlannerBlueprintInvalid:
    def test_invalid_blueprint_raises_before_stop(self) -> None:
        """proc_dicts_fn бросает BlueprintInvalid → commands пробрасывает,
        ни одной stop-команды не генерируется."""

        def bad_proc_dicts_fn(desired):
            raise BlueprintInvalid(["поле X обязательно"])

        p = _make_planner(
            proc_dicts_fn=bad_proc_dicts_fn,
            current={"running_1", "running_2"},
        )

        with pytest.raises(BlueprintInvalid):
            p.commands({"has_changes": True}, {"bad": True})


# ===========================================================================
# commands — current_provider (не аргумент current)
# ===========================================================================


class TestPlannerCurrentProvider:
    def test_old_from_provider_not_argument(self) -> None:
        """old берётся из current_provider, не из аргумента.

        current=None (первый switch), current_provider→{a,b} →
        stop_all/cleanup для a,b.
        """
        proc_dicts = {"new_x": {"class": "X"}}
        p = _make_planner(
            proc_dicts=proc_dicts,
            current={"boot_a", "boot_b"},
        )
        # diff с current=None (первый switch — topology менеджер не видел boot)
        cmds = p.commands({"has_changes": True}, {"desired": True})

        stop_all_cmds = [c for c in cmds if c["cmd"] == "process.stop_all"]
        cleanup_names = {c["process_name"] for c in cmds if c["cmd"] == "process.cleanup"}

        assert len(stop_all_cmds) == 1
        assert set(stop_all_cmds[0]["process_names"]) == {"boot_a", "boot_b"}
        assert cleanup_names == {"boot_a", "boot_b"}


# ===========================================================================
# commands — согласованность diff и commands
# ===========================================================================


class TestPlannerConsistency:
    def test_commands_cover_old_and_new(self) -> None:
        """Команды покрывают ровно old ∪ new (без protected)."""
        proc_dicts = {"n1": {"class": "N1"}, "n2": {"class": "N2"}}
        p = _make_planner(
            proc_dicts=proc_dicts,
            current={"o1", "o2"},
            protected=set(),
        )
        cmds = p.commands({"has_changes": True}, {})

        # stop_all содержит old-имена, per-process — new-имена
        stop_all_names = set()
        per_process_names = set()
        for c in cmds:
            if c["cmd"] == "process.stop_all":
                stop_all_names.update(c["process_names"])
            elif "process_name" in c:
                per_process_names.add(c["process_name"])
        all_names = stop_all_names | per_process_names
        assert all_names == {"o1", "o2", "n1", "n2"}

    def test_empty_current_only_new(self) -> None:
        """Пустой current → нет stop_all, только provision/create/start для новых."""
        proc_dicts = {"x": {"class": "X"}}
        p = _make_planner(proc_dicts=proc_dicts, current=set())
        cmds = p.commands({"has_changes": True}, {})

        cmd_types = {c["cmd"] for c in cmds}
        assert "process.stop_all" not in cmd_types
        assert "process.stop" not in cmd_types
        assert "process.cleanup" not in cmd_types
        assert "process.provision" in cmd_types
        assert "process.create" in cmd_types
        assert "process.start" in cmd_types

    def test_empty_new_only_stop_all_cleanup(self) -> None:
        """Пустой proc_dicts → только stop_all + cleanup для старых."""
        p = _make_planner(proc_dicts={}, current={"old_1"})
        cmds = p.commands({"has_changes": True}, {})

        cmd_types = {c["cmd"] for c in cmds}
        assert "process.stop_all" in cmd_types
        assert "process.stop" not in cmd_types
        assert "process.cleanup" in cmd_types
        assert "process.provision" not in cmd_types
        assert "process.create" not in cmd_types
        assert "process.start" not in cmd_types

    def test_proc_dict_passed_in_commands(self) -> None:
        """provision и create содержат proc_dict для каждого нового процесса."""
        proc_dicts = {"w1": {"class": "W1", "config": {"key": 1}}}
        p = _make_planner(proc_dicts=proc_dicts, current=set())
        cmds = p.commands({"has_changes": True}, {})

        provision_cmds = [c for c in cmds if c["cmd"] == "process.provision"]
        create_cmds = [c for c in cmds if c["cmd"] == "process.create"]

        assert len(provision_cmds) == 1
        assert provision_cmds[0]["proc_dict"] == proc_dicts["w1"]
        assert len(create_cmds) == 1
        assert create_cmds[0]["proc_dict"] == proc_dicts["w1"]


# ===========================================================================
# Observability
# ===========================================================================


class TestPlannerProtectedConflictsB2:
    """B-2 (RS-3): расхождение конфига protected-процесса → не тихий успех."""

    def _make_planner_with_live(self, proc_dicts, protected, live_configs):
        """Планировщик с protected_config_provider из словаря живых конфигов."""
        return FullReplacePlanner(
            proc_dicts_fn=MagicMock(return_value=proc_dicts),
            protected_provider=lambda: set(protected),
            current_provider=lambda: set(),
            protected_config_provider=lambda name: live_configs.get(name),
        )

    def test_divergent_protected_config_recorded(self) -> None:
        """protected 'devices' с ИНЫМ конфигом в новом рецепте → конфликт зафиксирован."""
        proc_dicts = {
            "devices": {"class": "DeviceHub", "protected": True, "config": {"port": 9999}},
            "worker": {"class": "W"},
        }
        live = {"devices": {"class": "DeviceHub", "protected": True, "config": {"port": 1234}}}
        p = self._make_planner_with_live(proc_dicts, {"devices"}, live)

        cmds = p.commands({"has_changes": True}, {})

        # Расхождение зафиксировано (switch не «тихо успешен»)
        assert p.last_protected_conflicts == ["devices"]
        # protected НЕ появляется в командах (не рестартится)
        per_process = {c.get("process_name") for c in cmds}
        assert "devices" not in per_process
        # worker (non-protected) применяется штатно
        assert "worker" in per_process

    def test_identical_protected_config_no_conflict(self) -> None:
        """protected с ИДЕНТИЧНЫМ конфигом → нет конфликта (штатный switch)."""
        proc_dicts = {
            "devices": {"class": "DeviceHub", "protected": True, "config": {"port": 1234}},
        }
        live = {"devices": {"class": "DeviceHub", "protected": True, "config": {"port": 1234}}}
        p = self._make_planner_with_live(proc_dicts, {"devices"}, live)

        p.commands({"has_changes": True}, {})
        assert p.last_protected_conflicts == []

    def test_no_live_config_no_conflict(self) -> None:
        """Нет живого конфига (первый boot protected) → нечего сравнивать."""
        proc_dicts = {"devices": {"class": "D", "protected": True}}
        p = self._make_planner_with_live(proc_dicts, {"devices"}, {})
        p.commands({"has_changes": True}, {})
        assert p.last_protected_conflicts == []

    def test_new_blueprint_protected_added_to_protected_set(self) -> None:
        """Процесс, protected в НОВОМ рецепте → исключён из new-фаз (old∪new)."""
        proc_dicts = {"gui": {"class": "GUI", "protected": True}, "w": {"class": "W"}}
        # provider живых protected пуст — protected берётся из нового blueprint
        p = FullReplacePlanner(
            proc_dicts_fn=MagicMock(return_value=proc_dicts),
            protected_provider=lambda: set(),
            current_provider=lambda: set(),
        )
        cmds = p.commands({"has_changes": True}, {})
        per_process = {c.get("process_name") for c in cmds}
        assert "gui" not in per_process  # protected в новом рецепте — не спавнится как non-protected
        assert "w" in per_process


class TestPlannerObservability:
    def test_record_metric_planner_commands(self) -> None:
        """commands → _record_metric("planner.commands", N) доходит до fake stats."""
        fake_stats = FakeStats()
        proc_dicts = {"a": {"class": "A"}, "b": {"class": "B"}}
        p = _make_planner(
            proc_dicts=proc_dicts,
            current={"old"},
            stats=fake_stats,
        )
        p.commands({"has_changes": True}, {})

        metric_names = [m[0] for m in fake_stats.metrics]
        assert "planner.commands" in metric_names
        # Значение = количество команд (1 stop_all + 1 cleanup + 2 provision + 2 create + 2 start = 8)
        planner_metric = [m for m in fake_stats.metrics if m[0] == "planner.commands"]
        assert planner_metric[0][1] == 8

    def test_log_info_on_commands(self) -> None:
        """commands → _log_info доходит до fake logger."""
        fake_logger = FakeLogger()
        p = _make_planner(
            proc_dicts={"x": {"class": "X"}},
            current=set(),
            logger=fake_logger,
        )
        p.commands({"has_changes": True}, {})
        info_msgs = [m for level, m in fake_logger.messages if level == "info"]
        assert len(info_msgs) >= 1

    def test_log_info_on_diff(self) -> None:
        """diff → _log_info доходит до fake logger."""
        fake_logger = FakeLogger()
        p = _make_planner(logger=fake_logger)
        p.diff(None, {"processes": [{"process_name": "x"}]})
        info_msgs = [m for level, m in fake_logger.messages if level == "info"]
        assert len(info_msgs) >= 1
