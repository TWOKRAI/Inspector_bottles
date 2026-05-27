# -*- coding: utf-8 -*-
"""
adapters/tests/test_config_store.py — тесты ConfigStoreFromManager adapter'а (Task D.2b).

Тестирует:
  1. Protocol satisfaction (isinstance с @runtime_checkable)
  2. get/set roundtrip (dot-notation ключи)
  3. get_section — возвращает плоский Mapping без секционного префикса
  4. list_keys с prefix-фильтрацией
  5. subscribe fires on matching key change (glob-паттерн)
  6. subscribe NOT fires on non-matching key
  7. unsubscribe stops callbacks
  8. save с save_callback (проверка вызова)
  9. save без callback — no-op (не падает)
 10. get на несуществующий ключ возвращает default
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from multiprocess_framework.modules.config_module.core.config import Config
from multiprocess_prototype.adapters.stores.config_store import ConfigStoreFromManager
from multiprocess_prototype.domain.protocols.config_store import ConfigStore


# ==============================================================================
# Вспомогательные фикстуры
# ==============================================================================


@pytest.fixture()
def config() -> Config:
    """Пустой Config из config_module."""
    return Config()


@pytest.fixture()
def adapter(config: Config) -> ConfigStoreFromManager:
    """ConfigStoreFromManager без save_callback."""
    return ConfigStoreFromManager(backend=config)


# ==============================================================================
# test_config_store_satisfies_protocol
# ==============================================================================


def test_config_store_satisfies_protocol(adapter: ConfigStoreFromManager) -> None:
    """ConfigStoreFromManager satisfies ConfigStore Protocol (@runtime_checkable)."""
    c: ConfigStore = adapter
    assert isinstance(c, ConfigStore)


# ==============================================================================
# test_get_set_roundtrip
# ==============================================================================


def test_get_set_roundtrip(adapter: ConfigStoreFromManager) -> None:
    """set() + get() возвращают то же значение."""
    adapter.set("display.theme", "dark")
    assert adapter.get("display.theme") == "dark"


def test_get_returns_default_for_missing_key(adapter: ConfigStoreFromManager) -> None:
    """get() на несуществующий ключ возвращает переданный default."""
    assert adapter.get("nonexistent.key") is None
    assert adapter.get("nonexistent.key", "fallback") == "fallback"
    assert adapter.get("nonexistent.key", 42) == 42


# ==============================================================================
# test_get_section_returns_mapping
# ==============================================================================


def test_get_section_returns_mapping(adapter: ConfigStoreFromManager) -> None:
    """get_section("display") для display.theme + display.dpi → {"theme": ..., "dpi": ...}."""
    adapter.set("display.theme", "dark")
    adapter.set("display.dpi", 96)
    adapter.set("network.host", "localhost")

    section = adapter.get_section("display")

    assert dict(section) == {"theme": "dark", "dpi": 96}


def test_get_section_returns_empty_for_missing_section(
    adapter: ConfigStoreFromManager,
) -> None:
    """get_section() для отсутствующей секции → пустой Mapping."""
    adapter.set("display.theme", "dark")
    section = adapter.get_section("network")
    assert dict(section) == {}


def test_get_section_nested_keys(adapter: ConfigStoreFromManager) -> None:
    """get_section() работает с вложенными ключами (a.b.c → секция a, подключ b.c)."""
    adapter.set("display.font.size", 14)
    adapter.set("display.font.family", "Arial")
    adapter.set("display.theme", "light")

    section = adapter.get_section("display")

    # Ключ display.font.size → sub_key = font.size
    assert section.get("font.size") == 14
    assert section.get("font.family") == "Arial"
    assert section.get("theme") == "light"


# ==============================================================================
# test_list_keys_with_prefix
# ==============================================================================


def test_list_keys_with_prefix(adapter: ConfigStoreFromManager) -> None:
    """list_keys("display.") возвращает только ключи с prefix."""
    adapter.set("display.theme", "dark")
    adapter.set("display.dpi", 96)
    adapter.set("network.host", "localhost")

    keys = adapter.list_keys("display.")

    assert set(keys) == {"display.theme", "display.dpi"}


def test_list_keys_empty_prefix_returns_all(adapter: ConfigStoreFromManager) -> None:
    """list_keys("") возвращает все ключи."""
    adapter.set("display.theme", "dark")
    adapter.set("network.host", "localhost")

    keys = adapter.list_keys()

    assert "display.theme" in keys
    assert "network.host" in keys


def test_list_keys_no_match_returns_empty(adapter: ConfigStoreFromManager) -> None:
    """list_keys() с неизвестным prefix → пустая последовательность."""
    adapter.set("display.theme", "dark")
    keys = adapter.list_keys("nonexistent.")
    assert len(list(keys)) == 0


# ==============================================================================
# test_subscribe_fires_on_matching_change
# ==============================================================================


def test_subscribe_fires_on_matching_change(adapter: ConfigStoreFromManager) -> None:
    """subscribe("display.*", handler) → handler вызван при set("display.theme", ...)."""
    calls: list[tuple[str, Any]] = []

    def handler(key: str, value: Any) -> None:
        calls.append((key, value))

    adapter.subscribe("display.*", handler)
    adapter.set("display.theme", "dark")

    assert len(calls) == 1
    assert calls[0] == ("display.theme", "dark")


def test_subscribe_fires_multiple_times(adapter: ConfigStoreFromManager) -> None:
    """Handler вызывается при каждом set()."""
    calls: list[Any] = []
    adapter.subscribe("x.*", lambda k, v: calls.append(v))
    adapter.set("x.a", 1)
    adapter.set("x.b", 2)
    assert calls == [1, 2]


# ==============================================================================
# test_subscribe_not_fires_on_non_matching
# ==============================================================================


def test_subscribe_not_fires_on_non_matching(adapter: ConfigStoreFromManager) -> None:
    """subscribe("display.*", handler) → handler НЕ вызван при set("network.host", ...)."""
    calls: list[tuple[str, Any]] = []

    def handler(key: str, value: Any) -> None:
        calls.append((key, value))

    adapter.subscribe("display.*", handler)
    adapter.set("network.host", "localhost")

    assert len(calls) == 0


# ==============================================================================
# test_unsubscribe_stops_callbacks
# ==============================================================================


def test_unsubscribe_stops_callbacks(adapter: ConfigStoreFromManager) -> None:
    """После subscription.unsubscribe() handler больше не вызывается."""
    calls: list[Any] = []
    subscription = adapter.subscribe("display.*", lambda k, v: calls.append(v))

    adapter.set("display.theme", "dark")
    assert len(calls) == 1

    subscription.unsubscribe()
    adapter.set("display.theme", "light")

    # Handler не должен был вызваться после unsubscribe
    assert len(calls) == 1


def test_unsubscribe_idempotent(adapter: ConfigStoreFromManager) -> None:
    """Повторный unsubscribe() не падает."""
    subscription = adapter.subscribe("x.*", lambda k, v: None)
    subscription.unsubscribe()
    subscription.unsubscribe()  # no-op — не должно бросать исключение


def test_subscription_context_manager(adapter: ConfigStoreFromManager) -> None:
    """Использование subscription как context manager — auto-unsubscribe при выходе."""
    calls: list[Any] = []
    with adapter.subscribe("display.*", lambda k, v: calls.append(v)):
        adapter.set("display.theme", "dark")
        assert len(calls) == 1

    # После выхода из with — unsubscribed
    adapter.set("display.theme", "light")
    assert len(calls) == 1


# ==============================================================================
# test_save_with_callback
# ==============================================================================


def test_save_calls_save_callback() -> None:
    """save() вызывает save_callback если он передан."""
    mock_save = MagicMock()
    cfg = Config(initial_data={"display": {"theme": "dark"}})
    adapter = ConfigStoreFromManager(backend=cfg, save_callback=mock_save)

    adapter.set("display.theme", "light")
    adapter.save()

    mock_save.assert_called_once()


def test_save_without_callback_does_not_raise(adapter: ConfigStoreFromManager) -> None:
    """save() без save_callback не бросает исключение (no-op + warning)."""
    adapter.set("x", 1)
    adapter.save()  # не должно падать


# ==============================================================================
# test_save_persists_to_disk (через ConfigManager + файл)
# ==============================================================================


def test_save_persists_via_callback(tmp_path: Any) -> None:
    """save_callback вызывается → данные можно сохранить и перечитать.

    Создаём два adapter'а на разных Config-объектах, эмулируем сохранение
    через save_callback который копирует данные во внешний dict,
    затем создаём второй adapter из этих данных и проверяем значение.
    """
    saved_data: dict[str, Any] = {}

    cfg = Config()
    adapter1 = ConfigStoreFromManager(
        backend=cfg,
        save_callback=lambda: saved_data.update(cfg.data),
    )

    adapter1.set("display.theme", "dark")
    adapter1.save()

    # Создаём второй adapter из сохранённых данных
    cfg2 = Config(initial_data=saved_data)
    adapter2 = ConfigStoreFromManager(backend=cfg2)

    # Проверяем что значение сохранилось
    assert adapter2.get("display.theme") == "dark"
