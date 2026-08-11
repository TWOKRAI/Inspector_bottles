# -*- coding: utf-8 -*-
"""Задача 3.3: последний рубеж выбора каталога логов — не строка ``"logs"``.

``ProcessLaunchConfig._resolve_log_dir`` — третья и последняя точка, где выбирался
каталог. Порядок «свой конфиг → env → дефолт» правильный; неверен был сам дефолт:
относительная ``"logs"`` резолвится от ``cwd`` запускающего, то есть при запуске из
корня репозитория логи ложились в репозиторий.
"""

from __future__ import annotations

from pathlib import Path

from multiprocess_framework.modules.process_module.configs.process_launch_config import (
    ProcessLaunchConfig,
)

#: Корень репозитория: файл — modules/process_module/tests/<файл>.
_REPO_ROOT = Path(__file__).resolve().parents[4]


def _config(**kwargs) -> ProcessLaunchConfig:
    return ProcessLaunchConfig(process_name="ticker", process_class="pkg.Ticker", **kwargs)


class TestPriorityOrder:
    def test_own_config_wins_over_env(self, tmp_path, monkeypatch) -> None:
        """Явный каталог сильнее env. Пара к следующему тесту — иначе он мерил бы приоритет."""
        monkeypatch.setenv("MULTIPROCESS_LOG_DIR", str(tmp_path / "from_env"))

        assert _config(log_dir=str(tmp_path / "from_config"))._resolve_log_dir() == str(tmp_path / "from_config")

    def test_env_wins_over_the_last_resort(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setenv("MULTIPROCESS_LOG_DIR", str(tmp_path / "from_env"))
        # Соседнюю ручку чистим ЯВНО: иначе тест мерил бы приоритет пары, а не действие
        # выставленной переменной.
        monkeypatch.delenv("INSPECTOR_LOG_DIR", raising=False)

        assert _config()._resolve_log_dir() == str(tmp_path / "from_env")

    def test_legacy_env_key_still_acts_when_the_canonical_one_is_silent(self, tmp_path, monkeypatch) -> None:
        monkeypatch.delenv("MULTIPROCESS_LOG_DIR", raising=False)
        monkeypatch.setenv("INSPECTOR_LOG_DIR", str(tmp_path / "legacy"))

        assert _config()._resolve_log_dir() == str(tmp_path / "legacy")


class TestLastResortIsOutsideTheRepository:
    def test_silence_everywhere_does_not_point_into_the_repo(self, monkeypatch) -> None:
        """Свойство задачи 3.3: не задал никто — пишем ВНЕ дерева репозитория."""
        monkeypatch.delenv("MULTIPROCESS_LOG_DIR", raising=False)
        monkeypatch.delenv("INSPECTOR_LOG_DIR", raising=False)

        resolved = Path(_config()._resolve_log_dir())

        assert resolved.is_absolute(), f"относительный последний рубеж резолвится от cwd: {resolved}"
        assert _REPO_ROOT not in resolved.parents and resolved != _REPO_ROOT, (
            f"последний рубеж указывает в репозиторий: {resolved}"
        )

    def test_the_relative_literal_is_gone_from_the_source(self) -> None:
        """Рецидив приёма ловится по тексту: конструкция вернётся быстрее, чем логика."""
        module_file = Path(__file__).resolve().parents[1] / "configs" / "process_launch_config.py"
        text = module_file.read_text(encoding="utf-8")
        code = "\n".join(line for line in text.splitlines() if "``" not in line)

        assert 'or "logs"' not in code
