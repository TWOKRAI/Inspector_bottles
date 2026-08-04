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
