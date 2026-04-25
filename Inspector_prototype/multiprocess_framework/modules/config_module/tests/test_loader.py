"""
Unit-тесты для config_module.tools.loader — ConfigLoader.
"""
import json
import os
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from multiprocess_framework.modules.config_module.tools.loader import ConfigLoader
from multiprocess_framework.modules.config_module.core.config import Config


# ---------------------------------------------------------------------------
# build_dict — слои и merge
# ---------------------------------------------------------------------------

def test_empty_loader():
    result = ConfigLoader().build_dict()
    assert result == {}


def test_defaults_only():
    result = ConfigLoader().defaults({"a": 1}).build_dict()
    assert result == {"a": 1}


def test_from_dict():
    result = ConfigLoader().from_dict({"a": 1}).build_dict()
    assert result == {"a": 1}


def test_defaults_plus_dict():
    result = (
        ConfigLoader()
        .defaults({"a": 1, "b": 2})
        .from_dict({"b": 3, "c": 4})
        .build_dict()
    )
    assert result == {"a": 1, "b": 3, "c": 4}


def test_multiple_dicts_priority():
    result = (
        ConfigLoader()
        .from_dict({"port": 5432})
        .from_dict({"port": 3306})
        .build_dict()
    )
    assert result == {"port": 3306}


def test_nested_merge():
    result = (
        ConfigLoader()
        .defaults({"db": {"host": "localhost", "port": 5432}})
        .from_dict({"db": {"port": 3306}})
        .build_dict()
    )
    assert result == {"db": {"host": "localhost", "port": 3306}}


# ---------------------------------------------------------------------------
# build — возвращает Config
# ---------------------------------------------------------------------------

def test_build_returns_config():
    cfg = ConfigLoader().from_dict({"key": "value"}).build()
    assert isinstance(cfg, Config)
    assert cfg.get("key") == "value"


def test_build_with_env_prefix():
    cfg = (
        ConfigLoader()
        .from_dict({"key": "value"})
        .from_env(prefix="MYAPP")
        .build()
    )
    assert isinstance(cfg, Config)
    # env_prefix передан в Config — проверяем через _env_prefix
    assert cfg._env_prefix == "MYAPP"


# ---------------------------------------------------------------------------
# from_file
# ---------------------------------------------------------------------------

def test_from_file_json(tmp_path):
    config_file = tmp_path / "config.json"
    config_file.write_text(json.dumps({"db": {"host": "prod-server"}}))

    result = (
        ConfigLoader()
        .defaults({"db": {"host": "localhost", "port": 5432}})
        .from_file(str(config_file))
        .build_dict()
    )
    assert result == {"db": {"host": "prod-server", "port": 5432}}


def test_from_file_not_found_optional():
    """Несуществующий файл при required=False — пропускается."""
    result = (
        ConfigLoader()
        .defaults({"a": 1})
        .from_file("/nonexistent/config.yaml", required=False)
        .build_dict()
    )
    assert result == {"a": 1}


def test_from_file_not_found_required():
    """Несуществующий файл при required=True — ошибка."""
    with pytest.raises(FileNotFoundError):
        ConfigLoader().from_file("/nonexistent/config.yaml", required=True)


# ---------------------------------------------------------------------------
# from_env_dict
# ---------------------------------------------------------------------------

def test_from_env_dict():
    with patch.dict(os.environ, {"MYAPP_DB_HOST": "env-host"}):
        result = (
            ConfigLoader()
            .defaults({"db_host": "localhost"})
            .from_env_dict("MYAPP", ["db_host"])
            .build_dict()
        )
    assert result == {"db_host": "env-host"}


def test_from_env_dict_missing_keys():
    """Отсутствующие env-переменные не добавляются."""
    result = (
        ConfigLoader()
        .defaults({"a": 1})
        .from_env_dict("MYAPP", ["nonexistent_key"])
        .build_dict()
    )
    assert result == {"a": 1}


# ---------------------------------------------------------------------------
# validate
# ---------------------------------------------------------------------------

def test_validate_success():
    """Валидация проходит — build_dict возвращает данные."""
    from pydantic import BaseModel

    class TestSchema(BaseModel):
        host: str
        port: int

    result = (
        ConfigLoader()
        .from_dict({"host": "localhost", "port": 5432})
        .validate(TestSchema)
        .build_dict()
    )
    assert result == {"host": "localhost", "port": 5432}


def test_validate_failure():
    """Невалидные данные — ValidationError."""
    from pydantic import BaseModel, ValidationError

    class TestSchema(BaseModel):
        host: str
        port: int

    with pytest.raises(ValidationError):
        ConfigLoader().from_dict({"host": "localhost"}).validate(TestSchema).build_dict()


# ---------------------------------------------------------------------------
# Chaining / fluent API
# ---------------------------------------------------------------------------

def test_full_pipeline(tmp_path):
    """Полный pipeline: defaults → file → dict → env → validate → build."""
    config_file = tmp_path / "app.json"
    config_file.write_text(json.dumps({"db": {"port": 3306}}))

    cfg = (
        ConfigLoader()
        .defaults({"db": {"host": "localhost", "port": 5432}, "debug": False})
        .from_file(str(config_file))
        .from_dict({"debug": True})
        .from_env(prefix="APP")
        .build()
    )

    assert isinstance(cfg, Config)
    assert cfg.get("db.host") == "localhost"  # из defaults
    assert cfg.get("db.port") == 3306         # из file (override)
    assert cfg.get("debug") is True           # из dict (override)
