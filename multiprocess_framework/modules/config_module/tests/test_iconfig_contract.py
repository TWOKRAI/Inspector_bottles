"""Контрактные тесты IConfig и IConfigObserver (k0 1.1).

Purpose: закрепить набор членов IConfig, соответствие Config и протокол наблюдателя.
Public API: нет (только тесты); ``__all__`` пуст.
Stability: lite
"""

import pytest

from multiprocess_framework.modules.config_module.core.config import Config
from multiprocess_framework.modules.config_module.interfaces import IConfig, IConfigObserver

__all__: list[str] = []

_MEMBERS = frozenset({"get", "set", "update", "has", "remove", "clear", "subscribe", "unsubscribe", "data"})


def test_iconfig_abstract_set_is_the_9_literal_names_and_uninstantiable():
    assert IConfig.__abstractmethods__ == _MEMBERS
    assert len(_MEMBERS) == 9
    with pytest.raises(TypeError):
        IConfig()


def test_config_instance_has_every_iconfig_member_and_data_is_a_copy():
    cfg = Config(initial_data={"a": {"b": 1}})
    for name in sorted(_MEMBERS - {"data"}):
        assert callable(getattr(cfg, name, None)), name
    assert cfg.data == {"a": {"b": 1}}
    snapshot = cfg.data
    snapshot["a"]["b"] = 99
    snapshot["x"] = 1
    assert cfg.data == {"a": {"b": 1}}


def test_iconfig_observer_protocol_and_subscribe_passes_key_old_new():
    def observer(key, old_value, new_value):
        return None

    assert isinstance(observer, IConfigObserver)
    assert not isinstance(object(), IConfigObserver)

    cfg = Config()
    by_key, by_default = [], []
    cfg.subscribe(lambda k, o, n: by_key.append((k, o, n)), key="k")
    cfg.subscribe(lambda k, o, n: by_default.append((k, o, n)))
    cfg.set("k", 1)
    cfg.set("k", 2)
    assert by_key[-1] == ("k", 1, 2)
    assert by_default[-1] == ("k", 1, 2)
