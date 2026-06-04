# -*- coding: utf-8 -*-
"""Тесты ProcessTreeGuard — OS-уровневая гарантия гибели дерева процессов.

OS-примитивы (Job Object / killpg) не дёргаем по-настоящему: проверяем выбор
ветки, безопасность POSIX-группы и portable psutil-fallback (мокаем).
"""

from unittest.mock import MagicMock, patch

from ..launcher import process_tree_guard as ptg
from ..launcher.process_tree_guard import ProcessTreeGuard


class TestPlatformChoice:
    def test_wants_new_session_matches_platform(self) -> None:
        """POSIX → нужна новая сессия (setsid); Windows → нет (держит Job Object)."""
        g = ProcessTreeGuard()
        assert g.wants_new_session() == (not g._is_windows)

    def test_adopt_records_pm_pid(self) -> None:
        g = ProcessTreeGuard()
        g._is_windows = False  # POSIX-ветка adopt: только запомнить pid
        g.adopt(4321)
        assert g._pm_pid == 4321


class TestKillTreeRouting:
    def test_falls_back_to_psutil_when_no_primitive(self) -> None:
        """Нет job (Win) / нет pm_pid (POSIX) → portable psutil-fallback."""
        g = ProcessTreeGuard()
        g._job = None
        g._pm_pid = None
        g._kill_via_psutil = MagicMock()

        g.kill_tree(["snapshot"])

        g._kill_via_psutil.assert_called_once_with(["snapshot"])

    def test_windows_job_terminate_skips_fallback(self) -> None:
        """Если TerminateJobObject сработал — psutil-fallback не зовём."""
        g = ProcessTreeGuard()
        g._is_windows = True
        g._terminate_windows_job = MagicMock(return_value=True)
        g._kill_via_psutil = MagicMock()

        g.kill_tree()

        g._kill_via_psutil.assert_not_called()


class TestPosixGroup:
    def test_killpg_targets_pm_group(self) -> None:
        """POSIX: killpg по группе оркестратора (его pgid), launcher не трогаем."""
        g = ProcessTreeGuard()
        g._is_windows = False
        g._pm_pid = 999
        mock_os = MagicMock()
        mock_os.getpgid.return_value = 999  # группа PM
        mock_os.getpgrp.return_value = 111  # группа launcher (другая)
        with patch.object(ptg, "os", mock_os), patch("time.sleep"):
            result = g._terminate_posix_group()
        assert result is True
        # SIGTERM по группе PM (999), не по группе launcher.
        assert mock_os.killpg.call_args_list[0].args[0] == 999

    def test_killpg_skips_when_same_group_as_launcher(self) -> None:
        """Защита: setsid не сработал (группа PM == группа launcher) → не killpg себя."""
        g = ProcessTreeGuard()
        g._is_windows = False
        g._pm_pid = 999
        mock_os = MagicMock()
        mock_os.getpgid.return_value = 111
        mock_os.getpgrp.return_value = 111  # та же группа → опасно
        with patch.object(ptg, "os", mock_os):
            result = g._terminate_posix_group()
        assert result is False
        mock_os.killpg.assert_not_called()


class TestPsutilFallback:
    def test_terminates_pre_kill_snapshot(self) -> None:
        """Процессы из снимка terminate'ятся даже при оборванной PPID-цепочке."""
        g = ProcessTreeGuard()
        fake_current = MagicMock(pid=1)
        fake_current.children.return_value = []  # обход по живым PPID пуст
        worker = MagicMock(pid=42)
        with (
            patch("psutil.Process", return_value=fake_current),
            patch("psutil.wait_procs", return_value=([], [])),
        ):
            g._kill_via_psutil([worker])
        worker.terminate.assert_called_once()

    def test_dedups_by_pid(self) -> None:
        """Один PID в снимке и в обходе → terminate один раз."""
        g = ProcessTreeGuard()
        worker = MagicMock(pid=42)
        fake_current = MagicMock(pid=1)
        fake_current.children.return_value = [worker]
        with (
            patch("psutil.Process", return_value=fake_current),
            patch("psutil.wait_procs", return_value=([], [])),
        ):
            g._kill_via_psutil([worker])
        worker.terminate.assert_called_once()

    def test_excludes_self(self) -> None:
        """Себя (launcher) не трогаем."""
        g = ProcessTreeGuard()
        fake_current = MagicMock(pid=1)
        fake_current.children.return_value = []
        self_proc = MagicMock(pid=1)  # тот же pid, что current → исключить
        with (
            patch("psutil.Process", return_value=fake_current),
            patch("psutil.wait_procs", return_value=([], [])),
        ):
            g._kill_via_psutil([self_proc])
        self_proc.terminate.assert_not_called()
