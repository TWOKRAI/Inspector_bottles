# -*- coding: utf-8 -*-
"""Сторожа блокера 2 и major 4 ревью Task 1.4 — дорога ручки ``observability.voices``.

Находка ревью, воспроизведённая тремя независимыми заплатками:

* ``wire_voices_policy`` → ``return None`` — **0 красных** из 350;
* ``voices_applied = apply_voices_policy(...)`` → ``None`` — **0 красных** из 350;
* грепом: ни одна из двух функций не упоминалась НИ В ОДНОМ тесте дерева.

И вердикт был слеп: ``config_reload_verified`` на секции ``voices`` отвечал
``{"verdict": "unverifiable", "checked": 0}`` — ручка не попадала даже в список
непроверяемого, исчезая из вердикта целиком. Класс дефекта названный в памяти
проекта: ``unverifiable`` при ``checked=0`` означает «никто не смотрел», а
читается как «проверено».

**Это дословный повтор блокера Б2 ревью Ф4** (там же — ``events``), и до него
Ф5 закрывала то же самое у ``flight``. Поэтому здесь не только сторожа самой
секции, но и сторож ПЕРЕЧНЯ (``IDENTITY_SECTION_KEYS``): он краснеет на
следующей под-секции схемы, которую забудут назвать, — то есть до ревью.

Файл отдельный, а не дописка к сторожам механизма
(``logger_module/tests/test_windowed_voice_*``): там свойства самого окна, здесь
— проводка «конфиг → живой механизм → readback → вердикт». Смешав их, через
месяц нельзя ответить, что именно нашло ревью.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Iterator

import pytest

from multiprocess_framework.modules.data_schema_module import SchemaBase
from multiprocess_framework.modules.logger_module.core.logger_manager import LoggerManager
from multiprocess_framework.modules.logger_module.core.windowed_voice import (
    default_window_sec,
    escalate_after_repeats,
    reset_voices_policy,
)
from multiprocess_framework.modules.process_module.configs.observability_config import (
    ObservabilityConfig,
    expand_observability,
)
from multiprocess_framework.modules.process_module.configs.observability_layers import flatten_section
from multiprocess_framework.modules.process_module.core.process_module import ProcessModule
from multiprocess_framework.modules.process_module.managers.observability_reload import (
    IDENTITY_SECTION_KEYS,
    observability_effective,
    observability_verified,
)
from multiprocess_framework.modules.process_module.managers.observability_wiring import (
    VOICES_SECTION_KEY,
    apply_voices_policy,
)

from .test_observation_policy_review_f4 import _wired

#: Литералы запроса — намеренно «некруглые» и НЕ совпадающие ни с одним
#: дефолтом схемы (5.0 / 3). Совпади они — тест проходил бы и у версии, которая
#: не применяет ничего.
WINDOW = 17.25
ESCALATE = 9

#: Н-2 (добор ревью Ф2, ``review-phase-1.md``): те же значения, что в
#: ``test_f2_task27_voices_reload_response_gap.py`` (``CAP``/``STALE``) — СПЕЦИАЛЬНО
#: не равны схемным дефолтам (512/10). Заплата, приколотившая ответ константой
#: 512/10, раньше проходила незамеченной именно потому, что запрос эти поля не
#: называл и ответ падал на дефолт — правда и ложь совпадали.
CAP = 2048
STALE = 7


@pytest.fixture(autouse=True)
def _isolated_policy() -> Iterator[None]:
    """Политика ПРОЦЕССНАЯ: без сброса тесты видели бы след соседа."""
    reset_voices_policy()
    yield
    reset_voices_policy()


def _logger_config(tmp_path: Path) -> Dict[str, Any]:
    return {
        "app_name": "voices_road",
        "log_directory": str(tmp_path),
        "modules": {},
        "channels": {"a": {"type": "file", "enabled": True, "file_path": "a.log"}},
        "scopes": {scope: {"channels": ["a"]} for scope in ("SYSTEM", "BUSINESS", "DEBUG")},
    }


def _boot(tmp_path: Path, app_layer: Dict[str, Any]):
    """Боевой подъём наблюдаемости процесса: ``_wire_observability_hub`` целиком.

    Не прямой вызов ``wire_voices_policy``: заплатка ревью снимала именно ЕГО,
    и сторож обязан идти той же дорогой, что процесс на старте, — иначе он
    доказывал бы функцию, а не её включённость в сшивку.
    """
    proc = ProcessModule("inspector", config={"observability_app": app_layer} if app_layer else {})
    logger = LoggerManager(manager_name="VoicesRoadProbe", config=_logger_config(tmp_path), process=proc)
    logger.initialize()
    proc.logger_manager = logger
    proc.register_manager("logger", logger, enabled=True)
    proc._wire_observability_hub()
    return proc, logger


# =========================================================================== #
# Точка 1 — СТАРТ процесса
# =========================================================================== #
class TestBootWiringReachesTheLiveMechanism:
    """``wire_voices_policy`` доносит секцию до механизма, а не только до слоя."""

    def test_the_section_from_the_app_layer_becomes_the_live_policy(self, tmp_path: Path) -> None:
        _, logger = _boot(
            tmp_path,
            {"voices": {"default_window_sec": WINDOW, "escalate_after_repeats": ESCALATE}},
        )
        try:
            live_window, live_escalate = default_window_sec(), escalate_after_repeats()
        finally:
            logger.shutdown()

        assert (live_window, live_escalate) == (WINDOW, ESCALATE), (
            f"секция легла в слой и не доехала до механизма: окно {live_window}, порог {live_escalate}"
        )

    def test_a_process_without_the_section_keeps_the_builtin_default(self, tmp_path: Path) -> None:
        """Пара-контроль: молчание слоя НЕ материализуется и не ломает дефолт.

        Без этой половины предыдущий тест проходил бы и у версии, которая
        ставит 17.25 откуда угодно. Литералы 5.0/3 — встроенные дефолты,
        пришпилены здесь отдельно от схемы.
        """
        _, logger = _boot(tmp_path, {})
        try:
            live = (default_window_sec(), escalate_after_repeats())
        finally:
            logger.shutdown()

        assert live == (5.0, 3), f"процесс без секции обязан остаться на встроенном дефолте: {live}"


# =========================================================================== #
# Точка 2 — ПЕРЕСБОРКА + имена ключей (major 4)
# =========================================================================== #
class TestRebuildReachesTheLiveMechanism:
    def test_apply_changes_the_live_policy(self) -> None:
        applied = apply_voices_policy({"default_window_sec": WINDOW, "escalate_after_repeats": ESCALATE})

        assert applied is not None, "секция подана — применение обязано состояться"
        assert (default_window_sec(), escalate_after_repeats()) == (WINDOW, ESCALATE)

    def test_a_silent_section_does_not_reset_what_was_set(self) -> None:
        """Правило Г3: слой, который ничего не сказал, ничего и не решает."""
        apply_voices_policy({"default_window_sec": WINDOW, "escalate_after_repeats": ESCALATE})

        assert apply_voices_policy(None) is None
        assert (default_window_sec(), escalate_after_repeats()) == (WINDOW, ESCALATE), (
            "молчание секции стёрло заданное окно"
        )

    def test_the_answer_uses_schema_field_names(self) -> None:
        """Major 4: readback переименовывал ключ, и round-trip сбрасывал окно.

        Воспроизведение ревью:

            apply(...)                 -> {'window_sec': 17.25, ...}
            apply(своим же readback)   -> {'window_sec': 5.0,   ...}

        ``ObservabilityVoicesConfig`` с ``extra=ignore`` съедала незнакомое имя
        молча; вторая ось выживала только потому, что её имя совпало.
        """
        applied = apply_voices_policy({"default_window_sec": WINDOW, "escalate_after_repeats": ESCALATE})

        # Task 2.7: секция не назвала max_tracked_keys/stale_windows — обе оси
        # получают СХЕМНЫЕ дефолты (512/10), та же дорога, что уже была у
        # window_sec/escalate_after до этой задачи.
        assert applied == {
            "default_window_sec": WINDOW,
            "escalate_after_repeats": ESCALATE,
            "max_tracked_keys": 512,
            "stale_windows": 10,
        }, f"имена ключей ответа обязаны быть именами полей СХЕМЫ: {applied}"
        assert set(applied) <= set(ObservabilityConfig().voices.model_dump()), (
            f"в ответе есть ключ, которого нет в схеме секции: {sorted(applied)}"
        )

    def test_feeding_the_answer_back_is_idempotent(self) -> None:
        """Round-trip — то, чем пользуются и оператор, и вердикт."""
        applied = apply_voices_policy({"default_window_sec": WINDOW, "escalate_after_repeats": ESCALATE})

        again = apply_voices_policy(applied)

        assert again == applied, f"подача собственного ответа обратно изменила его: {applied} -> {again}"
        assert default_window_sec() == WINDOW, f"round-trip молча сбросил окно в дефолт: {default_window_sec()}"


# =========================================================================== #
# Точка 3 — READBACK и ВЕРДИКТ
# =========================================================================== #
class TestTheVerdictSeesTheSection:
    REQUEST = {"observability": {"voices": {"default_window_sec": WINDOW, "escalate_after_repeats": ESCALATE}}}

    @staticmethod
    def _verdict(section: Dict[str, Any]) -> Dict[str, Any]:
        return observability_verified(section, observability_effective())

    def test_readback_carries_the_live_policy_under_schema_paths(self) -> None:
        apply_voices_policy({"default_window_sec": WINDOW, "escalate_after_repeats": ESCALATE})

        effective = observability_effective()

        # Task 2.7: readback безусловный (как и раньше) и теперь несёт ещё два
        # поля секции — на схемных дефолтах, потому что запрос их не называл.
        assert effective[VOICES_SECTION_KEY] == {
            "default_window_sec": WINDOW,
            "escalate_after_repeats": ESCALATE,
            "max_tracked_keys": 512,
            "stale_windows": 10,
        }, effective.get(VOICES_SECTION_KEY)

    def test_an_applied_knob_is_confirmed_not_unverifiable(self) -> None:
        section = self.REQUEST["observability"]
        apply_voices_policy(section["voices"])

        verdict = self._verdict(section)

        assert verdict["verdict"] == "confirmed", verdict
        # 2 — литерал: обе оси секции проверены. Ноль здесь и был находкой.
        assert verdict["checked"] == 2, verdict
        assert verdict["unverifiable"] == [], verdict

    def test_a_knob_that_did_not_reach_the_mechanism_is_named_a_mismatch(self) -> None:
        """Пара-контроль: вердикт не всеяден.

        Без неё «confirmed» проходило бы и у сверщика, который согласен со всем.
        Здесь запрос ПОДАН, но не применён — механизм стоит на дефолте.
        """
        verdict = self._verdict(self.REQUEST["observability"])

        assert verdict["verdict"] == "failed", verdict
        assert verdict["checked"] == 2, verdict
        assert {m["key"] for m in verdict["mismatches"]} == {
            "voices.default_window_sec",
            "voices.escalate_after_repeats",
        }, verdict

    def test_a_typo_in_the_section_is_still_an_unknown_key(self) -> None:
        """Контроль схемы: опечатка обязана остаться опечаткой, а не «подтвердиться»."""
        verdict = self._verdict({"voices": {"defalt_window_sec": WINDOW}})

        assert verdict["unknown_keys"] == ["voices.defalt_window_sec"], verdict
        assert verdict["verdict"] == "failed", verdict


# =========================================================================== #
# Точка 4 — ОТВЕТ КОМАНДЫ
# =========================================================================== #
class TestTheCommandAnswerCarriesVoicesApplied:
    """Применённое считалось и выбрасывалось — за пределами тестов его не читал никто.

    Сторож читает ОТВЕТ ``config.reload``, а не внутренний ``expanded``: сторож,
    смотрящий во внутренний словарь, доказывает харнесс (урок блокера Б2 Ф4,
    дословно тот же).
    """

    def test_voices_applied_is_a_key_of_the_answer(self, tmp_path: Path) -> None:
        """Н-2 (добор ревью Ф2): запрос НАЗЫВАЕТ ``max_tracked_keys``/``stale_windows``
        значениями, отличными от схемных дефолтов (512/10) — иначе заплата,
        приколотившая ответ той же константой, что и дефолт, проходит незамеченной
        (0 красных из 2526 у ревьюера).
        """
        _, handlers = _wired(tmp_path)

        res = handlers["config.reload"](
            {
                "observability": {
                    "voices": {
                        "default_window_sec": WINDOW,
                        "escalate_after_repeats": ESCALATE,
                        "max_tracked_keys": CAP,
                        "stale_windows": STALE,
                    }
                }
            }
        )

        assert res["success"] is True, res
        assert "voices_applied" in res, sorted(res)
        assert res["voices_applied"] == {
            "default_window_sec": WINDOW,
            "escalate_after_repeats": ESCALATE,
            "max_tracked_keys": CAP,
            "stale_windows": STALE,
        }, res["voices_applied"]

    def test_the_same_answer_confirms_the_knob(self, tmp_path: Path) -> None:
        """Вторая половина: команда не только отчитывается, но и подтверждает.

        ``unverifiable`` при ``checked=0`` — то, что стенд отдавал до починки.
        """
        _, handlers = _wired(tmp_path)

        res = handlers["config.reload"](
            {"observability": {"voices": {"default_window_sec": WINDOW, "escalate_after_repeats": ESCALATE}}}
        )

        verified = res["verified"]
        assert verified["verdict"] == "confirmed", verified
        assert verified["checked"] >= 2, verified
        assert res["effective"]["voices"]["default_window_sec"] == WINDOW, res["effective"].get("voices")


# =========================================================================== #
# Класс дефекта — ПЕРЕЧЕНЬ, а не одна секция
# =========================================================================== #
class TestIdentitySectionsCoverEveryUnexpandedSubsection:
    """Сторож против ЧЕТВЁРТОГО повтора одного и того же блокера.

    ``events`` (Ф4), ``flight`` (Ф5), ``voices`` (Task 1.4) — трижды ревью
    находило одну дыру и трижды её закрывали дописыванием одной строки. Здесь
    перечень сверяется со СХЕМОЙ: новая под-секция обязана быть осознанно
    отнесена к одной из трёх корзин, иначе тест краснеет.
    """

    #: Под-секции, которые ``expand_observability`` РАСКЛАДЫВАЕТ в конфиги
    #: менеджеров: их пути readback'а приходят оттуда, тождественное
    #: соответствие им не нужно.
    EXPANDED = {"errors", "stats", "commands"}

    #: Осознанные исключения — каждое со своей причиной:
    #: * ``documents`` — адрес второй плоскости (фабрика + её словарь), readback
    #:   её не отдаёт и отдавать не должен (словарь принадлежит корню композиции);
    #: * ``observation`` — ключи-globs с точками, нормализация ОБОИХ берегов у
    #:   неё своя (``normalized_observation_section``), строковое тождество ей
    #:   не годится.
    EXEMPT = {"documents", "observation"}

    def test_every_subsection_of_the_schema_is_classified(self) -> None:
        subsections = {
            name
            for name, field in ObservabilityConfig.model_fields.items()
            if isinstance(field.annotation, type) and issubclass(field.annotation, SchemaBase)
        }

        assert subsections == set(IDENTITY_SECTION_KEYS) | self.EXPANDED | self.EXEMPT, (
            "у схемы появилась под-секция, не отнесённая ни к одной корзине. "
            "Молчания вердикта это САМО ПО СЕБЕ уже не вызывает — с задачи 2.9 "
            "'потреблена ли секция экспандером' решает зонд, и новая секция "
            "будет названа без правки этого перечня. Красное здесь означает "
            "другое и не менее важное: никто не ЗАПИСАЛ, почему секция обходит "
            "экспандер (или почему не обходит), то есть решение принято молча. "
            f"Секции схемы: {sorted(subsections)}"
        )

    def test_identity_sections_really_bypass_the_expander(self) -> None:
        """Проверяемое основание корзины, а не только её состав.

        Секция попадает в ``IDENTITY_SECTION_KEYS`` ровно потому, что
        ``expand_observability`` про неё ничего не кладёт: иначе путь readback'а
        пришёл бы оттуда и тождественное соответствие дублировало бы его.
        """
        baseline = flatten_section(expand_observability({}))

        for key in IDENTITY_SECTION_KEYS:
            leaking = [path for path in baseline if path.startswith(f"{key}.")]
            assert not leaking, (
                f"секция '{key}' раскладывается экспандером ({leaking}) — тождественное соответствие ей не нужно"
            )
