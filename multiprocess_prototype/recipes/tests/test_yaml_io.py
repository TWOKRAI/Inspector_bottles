# -*- coding: utf-8 -*-
"""Shim-parity: `recipes.yaml_io` реэкспортирует generic-writer модуля `recipe`.

Полное покрытие поведения — в home-тесте модуля
(`multiprocess_framework/modules/recipe/tests/test_yaml_io.py`, C3/ADR-RCP-005).
Здесь — гарантия, что старый путь импорта `multiprocess_prototype.recipes.yaml_io`
жив и указывает на те же объекты (шим не разъехался с фреймворком).
"""

from __future__ import annotations

from multiprocess_framework.modules.recipe import yaml_io as fw_yaml_io
from multiprocess_prototype.recipes import yaml_io as proto_yaml_io


def test_shim_reexports_same_update_yaml_preserving():
    assert proto_yaml_io.update_yaml_preserving is fw_yaml_io.update_yaml_preserving


def test_shim_reexports_same_metadata_writer():
    assert proto_yaml_io.update_blueprint_metadata_preserving is fw_yaml_io.update_blueprint_metadata_preserving
