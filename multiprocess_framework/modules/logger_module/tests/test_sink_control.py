# -*- coding: utf-8 -*-
"""Тесты Ф1 Task 1.4 (серверная часть): LoggerManager.set_sink_enabled.

Якорь ADR-CRM-006 п.3 (logger.sink.enable|disable → register_channel/unregister_channel):
точечная (де)регистрация sink'а по имени без пересборки всего конфига.
"""

from __future__ import annotations

from multiprocess_framework.modules.logger_module.core.logger_manager import LoggerManager


class TestSetSinkEnabled:
    def test_disable_removes_sink_from_registry(self) -> None:
        mgr = LoggerManager(manager_name="TapTest")
        mgr.initialize()
        assert mgr._channel_registry.get("system_file") is not None

        assert mgr.set_sink_enabled("system_file", False) is True
        assert mgr._channel_registry.get("system_file") is None

    def test_enable_recreates_sink_from_config(self) -> None:
        mgr = LoggerManager(manager_name="TapTest")
        mgr.initialize()
        mgr.set_sink_enabled("system_file", False)
        assert mgr._channel_registry.get("system_file") is None

        assert mgr.set_sink_enabled("system_file", True) is True
        assert mgr._channel_registry.get("system_file") is not None

    def test_enable_unknown_sink_returns_false(self) -> None:
        mgr = LoggerManager(manager_name="TapTest")
        mgr.initialize()
        assert mgr.set_sink_enabled("__nope__", True) is False

    def test_disable_unknown_sink_returns_false(self) -> None:
        mgr = LoggerManager(manager_name="TapTest")
        mgr.initialize()
        assert mgr.set_sink_enabled("__nope__", False) is False


class TestModuleSinkRoundTrip:
    """Живые находки 2026-07-28: ручка была ОДНОСТОРОННЕЙ и врала счётчиком потерь.

    Обе найдены прогоном на прототипе (`camera_0`, рецепт webcam_sketch), обе
    воспроизведены на стенде и закреплены здесь по НАБЛЮДАЕМОМУ эффекту —
    состоянию реестра и счётчику потерь, а не по именам вызванных методов.
    """

    @staticmethod
    def _manager(tmp_path):
        from multiprocess_framework.modules.logger_module.configs import (
            LoggerManagerConfig,
            LoggerModuleSchema,
        )

        return LoggerManager(
            config=LoggerManagerConfig(
                app_name="module_sink",
                log_directory=str(tmp_path),
                enable_batching=False,
                modules={"trace": LoggerModuleSchema(enabled=True, file_path="trace.log")},
            )
        )

    def test_module_sink_can_be_switched_back_on(self, tmp_path) -> None:
        """Снял — верни. До правки `enable` отвечал False и канал не возвращался.

        Причина была не в отсутствии параметров (докстринг утверждал именно это),
        а в том, что искали их в `config.channels`, тогда как module-каналы
        описаны в `config.modules`. Косвенное доказательство было уже вживую:
        `config.reload` канал ВОССТАНАВЛИВАЛ, доставая параметры оттуда же.
        """
        mgr = self._manager(tmp_path)
        try:
            assert mgr._channel_registry.get("module_trace") is not None
            assert mgr.set_sink_enabled("module_trace", False) is True
            assert mgr._channel_registry.get("module_trace") is None

            assert mgr.set_sink_enabled("module_trace", True) is True
            assert mgr._channel_registry.get("module_trace") is not None
        finally:
            mgr.shutdown()

    def test_module_sink_writes_again_after_round_trip(self, tmp_path) -> None:
        """Возвращённый канал не просто числится в реестре, а ПИШЕТ.

        Отдельно от предыдущего: реестр мог бы получить закрытый объект, и
        проверка «is not None» осталась бы зелёной при мёртвом канале.
        """
        mgr = self._manager(tmp_path)
        try:
            mgr.set_sink_enabled("module_trace", False)
            mgr.set_sink_enabled("module_trace", True)
            mgr.info("после возврата", module="trace")
            mgr.flush()
        finally:
            mgr.shutdown()

        assert "после возврата" in (tmp_path / "trace.log").read_text(encoding="utf-8")

    def test_disabling_module_sink_is_not_counted_as_a_loss(self, tmp_path) -> None:
        """Штатное «выключи мне этот лог» НЕ должно выглядеть как потеря записей.

        Воспроизведение до правки: generic-путь `set_sink_enabled(False)` снимал
        канал только с реестра, а `_resolve_channel` продолжал доставать его из
        `_module_channels` — записи модуля уходили в УЖЕ ЗАКРЫТЫЙ канал и
        считались `channel_refused_records` (5 записей → 5 отказов). 2.V2 подняла
        бы по ним аномалию `observability_loss` на ровном месте.
        """
        mgr = self._manager(tmp_path)
        try:
            mgr.set_sink_enabled("module_trace", False)
            for i in range(5):
                mgr.info(f"запись {i}", module="trace")
            stats = mgr.get_stats()
        finally:
            mgr.shutdown()

        assert stats["channel_refused_records"] == 0, stats.get("channel_refused_by_channel")
        assert stats["unresolved_channel_records"] == 0, stats.get("unresolved_channels")
        assert stats["records_without_channels"] == 0

    def test_runtime_only_module_sink_stays_unrecoverable(self, tmp_path) -> None:
        """Предел, который остаётся пределом — и назван честно.

        Канал, поднятый `enable_module_logging` и НЕ описанный в конфиге, вернуть
        действительно неоткуда: параметров нет. Тест нужен, чтобы правка выше не
        читалась как «теперь возвращается всё».
        """
        mgr = self._manager(tmp_path)
        try:
            mgr.enable_module_logging("рантайм", file_path="runtime.log")
            assert mgr.set_sink_enabled("module_рантайм", False) is True
            assert mgr.set_sink_enabled("module_рантайм", True) is False
        finally:
            mgr.shutdown()
