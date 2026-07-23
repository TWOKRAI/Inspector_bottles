"""Ф2 Task 2.1 (truth-holes-closure): замена инстанса видима в supervision.status.

Дыра: при дефолтном reuse-очередей ``process.restart`` ОСОЗНАННО не бампает
incarnation (fence-семантика, DECISIONS PMM:311-333), а ``restart_count`` монитора
считает только краш-рестарты — supervision-снимок до и после ручного рестарта
неотличим, хотя инстанс заменён (сменился pid).

Здесь проверяется маркер замены: ``pid`` (истина ОС) + ``instance_restarts``
(безусловный счётчик успешных ``restart_process``) + ``started_at``.
Смена самого pid на живой системе — live-плечо приёмки (mock переиспользует
детерминированный pid по имени).
"""

from unittest.mock import MagicMock, patch

from ..process.process_manager_process import ProcessManagerProcess
from .conftest import MockProcess, make_pm


def _pm_snapshot_ready(pm, snapshot: dict) -> None:
    """Монитор в make_pm — MagicMock; supervision-хендлер ждёт от него dict."""
    pm._process_monitor.get_supervision_snapshot.return_value = snapshot


class TestSupervisionSnapshotFields:
    def test_snapshot_carries_pid_started_at_and_instance_restarts(self) -> None:
        with patch.object(ProcessManagerProcess, "__init__", lambda self, *a, **kw: None):
            pmp = ProcessManagerProcess.__new__(ProcessManagerProcess)
            pmp.name = "ProcessManager"
            pmp._routing_epoch = 2
            pmp._incarnations = {"camera": 0}
            pmp._instance_restarts = {"camera": 3}
            pmp._instance_started_at = {"camera": 1234.5}
            mon = MagicMock()
            mon.get_supervision_snapshot.return_value = {
                "camera": {"status": "running", "last_exit": None, "restart_count": 0},
            }
            pmp._process_monitor = mon
            registry = MagicMock()
            registry.get_process_by_name.return_value = MockProcess("camera", alive=True, pid=4242)
            pmp._process_registry = registry

            res = pmp._cmd_supervision_status()
            cam = res["processes"]["camera"]
            assert cam["pid"] == 4242
            assert cam["alive"] is True
            assert cam["started_at"] == 1234.5
            assert cam["instance_restarts"] == 3
            # Прежние поля не деградировали
            assert cam["incarnation"] == 0
            assert cam["restart_count"] == 0

    def test_snapshot_without_registry_and_counters(self) -> None:
        """PM без реестра/счётчиков (unit-PM с no-op __init__) — не падает,
        новые поля честно null/0, а не выдуманы."""
        with patch.object(ProcessManagerProcess, "__init__", lambda self, *a, **kw: None):
            pmp = ProcessManagerProcess.__new__(ProcessManagerProcess)
            pmp.name = "ProcessManager"
            pmp._routing_epoch = 0
            pmp._incarnations = {"gui": 0}
            mon = MagicMock()
            mon.get_supervision_snapshot.return_value = {
                "gui": {"status": "running", "last_exit": None, "restart_count": 0}
            }
            pmp._process_monitor = mon

            gui = pmp._cmd_supervision_status()["processes"]["gui"]
            assert gui["pid"] is None
            assert gui["alive"] is None
            assert gui["started_at"] is None
            assert gui["instance_restarts"] == 0

    def test_pm_reports_own_pid(self) -> None:
        """Live-находка Ф2 Task 2.1: PM не состоит в собственном реестре, поэтому
        отдавал про СЕБЯ pid=null/alive=null — хотя знает свой pid точно."""
        import os

        with patch.object(ProcessManagerProcess, "__init__", lambda self, *a, **kw: None):
            pmp = ProcessManagerProcess.__new__(ProcessManagerProcess)
            pmp.name = "ProcessManager"
            pmp._routing_epoch = 0
            pmp._incarnations = {"ProcessManager": 0}
            mon = MagicMock()
            mon.get_supervision_snapshot.return_value = {
                "ProcessManager": {"status": "running", "last_exit": None, "restart_count": 0}
            }
            pmp._process_monitor = mon
            registry = MagicMock()
            registry.get_process_by_name.return_value = None
            pmp._process_registry = registry

            pm_row = pmp._cmd_supervision_status()["processes"]["ProcessManager"]
            assert pm_row["pid"] == os.getpid()
            assert pm_row["alive"] is True

    def test_absent_child_stays_null(self) -> None:
        """Контраст: у ребёнка, которого нет в реестре, pid/alive остаются null —
        подстановка своего pid не растекается на чужие имена."""
        with patch.object(ProcessManagerProcess, "__init__", lambda self, *a, **kw: None):
            pmp = ProcessManagerProcess.__new__(ProcessManagerProcess)
            pmp.name = "ProcessManager"
            pmp._routing_epoch = 0
            pmp._incarnations = {"cam": 0}
            mon = MagicMock()
            mon.get_supervision_snapshot.return_value = {"cam": {"status": "dead", "last_exit": 1, "restart_count": 0}}
            pmp._process_monitor = mon
            registry = MagicMock()
            registry.get_process_by_name.return_value = None
            pmp._process_registry = registry

            cam = pmp._cmd_supervision_status()["processes"]["cam"]
            assert cam["pid"] is None
            assert cam["alive"] is None

    def test_process_known_only_by_instance_restarts_is_listed(self) -> None:
        """Процесс, которого нет в monitor-срезе, но который рестартовали,
        не должен исчезать из снимка."""
        with patch.object(ProcessManagerProcess, "__init__", lambda self, *a, **kw: None):
            pmp = ProcessManagerProcess.__new__(ProcessManagerProcess)
            pmp.name = "ProcessManager"
            pmp._routing_epoch = 0
            pmp._incarnations = {}
            pmp._instance_restarts = {"cam": 1}
            mon = MagicMock()
            mon.get_supervision_snapshot.return_value = {}
            pmp._process_monitor = mon

            res = pmp._cmd_supervision_status()
            assert res["processes"]["cam"]["instance_restarts"] == 1


class TestManualRestartCounter:
    def test_reuse_restart_bumps_instance_restarts_not_incarnation(self) -> None:
        """Ядро задачи: reuse-рестарт (дефолт) — incarnation прежняя, но
        instance_restarts вырос и started_at обновился.

        Оговорка (ревью Fable): в mock-реестре очередей нет, поэтому
        ``ids_before == ids_after == {}`` — «reuse» здесь доказан отсутствием
        очередей, а не их переиспользованием. Кодовый путь сравнения ids тот же,
        что в проде, контраст даёт соседний тест (форс расхождения ids), а
        настоящее reuse-плечо с живыми очередями — live (Ф5 / Task 4.4).
        """
        pm = make_pm({"worker": {"class": "m.W", "priority": "normal"}})
        pm.send_message = MagicMock()
        pm._broadcast_routing_refresh = MagicMock()
        pm._publish_process_identity = MagicMock()
        pm._replay_telemetry_runtime_delta = MagicMock()

        inc_before = dict(getattr(pm, "_incarnations", {}))
        assert pm.restart_process("worker") is True
        assert pm.restart_process("worker") is True

        # reuse-очередей: identity не менялась → incarnation осталась прежней
        assert getattr(pm, "_incarnations", {}).get("worker", 0) == inc_before.get("worker", 0)
        # …но замена инстанса ВИДНА
        assert pm._instance_restarts["worker"] == 2
        assert pm._instance_started_at["worker"] > 0

    def test_no_reuse_restart_still_bumps_incarnation(self) -> None:
        """Контраст: при смене identity очередей incarnation бампается как раньше —
        новый счётчик ничего не сломал."""
        pm = make_pm({"worker": {"class": "m.W", "priority": "normal"}})
        pm.send_message = MagicMock()
        pm._broadcast_routing_refresh = MagicMock()
        pm._publish_process_identity = MagicMock()
        pm._replay_telemetry_runtime_delta = MagicMock()
        # Форсируем ids_before != ids_after (как в test_routing_epoch)
        seq = iter([{"data": 1}, {"data": 2}])
        pm._process_queue_ids = lambda name: next(seq, {"data": 2})

        assert pm.restart_process("worker") is True
        assert pm._incarnations.get("worker") == 1
        assert pm._instance_restarts["worker"] == 1

    def test_failed_restart_does_not_count(self) -> None:
        """Несуществующий процесс → рестарта не было → счётчик не растёт."""
        pm = make_pm({})
        assert pm.restart_process("ghost") is False
        assert getattr(pm, "_instance_restarts", {}).get("ghost", 0) == 0

    def test_restart_counter_visible_in_supervision_snapshot(self) -> None:
        """Сквозное: рестарт → тот же PM отдаёт instance_restarts наружу."""
        pm = make_pm({"worker": {"class": "m.W", "priority": "normal"}})
        pm.send_message = MagicMock()
        pm._broadcast_routing_refresh = MagicMock()
        pm._publish_process_identity = MagicMock()
        pm._replay_telemetry_runtime_delta = MagicMock()
        _pm_snapshot_ready(pm, {"worker": {"status": "running", "last_exit": None, "restart_count": 0}})

        assert pm.restart_process("worker") is True
        worker = pm._cmd_supervision_status()["processes"]["worker"]
        assert worker["instance_restarts"] == 1
        assert worker["restart_count"] == 0, "краш-счётчик монитора не подменяется ручным"
        assert worker["pid"] is not None
        assert worker["started_at"] is not None

    def test_auto_restart_path_also_counts(self) -> None:
        """Ревью Fable, находка 1: авто-рестарт монитора приходит В PM той же
        командой ``process.restart`` (_dispatch_due_restarts) → счётчик обязан
        считать и его. Поэтому поле называется instance_restarts, а не
        manual_restarts: «ручной» было бы ложью про происхождение замены."""
        pm = make_pm({"worker": {"class": "m.W", "priority": "normal"}})
        pm.send_message = MagicMock()
        pm._broadcast_routing_refresh = MagicMock()
        pm._publish_process_identity = MagicMock()
        pm._replay_telemetry_runtime_delta = MagicMock()

        # ровно то, что кладёт монитор в system-очередь PM при авто-рестарте
        res = pm._cmd_process_restart(data={"process_name": "worker"})
        assert res["success"] is True
        assert pm._instance_restarts["worker"] == 1


class TestCleanupRemovesTails:
    def test_cleanup_drops_instance_tails(self) -> None:
        """Ревью Fable, находка 2: снятый switch'ем процесс не должен вечно
        висеть в supervision-снимке, а новый одноимённый — наследовать чужой
        счётчик замен (тот же контракт, что у monitor.forget_process)."""
        pm = make_pm({"cam": {"class": "m.C", "priority": "normal"}})
        pm.send_message = MagicMock()
        pm._broadcast_routing_refresh = MagicMock()
        pm._publish_process_identity = MagicMock()
        pm._replay_telemetry_runtime_delta = MagicMock()
        pm._delete_process_state = MagicMock()
        _pm_snapshot_ready(pm, {})

        assert pm.restart_process("cam") is True
        assert pm._instance_restarts["cam"] == 1

        pm._cleanup_process_resources("cam")
        assert "cam" not in pm._instance_restarts
        assert "cam" not in pm._instance_started_at
        # …и процесс-призрак исчез из снимка
        assert pm._cmd_supervision_status()["processes"] == {}

    def test_incarnation_survives_cleanup(self) -> None:
        """Контраст: fence-плоскость чистить НЕЛЬЗЯ — монотонность incarnation
        защищает соседей от стейл-ссылок на снятое имя."""
        pm = make_pm({"cam": {"class": "m.C"}})
        pm._delete_process_state = MagicMock()
        pm._ensure_routing_state()
        pm._bump_incarnation("cam")
        inc = pm._incarnations.get("cam")

        pm._cleanup_process_resources("cam")
        assert pm._incarnations.get("cam") == inc


class TestStartPathsMarkInstance:
    def test_start_process_marks_started_at(self) -> None:
        pm = make_pm({"worker": {"class": "m.W"}})
        pm._process_registry._processes["worker"] = MockProcess("worker", alive=False)
        assert pm.start_process("worker") is True
        assert pm._instance_started_at["worker"] > 0

    def test_bulk_start_does_not_touch_already_alive(self) -> None:
        """Ревью Fable, находка 3: bulk-старт метит только реально стартовавших.
        Иначе у живого процесса started_at «омолаживался» бы при том же pid —
        маркер врал бы ровно в ту сторону, против которой задача."""
        pm = make_pm({})
        pm._publish_process_identity = MagicMock()
        registry = pm._process_registry
        registry._processes["alive"] = MockProcess("alive", alive=True)
        registry._processes["dead"] = MockProcess("dead", alive=False)
        # паритет реального ProcessRegistry.start_all: живых пропускает
        registry.start_all = lambda: [p.start() for p in registry.os_processes if not p.is_alive()]

        assert pm.start_process() is True
        assert "dead" in pm._instance_started_at
        assert "alive" not in pm._instance_started_at
