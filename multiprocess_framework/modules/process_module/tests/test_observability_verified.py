# -*- coding: utf-8 -*-
"""Task 5.7 — verified-смена: успех означает «действует», а не «команда выполнилась».

``config.reload`` и до 5.7 возвращал ``effective`` — readback лежал в ответе. Чего
не было, так это СУЖДЕНИЯ: ``success: True`` ставился по факту «применение не
упало», поэтому ключ, перебитый вышестоящим слоем, и **опечатка в имени** давали
тот же успех.

Вердикт трёхзначный намеренно (``confirmed`` / ``failed`` / ``unverifiable``).
Первая редакция была булевой и отдавала ``true`` при нуле проверенных путей — то
есть «подтверждено» там, где не проверялось ничего.
"""

from __future__ import annotations

from typing import Any, Dict

from multiprocess_framework.modules.process_module.managers.observability_reload import (
    observability_verified,
)

#: Readback в форме, в какой его отдаёт `observability_effective`.
_EFFECTIVE_INFO: Dict[str, Any] = {"logger": {"default_level": "INFO"}}
_EFFECTIVE_DEBUG: Dict[str, Any] = {"logger": {"default_level": "DEBUG"}}


class TestA1RequestedVersusEffective:
    """A1: сошлось → confirmed; перебито вышестоящим слоем → failed с именем ключа."""

    def test_applied_key_is_confirmed(self) -> None:
        result = observability_verified({"log_level": "DEBUG"}, _EFFECTIVE_DEBUG)
        assert result["verdict"] == "confirmed"
        assert result["checked"] == 1
        assert result["mismatches"] == []

    def test_key_not_in_effect_is_failed_and_named(self) -> None:
        """Вторая половина пары.

        Без неё тест выше зелен и у реализации «verdict = confirmed всегда» —
        то есть стерёг бы наличие поля, а не суждение.
        """
        result = observability_verified({"log_level": "DEBUG"}, _EFFECTIVE_INFO)
        assert result["verdict"] == "failed"
        assert result["mismatches"] == [{"key": "logger.default_level", "expected": "DEBUG", "actual": "INFO"}]

    def test_key_set_to_its_default_is_still_confirmed(self) -> None:
        """Ключ, заданный значением по умолчанию, — законный запрос, а не опечатка.

        Он не меняет раскладку, поэтому «изменённых путей» не даёт. Спутай его с
        неизвестным ключом — и honest-запрос «верни INFO» отвечал бы провалом.
        """
        result = observability_verified({"log_level": "INFO"}, _EFFECTIVE_INFO)
        assert result["verdict"] in ("confirmed", "unverifiable")
        assert result["unknown_keys"] == [], "ключ со значением по умолчанию назван неизвестным"


class TestA2UnknownKeysAreLoud:
    """A2: опечатка в имени — провал вердикта, а не тихий успех."""

    def test_typo_in_top_level_key_is_reported(self) -> None:
        result = observability_verified({"log_levl": "DEBUG"}, _EFFECTIVE_INFO)
        assert result["verdict"] == "failed"
        assert result["unknown_keys"] == ["log_levl"]

    def test_typo_in_nested_key_is_reported(self) -> None:
        """Вложенные ключи тоже: секция `errors` — не свалка."""
        result = observability_verified({"errors": {"lvl": 1}}, _EFFECTIVE_INFO)
        assert result["verdict"] == "failed"
        assert result["unknown_keys"] == ["errors.lvl"]

    def test_known_key_alongside_typo_does_not_hide_it(self) -> None:
        """Пара: один ключ применился, второй — опечатка. Вердикт всё равно провал.

        Иначе один верный ключ маскировал бы любую опечатку рядом.
        """
        result = observability_verified({"log_level": "DEBUG", "log_levl": "X"}, _EFFECTIVE_DEBUG)
        assert result["verdict"] == "failed"
        assert result["unknown_keys"] == ["log_levl"]
        assert result["checked"] == 1, "верный ключ должен остаться проверенным"


class TestA3VerdictIsThreeStateNotBoolean:
    """A3: «не проверено» — отдельное состояние, не успех и не провал."""

    def test_only_unverifiable_paths_give_unverifiable(self) -> None:
        """Запрос изменил лишь то, чего readback не отдаёт → подтверждать нечем.

        Первая редакция отвечала здесь `verified: true` при `checked: 0`.
        """
        result = observability_verified({"retention_days": 7}, _EFFECTIVE_INFO)
        assert result["verdict"] == "unverifiable"
        assert result["checked"] == 0
        assert result["unverifiable"], "непроверяемые пути обязаны быть названы"

    def test_confirmed_requires_at_least_one_checked_path(self) -> None:
        """Вторая половина: confirmed невозможен при нулевом охвате."""
        for section in ({}, {"retention_days": 7}):
            result = observability_verified(section, _EFFECTIVE_INFO)
            assert not (result["verdict"] == "confirmed" and result["checked"] == 0), (
                f"confirmed при нулевом охвате: {section} → {result}"
            )

    def test_coverage_is_reported_not_only_the_outcome(self) -> None:
        """Потребитель обязан видеть ОХВАТ, а не только итог."""
        result = observability_verified({"log_level": "DEBUG"}, _EFFECTIVE_DEBUG)
        assert set(result) == {"verdict", "checked", "mismatches", "unknown_keys", "unverifiable"}


class TestCoherentSnapshotForDeltaJudgement:
    """``flush=True`` — снимок КОГЕРЕНТНЫЙ: «записано» включает уже эмитированное.

    Ф7.4: прежняя редакция воспроизводила отставание счётчика БАТЧИНГОМ (запись
    ждала в пачке, и окно без ``flush`` наследовало записи команды-смены; живой
    замер 2026-07-30 дал 5.1 записи на опрос). Батчинг снят — отставания этого
    рода не существует, и когерентность стала свойством самой записи. Тест
    остаётся, потому что обещание команды не изменилось: то, что уже
    эмитировано, обязано быть посчитано к моменту ответа.
    """

    def _logger(self, tmp_path):
        from multiprocess_framework.modules.logger_module.configs import LoggerManagerConfig
        from multiprocess_framework.modules.logger_module.core.logger_manager import LoggerManager

        return LoggerManager(config=LoggerManagerConfig(app_name="coherent", log_directory=str(tmp_path)))

    def test_emitted_records_are_counted_without_waiting(self, tmp_path) -> None:
        from multiprocess_framework.modules.process_module.managers.observability_reload import (
            observability_counters,
        )

        logger = self._logger(tmp_path)
        try:
            before = observability_counters(logger=logger)["logger"]["channel_written_records"]
            for i in range(5):
                logger.info(f"запись {i}", module="unit")

            after = observability_counters(logger=logger)["logger"]["channel_written_records"]
            assert after - before >= 5, "эмитированное не посчитано к моменту ответа"
        finally:
            logger.shutdown()


class TestVerdictRidesInConfigReloadResponse:
    """Механизм, не подключённый к команде, наружу не виден.

    Отдельный тест, потому что «функция работает» и «команда её вызывает» — разные
    факты, и второй уже терялся в этом проекте (страж реестра публикации, 5.6).
    """

    def test_config_reload_returns_verdict_for_inline_section(self, tmp_path) -> None:
        from multiprocess_framework.modules.logger_module.configs import LoggerManagerConfig
        from multiprocess_framework.modules.logger_module.core.logger_manager import LoggerManager
        from multiprocess_framework.modules.process_module.commands.builtin_commands import (
            BuiltinCommands,
        )

        class _Cm:
            def __init__(self) -> None:
                self.handlers: Dict[str, Any] = {}

            def register_command(self, name, handler, metadata=None, tags=None) -> None:
                self.handlers[name] = handler

        class _Svc:
            def __init__(self, logger) -> None:
                self.name = "verified_probe"
                self.logger_manager = logger
                self.error_manager = None
                self.stats_manager = None
                self.command_manager = _Cm()
                self._values: Dict[str, Any] = {}

            def get_config(self, key, default=None):
                return self._values.get(key, default)

            def update_config(self, key, value) -> bool:
                self._values[key] = value
                return True

            def _log_info(self, *a, **kw) -> None:
                pass

            def _log_error(self, *a, **kw) -> None:
                pass

            def _log_debug(self, *a, **kw) -> None:
                pass

        logger = LoggerManager(
            config=LoggerManagerConfig(app_name="v", log_directory=str(tmp_path), enable_batching=False)
        )
        try:
            svc = _Svc(logger)
            BuiltinCommands(svc)._register_observability_commands()
            reload_cmd = svc.command_manager.handlers["config.reload"]

            ok = reload_cmd({"observability": {"log_level": "DEBUG"}})
            assert ok["verified"]["verdict"] == "confirmed", ok["verified"]

            # Вторая половина 5.7 живёт в драйвере, но БАЗА ОТСЧЁТА для неё едет
            # этим ответом — и снимается ПОСЛЕ применения, иначе окно доставки
            # начиналось бы до смены и прежний уровень доказывал бы новый.
            # Форма — та же, что у `introspect.observability` (ключ `counters`):
            # оба снимка читаются одной функцией.
            counters = ok["counters"]
            assert "channel_written_records" in counters["logger"], counters["logger"].keys()
            assert "observed_at" in counters["logger"]

            # Пара: опечатка через ту же команду — вердикт провальный, при том что
            # само применение не упало (`success` остаётся истинным).
            bad = reload_cmd({"observability": {"log_levl": "DEBUG"}})
            assert bad.get("success") is True, "применение не должно падать из-за опечатки"
            assert bad["verified"]["verdict"] == "failed", bad["verified"]
            assert bad["verified"]["unknown_keys"] == ["log_levl"]
        finally:
            logger.shutdown()
