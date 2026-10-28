# -*- coding: utf-8 -*-
"""Ф2.х (Н6) — корень дерева логов: env главнее yaml, и слышат его ВСЕ.

Находка live-прогона ревью Ф2 (2026-08-04): запуск с ``INSPECTOR_LOG_DIR``
раскалывал дерево логов на два корня — PM брал каталог из env
(``managers_from_log_dir``), а дети получали ``system.log_dir`` из yaml через
ассемблер и писали в ``logs/prototype_2``. env-переопределение на то и
переопределение, что действует на всё дерево.

Env снимается ОДИН раз при импорте (``_ENV_LOG_DIR_OVERRIDE``), а не читается
живьём: ``build()`` сам пишет резолвнутый абсолютный путь в ``INSPECTOR_LOG_DIR``
(setdefault для hot-swap и детей), и живое чтение на втором build() того же
процесса принимало СВОЮ ЖЕ запись за волю оператора — поймано красной
характеризацией сборки (снапшот зависел от того, какой build был первым).
"""

from __future__ import annotations

import multiprocess_prototype.backend.launch as launch
from multiprocess_prototype.backend.launch import _env_log_dir_override, resolve_log_dir_root


class TestEnvBeatsYaml:
    def test_env_override_beats_the_yaml_value(self, monkeypatch) -> None:
        """Репро находки: env задан → он корень для ВСЕЙ сборки, не для половины."""
        monkeypatch.setattr(launch, "_ENV_LOG_DIR_OVERRIDE", "logs_review")

        assert resolve_log_dir_root("logs/prototype_2") == "logs_review"

    def test_without_env_the_yaml_value_acts(self, monkeypatch) -> None:
        """Пара: молчащий env ничего не переопределяет."""
        monkeypatch.setattr(launch, "_ENV_LOG_DIR_OVERRIDE", None)

        assert resolve_log_dir_root("logs/prototype_2") == "logs/prototype_2"

    def test_without_both_the_default_is_logs(self, monkeypatch) -> None:
        monkeypatch.setattr(launch, "_ENV_LOG_DIR_OVERRIDE", None)

        assert resolve_log_dir_root(None) == "logs"


class TestOverrideIsSnappedOnceNotReadLive:
    """Живое чтение env на build() — это и был дефект второй редакции правки."""

    def test_multiprocess_key_is_read_first_like_in_log_paths(self) -> None:
        """Порядок ключей — контракт фреймворка (``log_paths``), не свой диалект."""
        env = {"MULTIPROCESS_LOG_DIR": "корень_а", "INSPECTOR_LOG_DIR": "корень_б"}

        assert _env_log_dir_override(env) == "корень_а"

    def test_inspector_key_acts_when_it_is_the_only_one(self) -> None:
        assert _env_log_dir_override({"INSPECTOR_LOG_DIR": "корень_б"}) == "корень_б"

    def test_empty_env_yields_no_override(self) -> None:
        assert _env_log_dir_override({}) is None

    def test_a_builds_own_setdefault_does_not_leak_back_into_resolution(self, monkeypatch) -> None:
        """Репро красной характеризации: запись build()'а в env не меняет резолв.

        Скармливаем функции состояние «env уже содержит абсолютный путь,
        записанный прошлым build()'ом» — снимок при импорте его не видел,
        значит и резолв обязан его не видеть.
        """
        monkeypatch.setattr(launch, "_ENV_LOG_DIR_OVERRIDE", None)
        monkeypatch.setenv("INSPECTOR_LOG_DIR", "d:/абсолютный/след/прошлого/build")

        assert resolve_log_dir_root("logs/prototype_2") == "logs/prototype_2"


class TestBuildPinsExplicitLogDirInEnv:
    """Task 0.2 (gui-graceful-close): явный каталог сборки обязан доходить до env.

    PM и лаунчер берут каталог из ``INSPECTOR_LOG_DIR`` (``resolve_base_log_dir``). При
    ``setdefault`` первый ``build()`` процесса закреплял СВОЙ каталог навсегда: второй прогон
    харнесса с другим ``log_dir`` писал логи PM в каталог первого. Сборка настоящая
    (``build_headless_launcher``), бэкенд не стартует.
    """

    @staticmethod
    def _clean_env(monkeypatch, *, snapshot: "str | None" = None) -> None:
        monkeypatch.delenv("MULTIPROCESS_LOG_DIR", raising=False)
        monkeypatch.delenv("INSPECTOR_LOG_DIR", raising=False)
        monkeypatch.setattr(launch, "_ENV_LOG_DIR_OVERRIDE", snapshot)

    @staticmethod
    def _build(log_dir) -> None:
        from backend_ctl.harness import build_headless_launcher

        build_headless_launcher(log_dir=log_dir)

    def test_second_build_with_other_explicit_dir_moves_env(self, monkeypatch, tmp_path) -> None:
        import os

        from multiprocess_framework.modules.process_module.managers.observability_reload import (
            resolve_base_log_dir,
        )

        self._clean_env(monkeypatch)
        first, second = tmp_path / "run_0", tmp_path / "run_1"
        self._build(first)
        self._build(second)

        expected = str(second.resolve())
        assert os.environ.get("INSPECTOR_LOG_DIR") == expected
        assert resolve_base_log_dir() == expected

    def test_operator_env_without_explicit_dir_stays(self, monkeypatch) -> None:
        """Env оператора (снят при импорте) — хозяин: сборка его не трогает."""
        import os

        operator_dir = "d:/оператор/логи"
        self._clean_env(monkeypatch, snapshot=operator_dir)
        monkeypatch.setenv("INSPECTOR_LOG_DIR", operator_dir)
        self._build(None)

        assert os.environ.get("INSPECTOR_LOG_DIR") == operator_dir

    def test_explicit_dir_beats_env_written_after_import(self, monkeypatch, tmp_path) -> None:
        """Env, появившийся после импорта (запись прошлой сборки, сосед-тест), — не воля оператора."""
        import os

        self._clean_env(monkeypatch)
        monkeypatch.setenv("INSPECTOR_LOG_DIR", "d:/чужой/след")
        target = tmp_path / "explicit"
        self._build(target)

        assert os.environ.get("INSPECTOR_LOG_DIR") == str(target.resolve())
