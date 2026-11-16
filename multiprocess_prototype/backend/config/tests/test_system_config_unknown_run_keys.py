# -*- coding: utf-8 -*-
"""M2 сквозного обзора (run-state 2.7): опечатка в плоском ключе работы ``run_*`` не молчит.

Правило (одно место — ``SystemConfig``, валидатор до полей): неизвестный ключ с префиксом ``run_`` -> одна WARNING
«неизвестный ключ <имя> (возможно <ближайшее из RUN_CONFIG_KEYS>)», значение в конфиг не попадает, блокирующего
отказа нет. Ключи без префикса ``run_`` — как раньше (молча отбрасываются схемой). Ожидаемые тексты — литералы.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from multiprocess_prototype.backend.config import schemas
from multiprocess_prototype.backend.config.schemas import load_system_config

_PREFIX = "неизвестный ключ"


@pytest.fixture
def warnings(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Логгер схем подменён записывающим двойником: тексты WARNING — первые позиционные аргументы."""
    double = MagicMock()
    monkeypatch.setattr(schemas, "logger", double)
    return double


def _texts(double: MagicMock) -> list[str]:
    return [str(c.args[0]) for c in double.warning.call_args_list if c.args and str(c.args[0]).startswith(_PREFIX)]


def _load(tmp_path: Path, text: str, *, overrides: str | None = None) -> schemas.SystemConfig:
    """``system.yaml`` в своём (пустом) каталоге; ``overrides`` — ``user_overrides.yaml`` рядом."""
    path = tmp_path / "system.yaml"
    path.write_text(text, encoding="utf-8")
    if overrides is not None:
        (tmp_path / "user_overrides.yaml").write_text(overrides, encoding="utf-8")
    return load_system_config(path)


def test_typo_warns_once_and_value_is_ignored(tmp_path: Path, warnings: MagicMock) -> None:
    cfg = _load(tmp_path, "run_gate: true\nrun_autostrat: true\n")

    assert _texts(warnings) == ["неизвестный ключ run_autostrat (возможно run_autostart)"]
    assert cfg.run_gate is True
    assert cfg.run_autostart is False
    assert "run_autostrat" not in cfg.model_dump()


def test_typo_in_user_overrides_warns_once(tmp_path: Path, warnings: MagicMock) -> None:
    cfg = _load(tmp_path, "run_gate: true\n", overrides="run_stop_timout_s: 3.0\n")

    assert _texts(warnings) == ["неизвестный ключ run_stop_timout_s (возможно run_stop_timeout_s)"]
    assert cfg.run_stop_timeout_s == 10.0


def test_all_real_run_keys_are_silent(tmp_path: Path, warnings: MagicMock) -> None:
    cfg = _load(
        tmp_path,
        "run_gate: true\nrun_autostart: true\nrun_stop_timeout_s: 5.0\nrun_restart_grace_s: 20.0\n",
    )

    assert _texts(warnings) == []
    assert (cfg.run_gate, cfg.run_autostart, cfg.run_stop_timeout_s, cfg.run_restart_grace_s) == (True, True, 5.0, 20.0)


def test_each_load_warns_once(tmp_path: Path, warnings: MagicMock) -> None:
    _load(tmp_path, "run_autostrat: true\n")
    assert len(_texts(warnings)) == 1

    _load(tmp_path, "run_autostrat: true\n")
    assert _texts(warnings) == ["неизвестный ключ run_autostrat (возможно run_autostart)"] * 2


def test_unknown_key_without_run_prefix_is_silent(tmp_path: Path, warnings: MagicMock) -> None:
    cfg = _load(tmp_path, "autostart: true\nrunner_x: 1\n")

    assert _texts(warnings) == []
    assert "autostart" not in cfg.model_dump()
    assert "runner_x" not in cfg.model_dump()


def test_typo_value_not_in_text(tmp_path: Path, warnings: MagicMock) -> None:
    _load(tmp_path, "run_gat: ZZ-marker-value\n")

    assert _texts(warnings) == ["неизвестный ключ run_gat (возможно run_gate)"]
    assert [t for t in map(str, warnings.mock_calls) if "ZZ-marker-value" in t] == []
