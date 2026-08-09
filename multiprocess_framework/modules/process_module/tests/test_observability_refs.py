# -*- coding: utf-8 -*-
"""Task 5.5 — имя, за которым нет приёмника, обязано быть громким.

План: `plans/observability-unified-routing.md`, Task 5.5 (A1–A3, A5).

Репро дефекта (живой путь `config.reload`, 2026-07-30):
``channels: {messages_fil: {enabled: false}}`` → `success=true`, вердикт
`unverifiable`; ``scopes: {SYSTEMM: {min_level: DEBUG}}`` → `success=true`, вердикт
**`confirmed`** — ложное подтверждение, потому что ключ действительно виден в
readback, а эффекта у него ноль.

Главное, что стерегут эти тесты, — **не запрет незнакомых имён**. `LoggerScopeSchema`
несёт свои `channels`, `LoggerChannelSchema` — `type`: новое имя С ТЕЛОМ законно
определяет сущность. Различие «определение против ссылки в пустоту» и есть предмет
задачи; запрети мы имена целиком — конфиг потерял бы право добавлять приёмники.
"""

from __future__ import annotations

from typing import Any, Dict, List

from multiprocess_framework.modules.process_module.configs.observability_refs import (
    known_refs_from_managers,
    unknown_observability_refs,
    unknown_recipe_processes,
)

#: Известные имена «как у живого процесса»: три плоскости + скоупы логгера.
_KNOWN: Dict[str, Any] = {
    "logger": {"console", "messages_file", "system_file"},
    "error": {"errors_file", "critical_file"},
    "stats": {"log_stats"},
    "scopes": {"SYSTEM", "BUSINESS"},
}


class TestReferenceVersusDefinition:
    """Незнакомое имя С ТЕЛОМ — определение. Без тела — ссылка в пустоту."""

    def test_unknown_channel_without_type_is_reported(self) -> None:
        refs = unknown_observability_refs({"channels": {"messages_fil": {"enabled": False}}}, _KNOWN)
        assert refs == {"channels": ["messages_fil"]}

    def test_unknown_channel_with_type_is_a_definition(self) -> None:
        """Вторая половина пары. Без неё «проверка» запрещала бы новые приёмники."""
        refs = unknown_observability_refs(
            {"channels": {"audit_file": {"type": "file", "enabled": True, "path": "audit.log"}}},
            _KNOWN,
        )
        assert refs == {}

    def test_known_channel_is_never_reported(self) -> None:
        assert unknown_observability_refs({"channels": {"console": {"enabled": False}}}, _KNOWN) == {}

    def test_error_and_stats_planes_are_checked_under_their_own_paths(self) -> None:
        """Симметрия трёх плоскостей (5.10): у ошибок и статистики свои каталоги имён."""
        refs = unknown_observability_refs(
            {
                "errors": {"channels": {"errors_fil": {"enabled": False}}},
                "stats": {"channels": {"log_stat": {"enabled": False}}},
            },
            _KNOWN,
        )
        assert refs == {"errors.channels": ["errors_fil"], "stats.channels": ["log_stat"]}

    def test_plane_catalogues_do_not_leak_into_each_other(self) -> None:
        """Имя канала ошибок в секции логгера — всё равно ссылка в пустоту.

        Иначе одного общего множества имён хватило бы, чтобы опечатка «не в той
        плоскости» проходила молча.
        """
        refs = unknown_observability_refs({"channels": {"errors_file": {"enabled": False}}}, _KNOWN)
        assert refs == {"channels": ["errors_file"]}


class TestScopeIsARuleThatMustHaveSomewhereToWrite:
    def test_new_scope_without_channels_is_reported(self) -> None:
        refs = unknown_observability_refs({"scopes": {"SYSTEMM": {}}}, _KNOWN)
        assert refs == {"scopes": ["SYSTEMM"]}

    def test_new_scope_with_channels_is_a_definition(self) -> None:
        refs = unknown_observability_refs(
            {"scopes": {"AUDIT": {"channels": ["system_file"]}}},
            _KNOWN,
        )
        assert refs == {}

    def test_known_scope_without_channels_is_legitimate(self) -> None:
        """У известного скоупа каналы приедут снизу merge'ем.

        Требуй мы их здесь — самая частая правка (`{min_level: DEBUG}`) стала бы
        отказом.
        """
        assert unknown_observability_refs({"scopes": {"SYSTEM": {}}}, _KNOWN) == {}

    def test_scope_pointing_at_unknown_channel_is_reported(self) -> None:
        refs = unknown_observability_refs(
            {"scopes": {"SYSTEM": {"channels": ["system_file", "systm_file"]}}},
            _KNOWN,
        )
        assert refs == {"scopes.channels": ["SYSTEM.systm_file"]}

    def test_scope_may_point_at_a_channel_defined_in_the_same_section(self) -> None:
        """Определение канала и ссылка на него в одной секции — законная пара."""
        refs = unknown_observability_refs(
            {
                "channels": {"audit_file": {"type": "file", "path": "a.log"}},
                "scopes": {"AUDIT": {"channels": ["audit_file"]}},
            },
            _KNOWN,
        )
        assert refs == {}


class TestKnownNamesComeFromRegistryAndConfigTogether:
    """Ни реестра, ни конфига по отдельности не хватает."""

    def test_channel_removed_from_registry_but_present_in_config_is_known(self) -> None:
        """`sink.disable` убрал канал из реестра. `{enabled: true}` про него —
        законный ВОЗВРАТ, а не опечатка."""

        class _Ch:
            def __init__(self, name: str) -> None:
                self.name = name

        class _Cfg:
            channels = {"console": {}, "messages_file": {}}
            scopes = {"SYSTEM": {}}

        class _Mgr:
            config = _Cfg()

            def get_all_channels(self) -> List[Any]:
                return [_Ch("console")]  # messages_file снят рантаймом

        known = known_refs_from_managers(logger=_Mgr())
        assert "messages_file" in known["logger"], "снятый приёмник объявлен неизвестным"
        assert unknown_observability_refs({"channels": {"messages_file": {"enabled": True}}}, known) == {}

    def test_runtime_channel_absent_from_config_is_known(self) -> None:
        """Зеркало: построенный рантаймом канал есть в реестре и не в конфиге."""

        class _Ch:
            name = "module_gui"

        class _Mgr:
            config = type("C", (), {"channels": {}, "scopes": {}})()

            def get_all_channels(self) -> List[Any]:
                return [_Ch()]

        known = known_refs_from_managers(logger=_Mgr())
        assert unknown_observability_refs({"channels": {"module_gui": {"enabled": False}}}, known) == {}


class TestRecipeProcessNames:
    """Шаг 10 задачи 5.13: адресная секция для процесса с опечаткой не доезжает НИ ДО КОГО."""

    def test_unknown_process_name_is_reported(self) -> None:
        section = {"processes": {"camera_0": {"log_level": "DEBUG"}, "camera_9": {"log_level": "DEBUG"}}}
        assert unknown_recipe_processes(section, ["camera_0", "gui"]) == ["camera_9"]

    def test_all_known_names_report_nothing(self) -> None:
        section = {"processes": {"camera_0": {}, "gui": {}}}
        assert unknown_recipe_processes(section, ["camera_0", "gui", "ProcessManager"]) == []

    def test_section_without_processes_is_not_an_error(self) -> None:
        assert unknown_recipe_processes({"log_level": "DEBUG"}, ["camera_0"]) == []


class TestEmptySectionSaysNothing:
    def test_empty_and_absent_sections_are_silent(self) -> None:
        for section in ({}, None, {"log_level": "DEBUG"}):
            assert unknown_observability_refs(section, _KNOWN) == {}


# --------------------------------------------------------------------------
# Живой путь команды: inline отказывает, файл говорит вслух
# --------------------------------------------------------------------------


class _Cm:
    def __init__(self) -> None:
        self.handlers: Dict[str, Any] = {}

    def register_command(self, name, handler, metadata=None, tags=None) -> None:
        self.handlers[name] = handler


class _Svc:
    """Процесс с ЖИВЫМ логгером и обработчиком конфига — как настоящий ребёнок.

    Фейк без `config_handler`/`update_config` уже давал ложные результаты на этом
    плане (находка «update_config мёртв при живом handler»), поэтому читаем и пишем
    тем же способом, что потребители.
    """

    def __init__(self, logger) -> None:
        self.name = "refs_probe"
        self.logger_manager = logger
        self.error_manager = None
        self.stats_manager = None
        self.command_manager = _Cm()
        self._values: Dict[str, Any] = {}
        self.errors: List[str] = []

    def get_config(self, key, default=None):
        return self._values.get(key, default)

    def update_config(self, key, value) -> bool:
        self._values[key] = value
        return True

    def _log_info(self, *a, **kw) -> None:
        pass

    def _log_error(self, message, *a, **kw) -> None:
        self.errors.append(str(message))

    def _log_debug(self, *a, **kw) -> None:
        pass


def _reload_command(tmp_path):
    from multiprocess_framework.modules.logger_module.configs import LoggerManagerConfig
    from multiprocess_framework.modules.logger_module.core.logger_manager import LoggerManager
    from multiprocess_framework.modules.process_module.commands.builtin_commands import BuiltinCommands

    logger = LoggerManager(
        config=LoggerManagerConfig(app_name="refs", log_directory=str(tmp_path), enable_batching=False)
    )
    svc = _Svc(logger)
    BuiltinCommands(svc)._register_observability_commands()
    return svc, logger, svc.command_manager.handlers["config.reload"]


def _snapshot(logger) -> tuple:
    return (
        tuple(sorted(ch.name for ch in logger.get_all_channels())),
        tuple(sorted(getattr(logger.config, "scopes", {}) or {})),
        getattr(logger.config, "default_level", None),
    )


class TestInlineTypoIsRefusedWithoutTouchingState:
    """A1/A2: ручка оператора — отказ ДО применения, состояние не изменилось."""

    def test_channel_typo_is_refused_and_nothing_changes(self, tmp_path) -> None:
        svc, logger, reload_cmd = _reload_command(tmp_path)
        try:
            before = _snapshot(logger)
            res = reload_cmd({"observability": {"channels": {"messages_fil": {"enabled": False}}}})
            assert res["success"] is False
            assert res["unknown_refs"] == {"channels": ["messages_fil"]}
            assert "messages_fil" in res["reason"]
            assert _snapshot(logger) == before, "состояние изменилось при отказе"
            assert svc.get_config("observability_session") in (None, {}), "слой сессии тронут при отказе"
        finally:
            logger.shutdown()

    def test_new_scope_without_channels_no_longer_reports_confirmed(self, tmp_path) -> None:
        """Тот самый ложный `confirmed` из репро: вердикт видел ключ в readback."""
        svc, logger, reload_cmd = _reload_command(tmp_path)
        try:
            before = _snapshot(logger)
            res = reload_cmd({"observability": {"scopes": {"SYSTEMM": {}}}})
            assert res["success"] is False, res
            assert res["unknown_refs"] == {"scopes": ["SYSTEMM"]}
            assert "verified" not in res, "вердикт о значении не выносится, когда применения не было"
            assert _snapshot(logger) == before
        finally:
            logger.shutdown()

    def test_legitimate_change_is_not_refused(self, tmp_path) -> None:
        """Вторая половина пары: настоящая правка проходит.

        Без неё реализация «отказывать всегда» была бы зелёной.
        """
        svc, logger, reload_cmd = _reload_command(tmp_path)
        try:
            res = reload_cmd({"observability": {"log_level": "DEBUG", "channels": {"console": {"enabled": False}}}})
            assert res["success"] is True, res
            assert "unknown_refs" not in res
            assert res["applied"]["log_level"] == "DEBUG"
        finally:
            logger.shutdown()


class TestFileReloadSpeaksInsteadOfRefusing:
    """A3: опечатка в файле применяет остальное, но громко себя называет.

    Отказ здесь означал бы, что опечатка в спутнике валит switch рецепта.
    """

    def test_file_typo_applies_the_rest_and_logs_loudly(self, tmp_path) -> None:
        import json

        svc, logger, reload_cmd = _reload_command(tmp_path)
        cfg = tmp_path / "obs.json"
        cfg.write_text(
            json.dumps({"observability": {"log_level": "WARNING", "channels": {"messages_fil": {"enabled": False}}}}),
            encoding="utf-8",
        )
        try:
            res = reload_cmd({"path": str(cfg)})
            assert res["success"] is True, res
            assert res["unknown_refs"] == {"channels": ["messages_fil"]}
            assert res["applied"]["log_level"] == "WARNING", "остальное обязано примениться"
            assert any("messages_fil" in line for line in svc.errors), svc.errors
        finally:
            logger.shutdown()

    def test_clean_file_leaves_no_line(self, tmp_path) -> None:
        """Вторая половина: без опечатки громкой строки нет — иначе она стала бы шумом."""
        import json

        svc, logger, reload_cmd = _reload_command(tmp_path)
        cfg = tmp_path / "obs.json"
        cfg.write_text(json.dumps({"observability": {"log_level": "WARNING"}}), encoding="utf-8")
        try:
            res = reload_cmd({"path": str(cfg)})
            assert res["success"] is True
            assert "unknown_refs" not in res
            assert svc.errors == [], svc.errors
        finally:
            logger.shutdown()


# --------------------------------------------------------------------------
# ФР-2: ПЯТЬ дорог в слой L2, и громкой была не каждая
# --------------------------------------------------------------------------
#
# Находка C-4-1 сквозного ревью Ф5. Проверка ссылок стояла на двух дорогах —
# inline (отказ) и файл L1 (громко), — а тело в слой кладут пять. Тихими были:
# конверт switch'а, перечитка спутника по команде и подхват спутника на boot.
# Связка с `observability.persist` замыкала круг: законный ключ на СНЯТЫЙ канал
# сохранялся в спутник и на следующем старте въезжал тихой дорогой — опечатка,
# увековеченная машиной.
#
# Тесты ниже перенесены из репро, которым дефект был подтверждён, и дополнены
# вторыми половинами пар: без них зелёной была бы и реализация «говорить всегда».


def _recipe_with_companion(tmp_path, companion_section):
    """Рецепт + спутник рядом. Спутник пишется ТЕМ ЖЕ кодом, что `persist`."""
    from multiprocess_framework.modules.process_module.configs.observability_companion import write_companion

    recipe = tmp_path / "line.yaml"
    recipe.write_text("processes: {}\n", encoding="utf-8")
    write_companion(recipe, companion_section)
    return recipe


class TestSwitchEnvelopeRoad:
    """Дорога 1: конверт switch'а кладёт дольку рецепта в слой L2."""

    def test_typo_in_the_envelope_is_loud_and_reported(self, tmp_path) -> None:
        svc, logger, reload_cmd = _reload_command(tmp_path)
        recipe = tmp_path / "line.yaml"
        recipe.write_text("processes: {}\n", encoding="utf-8")
        try:
            res = reload_cmd(
                {
                    "observability_recipe": {"channels": {"messages_fil": {"enabled": False}}},
                    "observability_recipe_path": str(recipe),
                }
            )
            assert res["success"] is True, res
            assert res["unknown_refs"] == {"channels": ["messages_fil"]}
            assert any("messages_fil" in line for line in svc.errors), svc.errors
        finally:
            logger.shutdown()

    def test_clean_envelope_leaves_no_line(self, tmp_path) -> None:
        """Вторая половина пары: иначе «громко всегда» прошло бы за починку."""
        svc, logger, reload_cmd = _reload_command(tmp_path)
        recipe = tmp_path / "line.yaml"
        recipe.write_text("processes: {}\n", encoding="utf-8")
        try:
            res = reload_cmd(
                {
                    "observability_recipe": {"channels": {"messages_file": {"enabled": False}}},
                    "observability_recipe_path": str(recipe),
                }
            )
            assert res["success"] is True, res
            assert "unknown_refs" not in res
            assert svc.errors == [], svc.errors
        finally:
            logger.shutdown()

    def test_typo_does_not_stop_the_switch(self, tmp_path) -> None:
        """Hazard: политика — «сказать», а не «отказать».

        Отказ здесь означал бы, что опечатка в machine-owned спутнике валит switch
        рецепта: система встаёт из-за ключа, который сам по себе безвреден. Слой
        обязан въехать целиком, а законная часть — примениться.
        """
        svc, logger, reload_cmd = _reload_command(tmp_path)
        recipe = tmp_path / "line.yaml"
        recipe.write_text("processes: {}\n", encoding="utf-8")
        try:
            res = reload_cmd(
                {
                    "observability_recipe": {
                        "log_level": "WARNING",
                        "channels": {"messages_fil": {"enabled": False}},
                    },
                    "observability_recipe_path": str(recipe),
                }
            )
            assert res["success"] is True, res
            assert res["applied"]["log_level"] == "WARNING", "законная часть конверта не применена"
            assert logger.config.default_level == "WARNING"
            assert "channels.messages_fil.enabled" in res["recipe_layer"], "слой не въехал из-за опечатки"
        finally:
            logger.shutdown()


class TestCompanionRefreshRoad:
    """Дорога 2: перечитка слоя L2 со своего адреса (`observability_recipe_reload`).

    Так до ребёнка доезжает правка спутника — оркестратор рассылает «перечитай»,
    секция по проводу не едет.
    """

    def test_typo_on_refresh_is_loud_and_reported(self, tmp_path) -> None:
        from multiprocess_framework.modules.process_module.configs.observability_layers import (
            RECIPE_PATH_CONFIG_KEY,
        )

        svc, logger, reload_cmd = _reload_command(tmp_path)
        recipe = _recipe_with_companion(
            tmp_path, {"processes": {"refs_probe": {"channels": {"messages_fil": {"enabled": False}}}}}
        )
        try:
            svc.update_config(RECIPE_PATH_CONFIG_KEY, str(recipe))
            res = reload_cmd({"observability_recipe_reload": True})
            assert res["success"] is True, res
            assert res["unknown_refs"] == {"channels": ["messages_fil"]}
            assert any("messages_fil" in line for line in svc.errors), svc.errors
        finally:
            logger.shutdown()

    def test_clean_refresh_leaves_no_line(self, tmp_path) -> None:
        from multiprocess_framework.modules.process_module.configs.observability_layers import (
            RECIPE_PATH_CONFIG_KEY,
        )

        svc, logger, reload_cmd = _reload_command(tmp_path)
        recipe = _recipe_with_companion(tmp_path, {"processes": {"refs_probe": {"log_level": "WARNING"}}})
        try:
            svc.update_config(RECIPE_PATH_CONFIG_KEY, str(recipe))
            res = reload_cmd({"observability_recipe_reload": True})
            assert res["success"] is True, res
            assert "unknown_refs" not in res
            assert svc.errors == [], svc.errors
        finally:
            logger.shutdown()

    def test_refresh_does_not_rewrite_the_companion(self, tmp_path) -> None:
        """Hazard: громкая строка не имеет права разбудить watcher.

        За спутником следит наблюдатель, и запись в файл (даже с тем же
        содержимым) — это новый mtime, то есть «файл изменился → перечитай →
        снова пожаловались → …». Петля выглядела бы как зависший hot-reload.
        Проверяем ФАЙЛ, а не намерение: жалоба уходит в журнал ошибок, спутник
        остаётся байт в байт прежним.

        Опечатка взята в плоскости ОШИБОК, а менеджера ошибок у этого процесса
        нет: такое имя не поглощается каталогом при применении (см.
        ``test_a_named_channel_joins_the_catalogue``) и потому остаётся сиротой на
        каждой перечитке. Иначе тест «три перечитки — три строки» был бы зелёным
        и у реализации, которая молчит начиная со второй.
        """
        from multiprocess_framework.modules.process_module.configs.observability_companion import companion_path
        from multiprocess_framework.modules.process_module.configs.observability_layers import (
            RECIPE_PATH_CONFIG_KEY,
        )

        svc, logger, reload_cmd = _reload_command(tmp_path)
        recipe = _recipe_with_companion(
            tmp_path,
            {"processes": {"refs_probe": {"errors": {"channels": {"errors_fil": {"enabled": False}}}}}},
        )
        path = companion_path(recipe)
        before = (path.read_bytes(), path.stat().st_mtime_ns)
        try:
            svc.update_config(RECIPE_PATH_CONFIG_KEY, str(recipe))
            for _ in range(3):
                res = reload_cmd({"observability_recipe_reload": True})
                assert res["unknown_refs"] == {"errors.channels": ["errors_fil"]}, res
            assert (path.read_bytes(), path.stat().st_mtime_ns) == before, "жалоба тронула наблюдаемый файл"
            assert len(svc.errors) == 3, f"ожидалась ровно одна строка на перечитку: {svc.errors}"
        finally:
            logger.shutdown()

    def test_validation_belongs_to_the_road_not_to_the_rebuild(self, tmp_path) -> None:
        """Hazard: считать сироты на КАЖДОЙ пересборке — значит залить журнал.

        Слой L2 с опечаткой живёт до следующего switch'а, а пересборка случается
        от любой ручки оператора. Привяжись проверка к пересборке (например,
        встань она внутри `apply_observability_layers`), одна и та же опечатка
        печаталась бы снова и снова, и громкость выродилась бы в фон.

        Опечатка — снова в плоскости ошибок (менеджера нет): имя, которое НЕ
        уходит в каталог, продолжало бы называться на каждой пересборке, если бы
        проверка была привязана к ней. Возьми мы канал логгера, тест был бы
        зелёным и у неверной реализации — по совсем другой причине.
        """
        from multiprocess_framework.modules.process_module.configs.observability_layers import (
            RECIPE_PATH_CONFIG_KEY,
        )

        svc, logger, reload_cmd = _reload_command(tmp_path)
        recipe = _recipe_with_companion(
            tmp_path,
            {"processes": {"refs_probe": {"errors": {"channels": {"errors_fil": {"enabled": False}}}}}},
        )
        try:
            svc.update_config(RECIPE_PATH_CONFIG_KEY, str(recipe))
            reload_cmd({"observability_recipe_reload": True})
            assert len(svc.errors) == 1, svc.errors
            # Ручка оператора: полная пересборка, слой L2 с опечаткой на месте.
            res = reload_cmd({"observability": {"log_level": "DEBUG"}})
            assert res["success"] is True, res
            assert len(svc.errors) == 1, f"опечатка слоя названа повторно на пересборке: {svc.errors}"
        finally:
            logger.shutdown()

    def test_a_named_channel_joins_the_catalogue(self, tmp_path) -> None:
        """Названный однажды канал становится ИЗВЕСТНЫМ — и второй раз молчит.

        Не решение этой задачи, а следствие правила «каталог = реестр ∪ конфиг»
        (``known_refs_from_managers``), и оно одинаково на всех дорогах. Применение
        слоя вливает ``channels.messages_fil`` в конфиг логгера, и на следующей
        перечитке имя уже своё. Записано тестом, потому что иначе выглядит как
        отказ проверки: тот же файл, та же команда, а строки нет.

        Практического ущерба нет — процесс называет опечатку при КАЖДОМ старте
        (у свежего процесса конфиг чист), а именно этой дорогой она и въезжала.
        """
        from multiprocess_framework.modules.process_module.configs.observability_layers import (
            RECIPE_PATH_CONFIG_KEY,
        )

        svc, logger, reload_cmd = _reload_command(tmp_path)
        recipe = _recipe_with_companion(
            tmp_path, {"processes": {"refs_probe": {"channels": {"messages_fil": {"enabled": False}}}}}
        )
        try:
            svc.update_config(RECIPE_PATH_CONFIG_KEY, str(recipe))
            first = reload_cmd({"observability_recipe_reload": True})
            second = reload_cmd({"observability_recipe_reload": True})
            assert first["unknown_refs"] == {"channels": ["messages_fil"]}
            assert "unknown_refs" not in second, second
            assert len(svc.errors) == 1, svc.errors
        finally:
            logger.shutdown()


class TestPersistThenBootRoad:
    """Дорога 3: подхват спутника на boot — та, что увековечивала опечатку.

    Связка целиком: `observability.persist` записал ключ на снятый канал в
    спутник → процесс перезапустился → boot подхватил файл. Ключ законен по форме
    и бессмыслен по существу, а сказать о нём было некому: команды нет, ответа
    нет, оставался только журнал — и он молчал.
    """

    def _proc(self, tmp_path, flat_config):
        from multiprocess_framework.modules.logger_module.configs import LoggerManagerConfig
        from multiprocess_framework.modules.logger_module.core.logger_manager import LoggerManager
        from multiprocess_framework.modules.process_module.core.process_module import ProcessModule

        logger = LoggerManager(
            config=LoggerManagerConfig(app_name="boot_refs", log_directory=str(tmp_path), enable_batching=False)
        )

        class _Handler:
            # Пусто = ассемблер этого процесса не касался → boot раскладывает слои.
            def get_managers_config(self) -> Dict[str, Any]:
                return {}

        class _Proc:
            name = "refs_probe"
            logger_manager = logger
            error_manager = None
            stats_manager = None
            config_handler = _Handler()

            def __init__(self) -> None:
                self.errors: List[str] = []

            def get_config(self, key: str, default: Any = None) -> Any:
                return flat_config.get(key, default)

            def _log_error(self, msg: str, **kw: Any) -> None:
                self.errors.append(str(msg))

            def _log_info(self, msg: str, **kw: Any) -> None:
                pass

            _apply_boot_observability_layers = ProcessModule._apply_boot_observability_layers

        return _Proc(), logger

    def test_persisted_typo_is_loud_on_the_next_boot(self, tmp_path) -> None:
        from multiprocess_framework.modules.process_module.configs.observability_companion import (
            persist_session_to_companion,
        )
        from multiprocess_framework.modules.process_module.configs.observability_layers import (
            RECIPE_PATH_CONFIG_KEY,
        )

        recipe = tmp_path / "line.yaml"
        recipe.write_text("processes: {}\n", encoding="utf-8")
        # Ровно то, что делает `observability.persist`: слой сессии → спутник.
        report = persist_session_to_companion(
            str(recipe),
            "refs_probe",
            {"log_level": "WARNING", "channels": {"messages_fil": {"enabled": False}}},
        )
        assert report["success"] is True, report

        proc, logger = self._proc(tmp_path, {RECIPE_PATH_CONFIG_KEY: str(recipe)})
        try:
            proc._apply_boot_observability_layers()
            assert any("messages_fil" in line for line in proc.errors), proc.errors
            assert logger.config.default_level == "WARNING", "законная часть спутника не применилась"
        finally:
            logger.shutdown()

    def test_clean_companion_boots_silently(self, tmp_path) -> None:
        """Вторая половина: спутник без опечатки поднимает процесс молча."""
        from multiprocess_framework.modules.process_module.configs.observability_companion import (
            persist_session_to_companion,
        )
        from multiprocess_framework.modules.process_module.configs.observability_layers import (
            RECIPE_PATH_CONFIG_KEY,
        )

        recipe = tmp_path / "line.yaml"
        recipe.write_text("processes: {}\n", encoding="utf-8")
        persist_session_to_companion(str(recipe), "refs_probe", {"log_level": "WARNING"})

        proc, logger = self._proc(tmp_path, {RECIPE_PATH_CONFIG_KEY: str(recipe)})
        try:
            proc._apply_boot_observability_layers()
            assert proc.errors == [], proc.errors
            assert logger.config.default_level == "WARNING"
        finally:
            logger.shutdown()


class TestEmptyCatalogueIsSilent:
    """Hazard: сравнение с пустым каталогом объявило бы сиротой каждое имя.

    Каталога нет у процесса, которому менеджеров не собирали вовсе — встройщик
    фреймворка вправе так сделать (тот же случай, что стережёт `layers_are_silent`).
    Самый громкий из возможных способов не сказать ничего.
    """

    def test_process_without_managers_reports_nothing(self) -> None:
        from multiprocess_framework.modules.process_module.configs.observability_refs import unknown_refs_for

        class _Bare:
            name = "bare"
            logger_manager = None
            error_manager = None
            stats_manager = None

        assert unknown_refs_for(_Bare(), {"channels": {"messages_fil": {"enabled": False}}}) == {}
