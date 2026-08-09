# -*- coding: utf-8 -*-
"""Task 5.10 — симметрия namespace: одна декларация на все плоскости.

Что здесь закрепляется (и чего до 5.10 не было):

  * плоскости **ошибок** и **статистики** адресуемы слоем конфига так же, как
    логгер: снятый приёмник переживает ``config.reload``, а не воскресает молча;
  * **частичная** запись (``{enabled: false}``) не стирает описание канала —
    иначе вернуть его было бы некуда (слияние стало глубоким);
  * ``module_*``-каналы логгера гасятся тем же ключом ``channels.<имя>.enabled``
    (резидуал R3 из 5.12) и не порождают фантомного файла;
  * служебные каналы статистики (``log_stats``/``file_stats``) читают тот же
    ключ — до 5.10 он там существовал и не значил ничего.

Тесты гоняют РЕАЛЬНЫЕ менеджеры и реальные обработчики команд: проверка на
фейках доказала бы фейки.
"""

from __future__ import annotations


import pytest

from multiprocess_framework.modules.error_module import ErrorManager
from multiprocess_framework.modules.error_module.core.error_config_assembly import (
    expand_error_manager_config,
)
from multiprocess_framework.modules.logger_module.configs import (
    LoggerManagerConfig,
)
from multiprocess_framework.modules.logger_module.core.logger_manager import LoggerManager
from multiprocess_framework.modules.process_module.commands.builtin_commands import BuiltinCommands
from multiprocess_framework.modules.statistics_module import StatsManager
from multiprocess_framework.modules.statistics_module.core.stats_manager import (
    STATS_FALLBACK_CHANNEL,
    STATS_LOG_CHANNEL,
)

from .test_observability_session_layer import _Svc


def _names(manager) -> list:
    return sorted(getattr(manager, "_channel_registry").names())


# =============================================================================
# A2 — частичная запись не стирает описание канала
# =============================================================================


class TestPartialOverrideKeepsTheDescription:
    def test_disable_record_does_not_strip_the_file_path(self) -> None:
        """Воспроизведение дефекта, который делал симметрию невозможной.

        До 5.10.a слияние было поверхностным, и от ``errors_file`` оставался
        ровно один ключ ``{'enabled': False}`` — без ``type``, без ``file_path``.
        Литералы, а не производные от кода: иначе тест согласится с любым ответом.
        """
        expanded = expand_error_manager_config(
            {
                "error_file_path": "logs/my_errors.log",
                "channels": {"errors_file": {"enabled": False}},
            }
        )
        ch = expanded["channels"]["errors_file"]
        assert ch["enabled"] is False
        assert ch["file_path"] == "logs/my_errors.log"
        assert ch["type"] == "file"

    def test_neighbour_channel_is_untouched(self) -> None:
        """Снятие адресное: ``critical_file`` не должен ни исчезнуть, ни погаснуть."""
        expanded = expand_error_manager_config({"channels": {"errors_file": {"enabled": False}}})
        assert expanded["channels"]["critical_file"]["enabled"] is True
        assert expanded["channels"]["critical_file"]["file_path"] == "logs/critical.log"

    def test_full_replacement_still_wins_where_it_is_given(self) -> None:
        """Цена глубокого слияния названа: заданные ключи по-прежнему побеждают."""
        expanded = expand_error_manager_config(
            {"channels": {"errors_file": {"file_path": "logs/other.log", "backup_count": 99}}}
        )
        assert expanded["channels"]["errors_file"]["file_path"] == "logs/other.log"
        assert expanded["channels"]["errors_file"]["backup_count"] == 99


# =============================================================================
# A1 — плоскость ошибок переживает пересборку
# =============================================================================


@pytest.fixture
def error_wired(tmp_path, monkeypatch):
    """Живые LoggerManager + ErrorManager и зарегистрированные команды.

    ``INSPECTOR_LOG_DIR`` выставляется намеренно: пересборка стартует от
    МАШИННОГО контекста (``resolve_base_log_dir``), а не от живого конфига
    менеджера — иначе удаление ``log_directory`` из слоя перестало бы работать
    (Task 5.12). Без этой строки ``config.reload`` уводит каналы в ``./logs``, и
    тест, проверяющий СОДЕРЖИМОЕ файла, ловит не ту гарантию.
    """
    monkeypatch.setenv("INSPECTOR_LOG_DIR", str(tmp_path))
    logger = LoggerManager(
        config=LoggerManagerConfig(app_name="sym", log_directory=str(tmp_path), enable_batching=False, modules={})
    )
    error = ErrorManager(
        config={
            "error_file_path": str(tmp_path / "errors.log"),
            "critical_file_path": str(tmp_path / "critical.log"),
            "warnings_file_path": None,
            "enable_batching": False,
        }
    )
    error.initialize()
    svc = _Svc(logger)
    svc.error_manager = error
    bc = BuiltinCommands(svc)
    bc._register_observability_commands()
    try:
        yield svc, svc.command_manager.handlers, tmp_path
    finally:
        error.shutdown()
        logger.shutdown()


class TestErrorPlaneSurvivesReload:
    def test_disabled_error_sink_stays_disabled_after_reload(self, error_wired) -> None:
        """Главная пара 5.10: снял приёмник ошибок → пересобрал → он всё ещё снят.

        До задачи `_record_sink_in_session` возвращал None для этой плоскости,
        и первый же `config.reload` возвращал `errors_file` молча.
        """
        svc, handlers, _ = error_wired
        assert "errors_file" in _names(svc.error_manager)

        res = handlers["logger.sink.disable"]({"sink": "errors_file", "manager": "error"})
        assert res["success"] is True
        assert res["session_key"] == "errors.channels.errors_file.enabled"
        assert "errors_file" not in _names(svc.error_manager)

        reload_res = handlers["config.reload"]({"observability": {}, "path": None})
        assert reload_res["success"] is True
        assert "errors.channels.errors_file.enabled" in reload_res["session_keys"]
        assert "errors_file" not in _names(svc.error_manager), "приёмник воскрес мимо слоя"
        assert "critical_file" in _names(svc.error_manager), "снятие задело соседа"

    def test_re_enabled_sink_writes_to_the_same_file(self, error_wired) -> None:
        """Пара к предыдущему: вернули — и запись идёт в ТОТ ЖЕ файл.

        Это и есть проверка глубокого слияния на живом менеджере: при
        поверхностном канал вернулся бы без пути и писал бы мимо (либо не
        поднялся бы вовсе). Наблюдаемый эффект — содержимое файла, а не имя
        в реестре.
        """
        svc, handlers, tmp_path = error_wired
        handlers["logger.sink.disable"]({"sink": "errors_file", "manager": "error"})
        handlers["config.reload"]({"observability": {}, "path": None})
        res = handlers["logger.sink.enable"]({"sink": "errors_file", "manager": "error"})
        assert res["success"] is True

        svc.error_manager.error("контрольная запись после возврата", module="sym")
        svc.error_manager.flush()
        text = (tmp_path / "errors.log").read_text(encoding="utf-8", errors="replace")
        assert "контрольная запись после возврата" in text

    def test_the_operator_mark_survives_the_rebuild_on_this_plane_too(self, error_wired) -> None:
        """«Я его снял» ≠ «канал не поднялся» — ответ обязан различать и здесь."""
        svc, handlers, _ = error_wired
        handlers["logger.sink.disable"]({"sink": "errors_file", "manager": "error"})
        handlers["config.reload"]({"observability": {}, "path": None})
        assert "errors_file" in getattr(svc.error_manager, "_sinks_disabled_by_operator")

    def test_readback_names_what_the_operator_disabled(self, error_wired) -> None:
        """Находка ЖИВОГО прогона: отметка ставилась, но наружу не отдавалась.

        Команда отвечала `session_key: errors.channels.errors_file.enabled`, а
        `introspect.observability` показывал по плоскости ошибок только уровень —
        ни состава приёмников, ни снятого оператором. Два ответа об одном
        состоянии противоречили друг другу, и правым выглядел readback.
        """
        svc, handlers, _ = error_wired
        res = handlers["config.reload"]({"observability": {}, "path": None})
        assert "errors_file" in res["effective"]["error"]["channels_active"]

        handlers["observability.sink.disable"]({"sink": "errors_file", "manager": "error"})
        res = handlers["config.reload"]({"observability": {}, "path": None})
        assert res["effective"]["error"]["sinks_disabled_by_operator"] == ["errors_file"]
        assert "errors_file" not in res["effective"]["error"]["channels_active"]


# =============================================================================
# A3 / R3 — СНЯТО в Ф2.6 вместе с механизмом per-module файлов
# =============================================================================
#
# Здесь жили три теста про `module_*`-каналы логгера: декларативное снятие ключом
# `channels.module_camera.enabled=false`, отсутствие фантомного файла и возврат
# настоящего канала с его путём. Все три сторожили механизм, которого больше нет.
#
# **Свойства не потеряны, а переехали вместе с механизмом:**
#
# * симметрия «снял ключом — вернул командой» для ОБЫЧНЫХ каналов остаётся выше
#   (`TestLoggerChannels`, `TestErrorChannels`) — она и была общим правилом;
# * ловушка «запись об отмене прочитана как описание канала → фантомный файл»
#   исчезла по построению: она существовала ровно потому, что у per-module
#   каналов описание жило в ОДНОЙ секции (`modules`), а отметка о снятии — в
#   ДРУГОЙ (`channels`). Одна секция — двух написаний нет;
# * «канал переживает пересборку» проверялось на ключе `camera`, который приезжал
#   из дефолта фреймворка. Дефолт убран (девять ключей доставляли ноль записей —
#   замер в схеме), и воспроизвести условие было бы нечем: секции `modules` в
#   `observability` никогда не существовало, то есть приложение этот механизм
#   настроить не могло в принципе.

# =============================================================================
# A4 — служебные каналы плоскости статистики
# =============================================================================


class TestStatsServiceChannels:
    def test_log_channel_is_disabled_declaratively(self, tmp_path) -> None:
        """``channels.log_stats.enabled=false`` гасит канал, которого нет в описаниях.

        Логгер регистрируется НЕ для полноты картины: без него
        ``_build_log_channel`` возвращает ``None``, канала не существует ни до,
        ни после — и проверка «его нет» проходит ни на чём. Первая редакция
        этого теста была именно такой и пережила снятие собственной защиты
        (слом-инъекция B9).
        """
        logger = LoggerManager(
            config=LoggerManagerConfig(app_name="stt", log_directory=str(tmp_path), enable_batching=False, modules={})
        )
        stats = StatsManager(config={"enable_logging": True})
        stats.register_manager("logger", logger)
        stats.initialize()
        try:
            assert STATS_LOG_CHANNEL in _names(stats), "канал не поднялся — проверять нечего"
            stats.reconfigure(
                {
                    "enable_logging": True,
                    "channels": {STATS_LOG_CHANNEL: {"enabled": False}},
                }
            )
            assert STATS_LOG_CHANNEL not in _names(stats)
        finally:
            stats.shutdown()
            logger.shutdown()

    def test_fallback_removal_is_honoured_and_said_out_loud(self, tmp_path) -> None:
        """Снятие последнего приёмника — законное решение, но не молчаливое.

        «Всегда есть куда писать» ценно как умолчание и вредно как запрет:
        иначе ключ конфига существовал бы и не значил ничего. Цена — плоскость
        без приёмников, поэтому она обязана быть названа вслух.
        """
        stats = StatsManager(config={"enable_logging": False})
        stats.initialize()
        said: list = []
        stats._log_error = lambda msg, *a, **kw: said.append(str(msg))  # type: ignore[method-assign]
        try:
            stats.reconfigure(
                {
                    "enable_logging": False,
                    "channels": {STATS_FALLBACK_CHANNEL: {"enabled": False}},
                }
            )
            assert _names(stats) == [], "fallback вернулся вопреки снятию"
            assert any(STATS_FALLBACK_CHANNEL in m for m in said), f"снятие прошло молча: {said}"
        finally:
            stats.shutdown()

    def test_disabled_stats_sink_stays_disabled_after_reload(self, tmp_path, monkeypatch) -> None:
        """Та же главная пара, что у ошибок, — на третьей плоскости.

        Отдельным тестом, а не «заодно»: раскладка ``stats.channels`` в
        ``expand_observability`` — своя ветка кода, и без своей пары её снятие
        не заметил бы ни один слом.
        """
        monkeypatch.setenv("INSPECTOR_LOG_DIR", str(tmp_path))
        logger = LoggerManager(
            config=LoggerManagerConfig(app_name="sym", log_directory=str(tmp_path), enable_batching=False, modules={})
        )
        stats = StatsManager(config={"enable_logging": False})
        stats.initialize()
        svc = _Svc(logger)
        svc.stats_manager = stats
        bc = BuiltinCommands(svc)
        bc._register_observability_commands()
        handlers = svc.command_manager.handlers
        try:
            assert STATS_FALLBACK_CHANNEL in _names(stats)
            res = handlers["observability.sink.disable"]({"sink": STATS_FALLBACK_CHANNEL, "manager": "stats"})
            assert res["success"] is True
            assert STATS_FALLBACK_CHANNEL not in _names(stats)

            handlers["config.reload"]({"observability": {}, "path": None})
            assert STATS_FALLBACK_CHANNEL not in _names(stats), "приёмник статистики воскрес мимо слоя"
        finally:
            stats.shutdown()
            logger.shutdown()

    def test_default_still_guarantees_one_channel(self, tmp_path) -> None:
        """Контроль: без явного снятия умолчание не изменилось."""
        stats = StatsManager(config={"enable_logging": False})
        stats.initialize()
        try:
            assert _names(stats) == [STATS_FALLBACK_CHANNEL]
        finally:
            stats.shutdown()


# =============================================================================
# A6 — честное имя команды
# =============================================================================


class TestCanonicalNameAndAlias:
    """Имя называет охват; старое написание остаётся живым."""

    def test_both_names_lead_to_the_same_handler(self, error_wired) -> None:
        """Алиас — второе ИМЯ одной команды, а не вторая реализация.

        Проверяется тождество объектов, а не совпадение ответов: две ветки,
        дающие сегодня одинаковый ответ, разъезжаются на первой же правке одной
        из них — и разъезд был бы молчаливым.
        """
        _, handlers, _ = error_wired
        for suffix in ("enable", "disable", "tail"):
            assert handlers[f"observability.sink.{suffix}"] == handlers[f"logger.sink.{suffix}"]

    def test_alias_addresses_the_error_plane_too(self, error_wired) -> None:
        """Старое написание не потеряло охвата, ради которого имя менялось."""
        svc, handlers, _ = error_wired
        res = handlers["observability.sink.disable"]({"sink": "errors_file", "manager": "error"})
        assert res["success"] is True
        assert "errors_file" not in _names(svc.error_manager)

    def test_contract_judges_both_names(self) -> None:
        """Контракт у имени и алиаса ОДИН — иначе он обходится сменой написания."""
        from multiprocess_framework.modules.process_module.commands.command_contracts import (
            BUILTIN_COMMAND_CONTRACTS,
        )

        for suffix in ("enable", "disable"):
            assert (
                BUILTIN_COMMAND_CONTRACTS[f"observability.sink.{suffix}"]
                is BUILTIN_COMMAND_CONTRACTS[f"logger.sink.{suffix}"]
            )


if __name__ == "__main__":  # pragma: no cover
    pytest.main([__file__, "-v"])
