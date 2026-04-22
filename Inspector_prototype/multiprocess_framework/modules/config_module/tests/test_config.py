"""
Unit-тесты для класса Config.
"""
import os
import pytest

from config_module.core.config import Config


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def cfg() -> Config:
    return Config()


@pytest.fixture
def cfg_with_data() -> Config:
    return Config(initial_data={"database": {"host": "localhost", "port": 5432}})


# ---------------------------------------------------------------------------
# get / set / has / remove / clear
# ---------------------------------------------------------------------------

def test_get_set(cfg):
    cfg.set("key", "value")
    assert cfg.get("key") == "value"


def test_nested_keys(cfg):
    cfg.set("database.host", "localhost")
    cfg.set("database.port", 5432)
    assert cfg.get("database.host") == "localhost"
    assert cfg.get("database.port") == 5432


def test_get_default(cfg):
    assert cfg.get("nonexistent", "default") == "default"


def test_has(cfg):
    cfg.set("key", "value")
    assert cfg.has("key")
    assert not cfg.has("nonexistent")


def test_remove(cfg):
    cfg.set("key", "value")
    assert cfg.remove("key")
    assert not cfg.has("key")


def test_remove_nonexistent(cfg):
    assert not cfg.remove("nonexistent")


def test_clear(cfg):
    cfg.set("k1", "v1")
    cfg.set("k2", "v2")
    cfg.clear()
    assert len(cfg) == 0


# ---------------------------------------------------------------------------
# update
# ---------------------------------------------------------------------------

def test_update_merges(cfg):
    cfg.set("a", 1)
    cfg.update({"b": 2, "a": 99})
    assert cfg.get("a") == 99
    assert cfg.get("b") == 2


def test_update_deep_merge(cfg_with_data):
    cfg_with_data.update({"database": {"name": "testdb"}})
    assert cfg_with_data.get("database.host") == "localhost"
    assert cfg_with_data.get("database.name") == "testdb"


# ---------------------------------------------------------------------------
# subscribe / unsubscribe
# ---------------------------------------------------------------------------

def test_subscribe_wildcard(cfg):
    events = []
    cfg.subscribe(lambda k, o, n: events.append((k, o, n)))
    cfg.set("key", "value")
    assert len(events) == 1
    assert events[0] == ("key", None, "value")


def test_subscribe_specific_key(cfg):
    events = []
    cfg.subscribe(lambda k, o, n: events.append(n), key="x")
    cfg.set("x", 42)
    cfg.set("y", 99)
    assert events == [42]


def test_subscribe_decorator(cfg):
    captured = []

    @cfg.subscribe(key="z")
    def handler(k, o, n):
        captured.append(n)

    cfg.set("z", "hello")
    assert captured == ["hello"]


def test_unsubscribe(cfg):
    events = []
    cb = lambda k, o, n: events.append(n)
    cfg.subscribe(cb)
    cfg.set("a", 1)
    assert cfg.unsubscribe(cb)
    cfg.set("a", 2)
    assert len(events) == 1


# ---------------------------------------------------------------------------
# section
# ---------------------------------------------------------------------------

def test_section_get_set(cfg):
    sec = cfg.section("db")
    sec.set("host", "localhost")
    assert sec.get("host") == "localhost"
    assert cfg.get("db.host") == "localhost"


# ---------------------------------------------------------------------------
# dict-syntax
# ---------------------------------------------------------------------------

def test_dict_syntax(cfg):
    cfg["key"] = "value"
    assert cfg["key"] == "value"
    assert "key" in cfg
    del cfg["key"]
    assert "key" not in cfg


def test_getitem_missing_raises(cfg):
    with pytest.raises(KeyError):
        _ = cfg["missing"]


def test_delitem_missing_raises(cfg):
    with pytest.raises(KeyError):
        del cfg["missing"]


# ---------------------------------------------------------------------------
# env_prefix fallback
# ---------------------------------------------------------------------------

def test_env_fallback(monkeypatch, cfg):
    cfg_env = Config(env_prefix="APP")
    monkeypatch.setenv("APP_DATABASE_HOST", "env_host")
    assert cfg_env.get("database.host") == "env_host"


def test_env_fallback_bool(monkeypatch):
    cfg_env = Config(env_prefix="APP")
    monkeypatch.setenv("APP_DEBUG", "true")
    assert cfg_env.get("debug") is True


def test_env_fallback_int(monkeypatch):
    cfg_env = Config(env_prefix="APP")
    monkeypatch.setenv("APP_PORT", "8080")
    assert cfg_env.get("port") == 8080


# ---------------------------------------------------------------------------
# data property
# ---------------------------------------------------------------------------

def test_data_returns_copy(cfg):
    cfg.set("x", 1)
    d = cfg.data
    d["x"] = 999
    assert cfg.get("x") == 1
