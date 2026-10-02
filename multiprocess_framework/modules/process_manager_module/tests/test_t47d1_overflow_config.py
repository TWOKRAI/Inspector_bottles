# -*- coding: utf-8 -*-
"""Task 4.7d-1 — слепые приёмочные тесты ключа рецепта ``overflow`` (``latest | every``).

Источник: plans/transport-single-policy/task-4.7.md, acceptance 4.7d-1 (пункты про
``as_generic_config`` и ``GenericProcessConfig.build``). Типизированного поля
``ProcessConfig.overflow`` нет — ключ живёт только в ``extras``.

``pydantic.ValidationError`` — подкласс ``ValueError``, поэтому тест текста ошибки
требует имя процесса: pydantic-``Literal`` сам его не несёт.
"""

from __future__ import annotations

import pytest

from ..topology.blueprint import ProcessConfig
from ...process_module.generic.generic_process_config import GenericProcessConfig


def test_extras_every_reaches_generic_config():
    gc = ProcessConfig(process_name="p", extras={"overflow": "every"}).as_generic_config()
    assert gc.overflow == "every"


def test_missing_key_defaults_to_latest():
    gc = ProcessConfig(process_name="p").as_generic_config()
    assert gc.overflow == "latest"


def test_extras_explicit_latest_stays_latest():
    gc = ProcessConfig(process_name="p", extras={"overflow": "latest"}).as_generic_config()
    assert gc.overflow == "latest"


def _bad_value_error() -> ValueError:
    with pytest.raises(ValueError) as exc:
        ProcessConfig(process_name="proc_x", extras={"overflow": "sometimes"}).as_generic_config()
    return exc.value


@pytest.mark.parametrize("needle", ["proc_x", "overflow", "'sometimes'"])
def test_bad_overflow_value_error_text_contains(needle):
    assert needle in str(_bad_value_error())


def test_build_puts_overflow_every_into_proc_dict_config():
    _, proc_dict = GenericProcessConfig(process_name="p", overflow="every").build()
    assert proc_dict["config"].get("overflow") == "every"


def test_build_omits_overflow_key_under_default_latest():
    _, proc_dict = GenericProcessConfig(process_name="p").build()
    # якорь: config собран (есть другие ключи/сам dict), ключа overflow нет
    assert isinstance(proc_dict["config"], dict)
    assert "overflow" not in proc_dict["config"]


def test_build_omits_overflow_key_under_explicit_latest():
    gc = GenericProcessConfig(process_name="p", overflow="latest")
    assert gc.overflow == "latest"
    _, proc_dict = gc.build()
    assert "overflow" not in proc_dict["config"]
