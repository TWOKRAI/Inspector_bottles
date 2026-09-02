# -*- coding: utf-8 -*-
"""Ф2, задача 2.2 — каждый ключ ``observability`` объявлен схемой, читается кодом
и подтверждается верификатором; ключа «принимается и ничего не делает» нет.

НЕЗАВИСИМЫЙ приёмочный набор (стадия 1, до реализации). Источник — акцептанс
задачи 2.2 (``plans/observability-closure/phase-2-one-policy.md``), а не
implementation-файлы: диффа и `_impl` тестер не видел.

Пять свойств, по одному классу на класс теста:

1. ``history`` — под-секция СХЕМЫ (не сырой dict), и правка ``history.level``
   через операторскую дверь (``config.reload`` inline / L3) принимается, а не
   отвергается как незнакомый ключ.
2. ``errors.enabled`` не молчит: либо гасит создание ``ErrorManager``
   (``expand_observability`` эмитит пустой/явно-выключенный ``error``-словарь),
   либо ключ снят из схемы с громкой жалобой на старый конфиг. Тест держит
   ИМЕННО эту дизъюнкцию, а не одну из двух реализаций.
3. Readback называет поле ``logger_groups`` (не ``groups``), и верификатор
   видит ``session_ttl_sec`` / ``retention_*`` / ``compress_rotated`` /
   ``channels.*.enabled`` / ``commands.log_success`` — не отвечает по ним
   молчанием и не путает «не проверено» с «подтверждено».
4. Страж: каждое ЛИСТОВОЕ поле схемы ``ObservabilityConfig`` (кроме подсекций
   со своим отдельным живым механизмом — ``documents``/``events``/``flight``/
   ``observation``/``voices``, и кроме ``heartbeat_interval_sec``, читаемого
   строковым ключом, а не атрибутом) обязано быть найдено АТРИБУТНЫМ чтением
   (``cfg.<section>.<field>``) хотя бы в одном из файлов проводки наблюдаемости.
5. Полная секция (без спорных ``history``/``errors.enabled`` — см. п.1/2) через
   ``config.reload`` инлайн даёт ``verified.unverifiable == []``.

Два харнесса, оба гоняют НАСТОЯЩИЙ хендлер ``config.reload``, разница — в том,
что у него ЖИВОЕ, а не в том, реальный он или нет:

* ``_wired`` (импорт из ``test_observation_policy_review_f4.py``, им же
  пользуется ``test_voices_policy_road_guards.py``) — процесс с настоящим
  ``ProcessHeartbeat`` и живым гейтом порта наблюдений, но ``logger_manager``
  там — ``_FakeLogger`` БЕЗ атрибута ``.config`` (``test_telemetry_commands.py``).
  Проверено зондом: ``observability_effective(logger=_FakeLogger(), ...)`` берёт
  ветку ``if logger is not None and getattr(logger, "config", None) is not None``
  — она НЕ исполняется, и ``effective["logger"]`` в этом харнессе не появляется
  вовсе. Годится для полей, не завязанных на логгер/ошибки (``session_ttl_sec``,
  правка секции ``history`` — обе живут в слое, не в менеджере).
* ``_real_wired`` (заведён в этом файле) — НАСТОЯЩИЙ ``LoggerManager`` +
  НАСТОЯЩИЙ ``ErrorManager`` + НАСТОЯЩИЙ ``CommandManager``, тот же приём, что
  ``test_sink_command_real_wiring.py`` (докстринг там: «фейковый харнесс даёт
  зелёный на мёртвой команде в проде» — тот же урок применён здесь: readback
  логгера/ошибок без настоящего менеджера доказывает харнесс, а не проводку).
  Вход — ``command_manager.handle_command({"command": ..., "data": ...})``,
  ПРОДовый вход IPC, а не выдуманный ``dispatch``.

Значения в запросах — ЛИТЕРАЛЫ, намеренно отличные от схемных дефолтов
(правило проекта: совпадение с дефолтом маскирует «ничего не применилось»).
"""

from __future__ import annotations

import ast
import contextlib
import shutil
import tempfile
from pathlib import Path
from typing import Any, Dict, Iterator, Tuple

import pytest

from multiprocess_framework.modules.command_module import CommandManager
from multiprocess_framework.modules.data_schema_module import SchemaBase
from multiprocess_framework.modules.error_module import ErrorManager, ErrorManagerConfig
from multiprocess_framework.modules.logger_module.core.logger_manager import LoggerManager
from multiprocess_framework.modules.logger_module.configs.logger_manager_config import (
    LoggerManagerConfig,
)
from multiprocess_framework.modules.process_module.commands.builtin_commands import BuiltinCommands
from multiprocess_framework.modules.process_module.configs.observability_config import (
    ObservabilityConfig,
    expand_observability,
)
from multiprocess_framework.modules.process_module.core.process_module import ProcessModule

from .test_observation_policy_review_f4 import _wired

#: Корень ``process_module`` — от расположения ЭТОГО файла (``tests/`` — прямой
#: потомок), а не абсолютным литералом: жёсткий путь ломается при переносе/копии
#: worktree, а вычисленный — нет.
PROCESS_MODULE_ROOT = Path(__file__).resolve().parent.parent


@contextlib.contextmanager
def _real_wired(tag: str) -> Iterator[Tuple[ProcessModule, LoggerManager, ErrorManager, CommandManager]]:
    """Процесс с НАСТОЯЩИМИ LoggerManager/ErrorManager/CommandManager.

    ``@contextmanager``, а не голый генератор под ``for ... in``: тесты этого
    файла КРАСНЫЕ по построению (RED-режим) — ``assert`` падает ВНУТРИ тела
    почти всегда, и без ``with`` очистка (``finally`` ниже) не гарантирована
    синхронно при исключении в теле (генератор закрывается лишь при сборке
    мусора). ``with`` гарантирует ``__exit__`` тем же контрактом, что и любой
    ``try/finally``. ``tag`` — уникальный суффикс каталога логов/имени процесса
    на тест (иначе параллельные файлы разных тестов конфликтуют).
    """
    tmp_dir = Path(tempfile.mkdtemp(prefix=f"f2_t22_{tag}_"))
    process = ProcessModule(f"f2_task22_{tag}")
    logger = LoggerManager(
        manager_name=f"logger_{tag}",
        config=LoggerManagerConfig(app_name=tag, log_directory=str(tmp_dir)),
        process=process,
    )
    logger.initialize()
    process.logger_manager = logger
    process.register_manager("logger", logger, enabled=True)

    error = ErrorManager(
        config=ErrorManagerConfig(
            app_name=f"{tag}_errors",
            critical_file_path=str(tmp_dir / "critical.log"),
            error_file_path=str(tmp_dir / "errors.log"),
            warnings_file_path=str(tmp_dir / "warnings.log"),
        ),
    )
    error.initialize()
    process.error_manager = error
    process.register_manager("error", error, enabled=True)

    command_manager = CommandManager(manager_name=f"cmd_{tag}")
    command_manager.initialize()
    process.command_manager = command_manager

    BuiltinCommands(process)._register_observability_commands()

    try:
        yield process, logger, error, command_manager
    finally:
        command_manager.shutdown()
        error.shutdown()
        logger.shutdown()
        shutil.rmtree(tmp_dir, ignore_errors=True)


def _reload(command_manager: CommandManager, section: Dict[str, Any]) -> Dict[str, Any]:
    """Отправить ``config.reload`` ТЕМ ЖЕ входом, что и IPC — ``handle_command``."""
    return command_manager.handle_command({"command": "config.reload", "data": {"observability": section}})


# =========================================================================== #
# 1 — ``history`` обязана быть под-секцией СХЕМЫ
# =========================================================================== #
class TestHistoryIsASchemaSubsection:
    """Критерий 1: ``history`` — поле ``ObservabilityConfig``, а не сырой dict.

    Сегодня ``resolve_history_policy`` читает секцию по СТРОКОВОМУ пути через
    ``process_observability_layers(svc).resolve().get("history")`` — сырой
    результат наложения слоёв, схема о ключе ``history`` не знает вовсе
    (подтверждено: в ``ObservabilityConfig`` (``configs/observability_config.py``)
    поля ``history`` нет). Следствие видно на операторской границе: слой
    сессии (``config.reload`` inline) сверяет ИМЕНА ключей ТОЛЬКО по схеме
    (``unknown_section_keys`` / ``validate_layer_section``, задача 5.4) — и
    отвергает ``history.level`` как незнакомый.
    """

    def test_the_schema_has_a_history_field_with_the_named_subfields(self) -> None:
        cfg = ObservabilityConfig()
        assert hasattr(cfg, "history"), (
            "ObservabilityConfig не имеет поля 'history' — секция не часть схемы (критерий 1 задачи 2.2)"
        )
        history = cfg.history
        assert isinstance(history, SchemaBase), f"observability.history обязана быть под-схемой, а не {type(history)}"
        for field in ("enabled", "level", "max_rows", "max_age_sec", "purge_interval_sec", "db_path"):
            assert hasattr(history, field), f"observability.history не несёт поле '{field}'"

    def test_the_schema_default_level_is_info_matching_the_named_constant(self) -> None:
        """Дефолт МЕХАНИЗМА (``DEFAULT_HISTORY_LEVEL``) и дефолт СХЕМЫ обязаны
        совпадать — иначе у одной политики два источника правды, и они разойдутся
        на первом же новом релизе.
        """
        from multiprocess_framework.modules.process_module.managers.observability_wiring import (
            DEFAULT_HISTORY_LEVEL,
            DEFAULT_HISTORY_MAX_AGE_SEC,
            DEFAULT_HISTORY_MAX_ROWS,
            DEFAULT_HISTORY_PURGE_INTERVAL_SEC,
        )

        history = ObservabilityConfig().history
        assert history.level == DEFAULT_HISTORY_LEVEL == "INFO", history.level
        assert history.max_rows == DEFAULT_HISTORY_MAX_ROWS, history.max_rows
        assert history.max_age_sec == DEFAULT_HISTORY_MAX_AGE_SEC, history.max_age_sec
        assert history.purge_interval_sec == DEFAULT_HISTORY_PURGE_INTERVAL_SEC, history.purge_interval_sec

    def test_history_level_is_accepted_on_the_operator_door_not_rejected_as_unknown(self, tmp_path: Path) -> None:
        """Живьём (операторская дверь): ``config.reload`` с ``history.level`` обязан
        подтвердиться, а не отвечать «ключей нет в контракте наблюдаемости».

        Сегодня это не так: ``unknown_section_keys`` считает через round-trip по
        ``ObservabilityConfig`` (см. ``configs/observability_layers.py``), и
        ``history`` там не выживает — сессия отказывает ДО записи (задача 5.4).
        """
        _, handlers = _wired(tmp_path)

        res = handlers["config.reload"]({"observability": {"history": {"level": "WARNING"}}})

        assert res["success"] is True, (
            f"history.level отвергнут операторской дверью: {res!r} — "
            "секция 'history' схеме неизвестна (критерий 1 задачи 2.2)"
        )
        verified = res["verified"]
        assert verified["verdict"] == "confirmed", verified


# =========================================================================== #
# 2 — ``errors.enabled`` не имеет права быть тихим no-op
# =========================================================================== #
class TestErrorsEnabledIsNotASilentNoop:
    """Критерий 2: свойство держится ДИЗЪЮНКТИВНО — задача разрешает реализатору
    выбрать один из двух путей (гасить ``ErrorManager`` ИЛИ снять ключ из схемы
    с громким предупреждением, как ``REMOVED_BATCHING_KEYS``). Тест не привязан
    ни к одному из них — он проверяет, что хотя бы ОДИН эффект случился.

    Сегодня — НИ ОДИН: ``errors.enabled`` существует в схеме
    (``ObservabilityErrorsConfig.enabled``, дефолт ``True``), но
    ``expand_observability`` строит ``error``-словарь БЕЗ обращения к
    ``cfg.errors.enabled`` (подтверждено чтением ``configs/observability_config.py``
    строки 834-837 и грепом ``errors\\.enabled`` по всему фреймворку — ноль
    совпадений вне схемы и докстрингов). ``ErrorManager`` создаётся, если
    ``managers_config.get("error", {})`` непусто (``managers/process_managers.py``,
    ``_create_error_manager``) — а он непуст ВСЕГДА, независимо от ``enabled``.
    """

    def test_setting_it_false_either_gates_the_manager_or_gets_a_loud_removal_complaint(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        heard: list = []
        import multiprocess_framework.modules._fallback as fallback_mod

        def _record(name: str, level: str, message: str, *args: Any) -> None:
            heard.append(str(message) % args if args else str(message))

        monkeypatch.setattr(fallback_mod, "emergency_log", _record)

        cfg = ObservabilityConfig.model_validate({"errors": {"enabled": False}})
        expanded = expand_observability(cfg)
        error_dict = expanded["error"]

        # Вариант (а) — гейт создания ErrorManager: словарь пуст (тогда
        # `_create_error_manager` не создаст менеджер, см. `managers_config.get`
        # проверку на непустоту) ИЛИ несёт явный маркер `enabled: False`,
        # который умеет читать `_create_error_manager`.
        gating_variant = (not error_dict) or (error_dict.get("enabled") is False)

        # Вариант (б) — ключ снят из схемы: старый конфиг с `errors.enabled: false`
        # обязан дать ГРОМКУЮ жалобу через `emergency_log` (тот же жест, что
        # `REMOVED_BATCHING_KEYS` / `_complain_about_repurposed_enabled`), а не
        # молча проигнорироваться `extra=ignore`.
        removal_variant = any("enabled" in msg for msg in heard)

        assert gating_variant or removal_variant, (
            f"errors.enabled=False не даёт НИКАКОГО наблюдаемого эффекта: "
            f"error-словарь={error_dict!r}, аварийные предупреждения={heard!r} — "
            "ключ принимается и ничего не делает (критерий 2 задачи 2.2, m4/M7)"
        )

    def test_setting_it_true_stays_the_default_shape_as_a_control(self) -> None:
        """Пара-контроль: дефолт (``enabled: True``, неявный) не должен внезапно
        погасить ``ErrorManager`` — иначе первый тест проходил бы и у поломки,
        которая гасит error-плоскость ВСЕГДА, независимо от ключа.
        """
        expanded = expand_observability({})
        assert expanded["error"], "error-секция обязана быть непустой при дефолтном enabled=True"


# =========================================================================== #
# 3 — Честный readback
# =========================================================================== #
class TestReadbackNamesLoggerGroupsField:
    """Критерий 3 (часть 1): readback обязан звать поле ``logger_groups`` —
    именем СХЕМЫ, а не внутренним ``groups`` (найдено чтением
    ``managers/observability_reload.py:287-289``:
    ``section["groups"] = groups_fn()``).

    Харнесс — ``_real_wired``: у ``_wired`` (test_observation_policy_review_f4)
    ``logger_manager`` — фейк без ``.config``, и ``effective["logger"]`` там не
    появляется вовсе (проверено зондом) — тест на нём был бы KeyError, не
    свойством readback'а.
    """

    def test_the_answer_uses_the_schema_field_name_not_groups(self) -> None:
        with _real_wired("groups") as (process, _logger, _error, cm):
            group_value = {"noisy": ["vision.capture.hikvision"]}

            res = _reload(cm, {"logger_groups": group_value})

            assert res["success"] is True, res
            effective_logger = res["effective"]["logger"]
            assert "logger_groups" in effective_logger, (
                f"readback не несёт ключ 'logger_groups': {sorted(effective_logger)} — "
                "оператор правит секцию логгера СХЕМНЫМ именем, а видит другое"
            )
            assert effective_logger["logger_groups"] == group_value, effective_logger.get("logger_groups")
            assert "groups" not in effective_logger, (
                f"readback ЕЩЁ несёт устаревшее имя 'groups': {sorted(effective_logger)}"
            )


class TestVerifierCoversTheListedPaths:
    """Критерий 3 (часть 2): ``session_ttl_sec`` / ``retention_*`` /
    ``compress_rotated`` / ``channels.*.enabled`` / ``errors.*`` /
    ``commands.log_success`` — через ``config_reload_verified`` обязаны
    подтверждаться, а не отвечать ``unverifiable`` (а по ``session_ttl_sec``
    и ``commands.log_success`` — не исчезать из вердикта МОЛЧА).

    Каждая правка — литерал, ОТЛИЧНЫЙ от схемного дефолта (правило проекта):
    совпадение с дефолтом даёт confirmed и у сломанной реализации.
    """

    def test_session_ttl_sec_is_confirmed_not_silently_dropped(self, tmp_path: Path) -> None:
        """Сегодня ``expand_observability`` НЕ эмитит ``session_ttl_sec`` вовсе
        (см. её докстринг: «сюда НЕ раскладывается сознательно») — значит путь
        никогда не попадает в ``expected`` вердикта, и правка исчезает из ответа
        целиком: не ``mismatch``, не ``unverifiable`` — просто отсутствует.

        Секция не завязана на логгер/ошибки — лёгкий ``_wired`` (heartbeat-only)
        достаточен, проверено зондом (``effective`` без 'logger' не мешает: путь
        живёт в самом слое, не в manager-конфиге).
        """
        _, handlers = _wired(tmp_path)

        res = handlers["config.reload"]({"observability": {"session_ttl_sec": 123.0}})

        assert res["success"] is True, res
        verified = res["verified"]
        assert verified["verdict"] == "confirmed", (
            f"session_ttl_sec подан ОДИН — вердикт {verified!r}: ключ обязан попасть "
            "в readback вердикта, а не пропасть из него молча"
        )
        assert verified["checked"] >= 1, verified
        assert verified["unverifiable"] == [], verified

    def test_retention_and_compression_knobs_are_confirmed(self) -> None:
        with _real_wired("retention") as (process, _logger, _error, cm):
            res = _reload(
                cm,
                {
                    "retention_days": 14,
                    "retention_total_mb": 500,
                    "compress_rotated": True,
                    "retention_sweep_interval_sec": 120.0,
                },
            )

            assert res["success"] is True, res
            verified = res["verified"]
            assert verified["verdict"] == "confirmed", verified
            assert verified["checked"] >= 4, verified
            assert verified["unverifiable"] == [], (
                f"ретеншен/компрессия не покрыты readback'ом: {verified['unverifiable']}"
            )

    def test_a_channel_override_enabled_flag_is_confirmed(self) -> None:
        """``channels.messages_file.enabled`` — адресное переопределение (Task 5.12).

        Сегодня readback логгера отдаёт только ``channels_active`` (список имён) и
        ``sinks_disabled_by_operator`` — ни один путь формы
        ``channels.<имя>.enabled`` в нём не появляется.
        """
        with _real_wired("chan") as (process, _logger, _error, cm):
            res = _reload(cm, {"channels": {"messages_file": {"enabled": False}}})

            assert res["success"] is True, res
            verified = res["verified"]
            assert verified["verdict"] == "confirmed", verified
            assert verified["unverifiable"] == [], (
                f"channels.messages_file.enabled не покрыт readback'ом: {verified['unverifiable']}"
            )

    def test_errors_include_stacktrace_is_confirmed(self) -> None:
        """Пара к ``errors.level`` (тот УЖЕ подтверждается сегодня — контроль ниже):
        ``observability_effective`` для плоскости ошибок отдаёт ТОЛЬКО
        ``default_level`` (``managers/observability_reload.py``, ветка ``error is
        not None``) — ``include_stacktrace`` в readback не попадает вовсе.
        """
        with _real_wired("stacktrace") as (process, _logger, _error, cm):
            res = _reload(cm, {"errors": {"include_stacktrace": False}})

            assert res["success"] is True, res
            verified = res["verified"]
            assert verified["verdict"] == "confirmed", verified
            assert verified["unverifiable"] == [], (
                f"errors.include_stacktrace не покрыт readback'ом: {verified['unverifiable']}"
            )

    def test_errors_level_already_works_as_a_control(self) -> None:
        """Контроль: ``errors.level`` УЖЕ подтверждается сегодня (``error.default_level``
        в readback существует) — без этой пары непонятно, ломает ли гипотетическая
        починка что-то, что и так работало.
        """
        with _real_wired("level_ctrl") as (process, _logger, _error, cm):
            res = _reload(cm, {"errors": {"level": "ERROR"}})

            assert res["success"] is True, res
            verified = res["verified"]
            assert verified["verdict"] == "confirmed", verified
            assert verified["checked"] == 1, verified

    def test_commands_log_success_is_confirmed(self) -> None:
        """``observability_effective`` не принимает получателя для ``command`` вовсе
        (сигнатура: ``logger=None, error=None, stats=None, event_selector=None,
        flight_recorder=None, heartbeat=None`` — параметра ``command`` нет), поэтому
        ``commands.log_success`` не может попасть в readback ни при каком запросе.
        """
        with _real_wired("cmdlog") as (process, _logger, _error, cm):
            res = _reload(cm, {"commands": {"log_success": True}})

            assert res["success"] is True, res
            verified = res["verified"]
            assert verified["verdict"] == "confirmed", verified
            assert verified["unverifiable"] == [], (
                f"commands.log_success не покрыт readback'ом: {verified['unverifiable']}"
            )


# =========================================================================== #
# 4 — Страж: каждое поле схемы обязано иметь читателя
# =========================================================================== #
#: Под-секции со своим ЖИВЫМ механизмом (не ``expand_observability``, свои
#: функции применения с ДРУГИМИ именами переменных получателя — не
#: ``cfg.<section>.<field>``). Подтверждено грепом: ноль атрибутных обращений
#: вида ``.documents.``/``.events.``/``.flight.``/``.observation.``/``.voices.``
#: вне докстрингов и тестов по всему ``process_module``. Тот же список фактически
#: воспроизводит ``IDENTITY_SECTION_KEYS`` + ``EXEMPT`` из
#: ``test_voices_policy_road_guards.py::TestIdentitySectionsCoverEveryUnexpandedSubsection``
#: — независимо посчитан ЗДЕСЬ, чтобы не наследовать чужую ошибку, если она есть.
_SUBSECTIONS_WITH_OWN_MECHANISM = {
    "documents": "адрес второй плоскости, читает wire_document_sink (композиционный корень)",
    "events": "политика отбора широких записей, читает WideEventSelector/apply_event_selector",
    "flight": "политика дампа кольца, читает FlightRecorder/apply_flight_recorder",
    "observation": "glob-правила порта, читает ObservationPolicy/apply_observation_policy",
    "voices": "политика окон голоса, читает windowed_voice/apply_voices_policy",
}

#: Скалярные (не под-секционные) поля, читаемые СТРОКОВЫМ ключом через
#: ``.get(KEY_CONSTANT)``, а не атрибутом ``cfg.<field>`` — подтверждено:
#: ``managers/observability_reload.py`` — ``HEARTBEAT_INTERVAL_KEY = "heartbeat_interval_sec"``
#: + ``resolved.get(HEARTBEAT_INTERVAL_KEY)``, ни одного атрибутного обращения
#: ``.heartbeat_interval_sec`` в файлах проводки.
_TOP_LEVEL_DICT_KEY_READERS = {
    "heartbeat_interval_sec": "читается по HEARTBEAT_INTERVAL_KEY через .get(), не атрибутом cfg.",
}

_WIRING_FILES: Tuple[Path, ...] = (
    PROCESS_MODULE_ROOT / "configs" / "observability_config.py",
    PROCESS_MODULE_ROOT / "managers" / "observability_wiring.py",
    PROCESS_MODULE_ROOT / "managers" / "observability_reload.py",
    PROCESS_MODULE_ROOT / "configs" / "observability_layers.py",
    PROCESS_MODULE_ROOT / "managers" / "observability_flight.py",
    PROCESS_MODULE_ROOT / "heartbeat" / "process_heartbeat.py",
    PROCESS_MODULE_ROOT / "commands" / "builtin_commands.py",
    PROCESS_MODULE_ROOT / "configs" / "observation_policy.py",
    PROCESS_MODULE_ROOT / "core" / "process_module.py",
)


def _attribute_chains_in(files: Tuple[Path, ...]) -> set:
    """Все цепочки атрибутных обращений (``a.b.c`` → ``("a","b","c")``) в файлах.

    ЧИСТО структурное — ``ast.Attribute``, а не текстовый грep: докстринги
    (``ast.Constant``) не порождают ``Attribute``-узлов, поэтому упоминание
    поля в прозе комментария/докстринга не даёт ложного «читается».
    """
    chains: set = set()
    for path in files:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute):
                chain = []
                cur: Any = node
                while isinstance(cur, ast.Attribute):
                    chain.append(cur.attr)
                    cur = cur.value
                chain.reverse()
                chains.add(tuple(chain))
    return chains


def _schema_leaf_paths(model_cls: type) -> list:
    """Листовые пути схемы: под-``SchemaBase`` разворачиваются рекурсивно."""
    out: list = []
    for name, field in model_cls.model_fields.items():
        ann = field.annotation
        if isinstance(ann, type) and issubclass(ann, SchemaBase):
            out.extend((name, *rest) for rest in _schema_leaf_paths(ann))
        else:
            out.append((name,))
    return out


def _is_read(path: Tuple[str, ...], chains: set) -> bool:
    """Путь читается, если он — СУФФИКС какой-то реальной цепочки атрибутов."""
    n = len(path)
    return any(len(chain) >= n and chain[-n:] == path for chain in chains)


def unread_schema_fields(
    model_cls: type,
    files: Tuple[Path, ...],
    *,
    exempt_sections: Dict[str, str] = None,
    exempt_top_level: Dict[str, str] = None,
) -> list:
    """Список путей схемы БЕЗ атрибутного читателя, за вычетом принятых исключений."""
    exempt_sections = exempt_sections or {}
    exempt_top_level = exempt_top_level or {}
    chains = _attribute_chains_in(files)
    unread = []
    for path in _schema_leaf_paths(model_cls):
        if len(path) > 1 and path[0] in exempt_sections:
            continue
        if len(path) == 1 and path[0] in exempt_top_level:
            continue
        if not _is_read(path, chains):
            unread.append(".".join(path))
    return sorted(unread)


class TestEveryReadableSchemaFieldHasAReader:
    """Критерий 4: страж обходит ПОЛЯ схемы (не под-секции целиком, как у соседа
    ``test_voices_policy_road_guards.TestIdentitySectionsCoverEveryUnexpandedSubsection``,
    который сверяет только СОСТАВ под-секций) и требует атрибутного чтения
    (``cfg.<section>.<field>``) в файлах проводки наблюдаемости — либо явного,
    поимённого, документированного исключения.

    Сегодня список ``unread`` — как минимум ``["errors.enabled"]`` (критерий 2 —
    тот же дефект, увиденный другим объективом: сторож обходит СХЕМУ, тест 2
    проверяет ЭФФЕКТ). Если добавление секции ``history`` (критерий 1) НЕ
    сопровождается атрибутным чтением (``cfg.history.<поле>``), её листья тоже
    попадут в ``unread`` — страж сторожит и связь между критериями 1 и 4, не
    только критерий 2 отдельно.
    """

    def test_no_schema_field_is_silently_unread(self) -> None:
        unread = unread_schema_fields(
            ObservabilityConfig,
            _WIRING_FILES,
            exempt_sections=_SUBSECTIONS_WITH_OWN_MECHANISM,
            exempt_top_level=_TOP_LEVEL_DICT_KEY_READERS,
        )

        assert unread == [], (
            f"поля схемы без атрибутного читателя и без принятого исключения: {unread} — "
            "ключ есть, эффекта нет (критерий 4 задачи 2.2, m4/M7)"
        )

    def test_a_field_added_without_a_reader_is_caught_by_name(self, tmp_path: Path) -> None:
        """Инъекция криатерия 3 акцептанса: «добавить в схему поле без читателя →
        страж красный по имени» — воспроизведена локально, без правки боевой схемы.

        Пустой файл-заглушка играет роль «файлов проводки, которые это поле не
        читают ни один»: страж обязан назвать поле поимённо, а не просто упасть.
        """
        phantom_field = "totally_unread_phantom_field_2_2"

        empty_file = tmp_path / "empty_wiring.py"
        empty_file.write_text("# ничего не читает\n", encoding="utf-8")

        # Схема из ОДНОГО поля — проще и надёжнее, чем monkeypatch реальной
        # ObservabilityConfig: страж принимает произвольный model_cls.
        class _OneFieldSchema(SchemaBase):
            totally_unread_phantom_field_2_2: bool = False

        unread = unread_schema_fields(_OneFieldSchema, (empty_file,))

        assert unread == [phantom_field], (
            f"страж обязан назвать добавленное непрочитанное поле ПОИМЁННО, получено: {unread}"
        )


# =========================================================================== #
# 5 — Полная секция без спорных history/errors.enabled → unverifiable == []
# =========================================================================== #
class TestFullSectionRoundTripHasNoUnverifiablePaths:
    """Критерий 5. ``history``/``errors.enabled``/``stats.*`` исключены из этого
    запроса намеренно: первые два спорны по форме реализации (см. классы 1 и 2
    выше) и дали бы отказ/неоднозначность по ДРУГОЙ причине; ``stats.*`` требует
    живого ``StatsManager``, которого ``_real_wired`` не поднимает (плоскость
    статистики — предмет Task 2.1, не этой задачи) — его отсутствие давало бы
    ``unverifiable`` по ПРИЧИНЕ ХАРНЕССА, а не по причине, которую держит этот
    тест. Замаскировать этим свойство пяти ДРУГИХ полей — не цель теста.
    """

    SECTION = {
        "log_level": "DEBUG",
        "session_ttl_sec": 111.0,
        "retention_days": 9,
        "retention_total_mb": 250,
        "compress_rotated": True,
        "retention_sweep_interval_sec": 90.0,
        "logger_groups": {"noisy": ["vision.capture"]},
        "channels": {"messages_file": {"enabled": False}},
        "commands": {"log_success": True},
        "errors": {"include_stacktrace": False},
    }

    def test_unverifiable_is_empty(self) -> None:
        with _real_wired("full") as (process, _logger, _error, cm):
            res = _reload(cm, self.SECTION)

            assert res["success"] is True, res
            verified = res["verified"]
            assert verified["unknown_keys"] == [], verified
            assert verified["mismatches"] == [], verified
            assert verified["unverifiable"] == [], (
                f"полная секция даёт неполный readback: {verified['unverifiable']} — критерий 5 задачи 2.2 не взят"
            )
            assert verified["verdict"] == "confirmed", verified
