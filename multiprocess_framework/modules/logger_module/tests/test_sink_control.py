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


# =============================================================================
# Ф2.6: класс TestModuleSinkRoundTrip снят вместе с механизмом per-module файлов
# =============================================================================
#
# Он закреплял две живые находки 2026-07-28 (`camera_0`, рецепт webcam_sketch):
# ручка `sink.enable/disable` была ОДНОСТОРОННЕЙ для module-каналов, и снятие
# такого приёмника учитывалось как ПОТЕРЯ записей. Обе беды существовали ровно
# потому, что у module-канала описание жило в секции `modules`, а отметка о
# снятии — в `channels`, и хранилищ каналов было два.
#
# Ни одно из проверявшихся свойств не осталось без сторожа:
#
# * симметрия «снял → вернул» — `TestSetSinkEnabled` выше, на обычных каналах:
#   это и было общее правило, а module-каналы из него выпадали;
# * «канал, не описанный в конфиге, вернуть неоткуда» —
#   `test_enable_unknown_sink_returns_false` там же;
# * «снятие приёмника — не потеря записей» — `test_unknown_channel_accounting.py`
#   (`test_disabling_the_only_sink_is_still_a_loss` и соседи, задача 2.8), где
#   разделены три класса: снят один из двух, снят единственный, опечатка в имени.
#
# То есть свойства исчезли не вместе с проверками, а вместе с ПРИЧИНОЙ: второго
# хранилища каналов и второго написания одного снятия больше нет.
