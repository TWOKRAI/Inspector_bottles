"""
Unit-тесты для класса ConfigSection.
"""
import pytest

from multiprocess_framework.modules.config_module.core.config import Config
from multiprocess_framework.modules.config_module.sections.config_section import ConfigSection


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def cfg_and_sec():
    cfg = Config()
    sec = ConfigSection(cfg, "database")
    return cfg, sec


# ---------------------------------------------------------------------------
# get / set
# ---------------------------------------------------------------------------

def test_set_get(cfg_and_sec):
    cfg, sec = cfg_and_sec
    sec.set("host", "localhost")
    assert sec.get("host") == "localhost"
    assert cfg.get("database.host") == "localhost"


def test_get_default(cfg_and_sec):
    _, sec = cfg_and_sec
    assert sec.get("missing", "default") == "default"


# ---------------------------------------------------------------------------
# update
# ---------------------------------------------------------------------------

def test_update(cfg_and_sec):
    cfg, sec = cfg_and_sec
    sec.update({"host": "localhost", "port": 5432})
    assert sec.get("host") == "localhost"
    assert sec.get("port") == 5432
    assert cfg.get("database.host") == "localhost"
    assert cfg.get("database.port") == 5432


# ---------------------------------------------------------------------------
# has / remove
# ---------------------------------------------------------------------------

def test_has(cfg_and_sec):
    _, sec = cfg_and_sec
    sec.set("host", "localhost")
    assert sec.has("host")
    assert not sec.has("port")


def test_remove(cfg_and_sec):
    cfg, sec = cfg_and_sec
    sec.set("host", "localhost")
    assert sec.remove("host")
    assert not sec.has("host")
    assert not cfg.has("database.host")


def test_remove_nonexistent(cfg_and_sec):
    _, sec = cfg_and_sec
    assert not sec.remove("ghost")


# ---------------------------------------------------------------------------
# data property
# ---------------------------------------------------------------------------

def test_data_property(cfg_and_sec):
    _, sec = cfg_and_sec
    sec.update({"host": "localhost", "port": 5432})
    d = sec.data
    assert d["host"] == "localhost"
    assert d["port"] == 5432


def test_data_empty_section(cfg_and_sec):
    _, sec = cfg_and_sec
    assert sec.data == {}


# ---------------------------------------------------------------------------
# dict-syntax
# ---------------------------------------------------------------------------

def test_dict_syntax_get_set(cfg_and_sec):
    _, sec = cfg_and_sec
    sec["host"] = "localhost"
    assert sec["host"] == "localhost"
    assert "host" in sec


def test_dict_syntax_del(cfg_and_sec):
    _, sec = cfg_and_sec
    sec["host"] = "localhost"
    del sec["host"]
    assert "host" not in sec


def test_dict_syntax_del_missing_raises(cfg_and_sec):
    _, sec = cfg_and_sec
    with pytest.raises(KeyError):
        del sec["missing"]
