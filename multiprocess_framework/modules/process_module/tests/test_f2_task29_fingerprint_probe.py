# -*- coding: utf-8 -*-
"""Добор ревью Task 2.9 — зонд отпечатка: имя вердикта не зависит от того,
совпало ли значение запроса со схемным дефолтом.

Автор — реализатор (внутренний hazard-тест механизма). Соседи по свойству, но
другими объективами:

* ``test_f2_task29_verifier_covers_every_leaf.py`` — независимый тестер, 52 листа
  перечислены руками, ``effective`` пустой;
* ``test_f2_task29_schema_coverage_guard.py`` — обход схемы против РЕАЛЬНОЙ
  проводки (``_real_wired``) и НЕДЕФОЛТНЫХ значений;
* этот файл — те же 52 листа, поданные СО СВОИМ ДЕФОЛТОМ. Дефолт здесь не
  небрежность, а ПРЕДМЕТ: ровно на нём ломался прежний зонд (он сравнивал
  раскладку запроса с раскладкой пустого запроса, и «значение равно дефолту»
  было для него неотличимо от «ключ не просили»). Замер до починки: 7 листьев
  пропадали из вердикта молча, 24 получали в ``unverifiable`` сырое схемное имя,
  которого readback не отдаёт никогда.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

import pytest

from multiprocess_framework.modules.data_schema_module import SchemaBase
from multiprocess_framework.modules.process_module.configs.observability_config import (
    ObservabilityConfig,
)
from multiprocess_framework.modules.process_module.managers.observability_reload import (
    observability_verified,
)


def _schema_leaf_paths(model_cls: type) -> List[Tuple[str, ...]]:
    """Листовые пути схемы — та же ``SchemaBase``-рекурсия, что у стражей 2.2/2.9.

    Копия правила, а не импорт приватной функции механизма: страж, спрашивающий
    у предмета, где у предмета листья, согласится с любым ответом предмета.
    """
    out: List[Tuple[str, ...]] = []
    for name, field in model_cls.model_fields.items():
        ann = field.annotation
        if isinstance(ann, type) and issubclass(ann, SchemaBase):
            out.extend((name, *rest) for rest in _schema_leaf_paths(ann))
        else:
            out.append((name,))
    return out


def _default_at(path: Tuple[str, ...]) -> Any:
    node: Any = ObservabilityConfig()
    for part in path:
        node = getattr(node, part)
    return node.model_dump() if isinstance(node, SchemaBase) else node


def _nest(path: Tuple[str, ...], value: Any) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    node = out
    for part in path[:-1]:
        node[part] = {}
        node = node[part]
    node[path[-1]] = value
    return out


#: ИМЯ, под которым вердикт обязан назвать каждый лист схемы, поданный со СВОИМ
#: ДЕФОЛТОМ при пустом ``effective``. Литерал целиком (снят одним прогоном и
#: разобран построчно), а не вычисление из механизма: набор, посчитанный тем же
#: зондом, который он сторожит, согласился бы с любым ответом зонда — включая
#: «ничего».
#:
#: Читать таблицу так — три класса имён, и различать их обязательно:
#:
#: 1. **Имя РАСКЛАДКИ** (``logger.retention_days``, ``error.default_level``,
#:    ``stats.enable_logging``, ``command.log_success``) — лист потреблён
#:    экспандером, и вердикт называет тот путь manager-конфига, которым лист
#:    управляет. Именно здесь ломался прежний зонд: при значении, равном
#:    дефолту, он клал сюда СЫРОЕ схемное имя (``retention_days``), которого
#:    readback не отдаёт, — то есть выдавал оператору имя, неотличимое от
#:    честного ``documents.factory``, но заведомо непроверяемое.
#: 2. **Схемное имя секции своего механизма** (``events.*``, ``flight.*``,
#:    ``voices.*``, ``history.*``, ``observation.*``, ``documents.*``,
#:    ``session_ttl_sec``, ``heartbeat_interval_sec``) — экспандер их не
#:    смотрит вовсе, у readback'а путь конфига и путь ответа совпадают один в
#:    один. Схемное имя здесь и есть правильное.
#: 3. **Схемное имя как ПОСЛЕДНИЙ РУБЕЖ** — девять листьев, у которых схемный
#:    дефолт есть ровно то значение, при котором экспандер МОЛЧИТ и отдаёт
#:    решение дефолту ниже: ``log_directory`` (``None``), ``console``/``file``
#:    (``true`` — при обоих включённых ``channels`` не эмитятся вовсе),
#:    ``channels``/``scopes``/``loggers``/``logger_groups``/``errors.channels``/
#:    ``stats.channels`` (``{}`` — секции раскладываются только непустыми).
#:    Проверяемого пути такой запрос не даёт, и это не дефект зонда, а свойство
#:    экспандера. Вердикт называет ключ ОПЕРАТОРА: промолчать нельзя (ответ на
#:    непустой запрос совпал бы с ответом на ``{}``), а назвать путь раскладки
#:    нечем — у ``console: true`` их 56 (весь граф каналов), у ``channels: {}``
#:    единственный кандидат ВЫДУМАН самим зондом. Это признанный предел, а не
#:    подтверждение: см. докстринг ``observability_verified``.
_NAMED_AT_ITS_OWN_DEFAULT: Dict[Tuple[str, ...], List[str]] = {
    ("log_level",): ["logger.default_level"],
    ("log_directory",): ["log_directory"],
    ("console",): ["console"],
    ("file",): ["file"],
    ("channels",): ["channels"],
    ("scopes",): ["scopes"],
    ("loggers",): ["loggers"],
    ("logger_groups",): ["logger_groups"],
    ("session_ttl_sec",): ["session_ttl_sec"],
    ("heartbeat_interval_sec",): ["heartbeat_interval_sec"],
    ("retention_days",): ["logger.retention_days"],
    ("retention_total_mb",): ["logger.retention_total_mb"],
    ("compress_rotated",): ["logger.compress_rotated"],
    ("retention_sweep_interval_sec",): ["logger.retention_sweep_interval_sec"],
    ("sampling_first_n",): ["logger.sampling_first_n"],
    ("sampling_every_mth",): ["logger.sampling_every_mth"],
    ("sampling_burst_reset_sec",): ["logger.sampling_burst_reset_sec"],
    ("sampling_max_level",): ["logger.sampling_max_level"],
    # У `enabled` СВОЕГО пути в раскладке нет: ключ решает, существует ли секция
    # `error` целиком. Поэтому он назван обоими путями, которые материализует, —
    # это и есть то, чем он управляет.
    # Переключатель, ГАСЯЩИЙ секцию раскладки целиком, называет СЕБЯ, а не её
    # содержимое. Прежде здесь стояли `error.default_level` и
    # `error.include_stacktrace` — пути, которых оператор не писал; на живом
    # стенде это давало ложный `failed`, требующий схемный дефолт от настройки,
    # выставленной самим оператором секундой раньше (находка А-1 ревью,
    # итерация 2). Рез отпечатка по пересечению полюсов оставил здесь одно имя.
    ("errors", "enabled"): ["errors.enabled"],
    ("errors", "level"): ["error.default_level"],
    ("errors", "include_stacktrace"): ["error.include_stacktrace"],
    ("errors", "channels"): ["errors.channels"],
    ("stats", "enabled"): ["stats.enabled"],
    ("stats", "log_snapshots"): ["stats.enable_logging"],
    ("stats", "aggregation_interval"): ["stats.aggregation_interval"],
    ("stats", "flush_interval"): ["stats.flush_interval"],
    ("stats", "log_level"): ["stats.log_level"],
    ("stats", "log_line_max_bytes"): ["stats.log_line_max_bytes"],
    ("stats", "max_series"): ["stats.max_series"],
    ("stats", "channels"): ["stats.channels"],
    ("commands", "log_success"): ["command.log_success"],
    ("documents", "factory"): ["documents.factory"],
    ("documents", "config"): ["documents.config"],
    ("events", "first_n"): ["events.first_n"],
    ("events", "every_mth"): ["events.every_mth"],
    ("flight", "enabled"): ["flight.enabled"],
    ("flight", "sink"): ["flight.sink"],
    ("flight", "keep"): ["flight.keep"],
    ("flight", "limit"): ["flight.limit"],
    ("observation", "subtree_enabled"): ["observation.subtree_enabled"],
    ("observation", "subtree_interval_sec"): ["observation.subtree_interval_sec"],
    ("observation", "rules"): ["observation.rules"],
    ("voices", "default_window_sec"): ["voices.default_window_sec"],
    ("voices", "escalate_after_repeats"): ["voices.escalate_after_repeats"],
    ("voices", "max_tracked_keys"): ["voices.max_tracked_keys"],
    ("voices", "stale_windows"): ["voices.stale_windows"],
    ("history", "enabled"): ["history.enabled"],
    ("history", "level"): ["history.level"],
    ("history", "max_rows"): ["history.max_rows"],
    ("history", "max_age_sec"): ["history.max_age_sec"],
    ("history", "purge_interval_sec"): ["history.purge_interval_sec"],
    ("history", "db_path"): ["history.db_path"],
}

_LEAF_PATHS = _schema_leaf_paths(ObservabilityConfig)


class TestEveryLeafIsNamedWhenItsValueEqualsTheSchemaDefault:
    """Критерий 4 добора: лист, поданный со СВОИМ дефолтом, назван — и назван верно."""

    def test_the_table_covers_the_whole_schema(self) -> None:
        """Появилось поле схемы — таблица обязана вырасти вместе с ним.

        Без этой сверки новый лист просто не попал бы в параметризацию, и
        свойство «каждый лист назван» держалось бы на 52 листьях из 53.
        """
        assert sorted(_LEAF_PATHS) == sorted(_NAMED_AT_ITS_OWN_DEFAULT), (
            "листья схемы и таблица имён разошлись: "
            f"нет в таблице {sorted(set(_LEAF_PATHS) - set(_NAMED_AT_ITS_OWN_DEFAULT))}, "
            f"лишние в таблице {sorted(set(_NAMED_AT_ITS_OWN_DEFAULT) - set(_LEAF_PATHS))}"
        )

    @pytest.mark.parametrize("path", _LEAF_PATHS, ids=[".".join(p) for p in _LEAF_PATHS])
    def test_leaf_at_its_default_is_named_exactly(self, path: Tuple[str, ...]) -> None:
        request = _nest(path, _default_at(path))

        verdict = observability_verified(request, {})

        leaf = ".".join(path)
        # Сильное заявление ПЕРВЫМ: не «список непуст», а «назван ИМЕННО тот
        # путь». Слабая половина («не нигде») сама по себе зелена и у вердикта,
        # который назовёт любую ерунду.
        assert verdict["unverifiable"] == _NAMED_AT_ITS_OWN_DEFAULT[path], (
            f"{leaf}: подан со своим дефолтом, а назван как {verdict['unverifiable']} — "
            f"ожидалось {_NAMED_AT_ITS_OWN_DEFAULT[path]}"
        )
        assert verdict["checked"] == 0, f"{leaf}: пустой readback не может ничего сверить: {verdict}"

    @pytest.mark.parametrize("path", _LEAF_PATHS, ids=[".".join(p) for p in _LEAF_PATHS])
    def test_a_non_empty_request_never_answers_like_an_empty_one(self, path: Tuple[str, ...]) -> None:
        """Инвариант шага 2 ТЗ, названный своими словами.

        Дефект M1 выглядел ровно так: ``observability_verified({"heartbeat_interval_sec":
        1.0}, eff)`` и ``observability_verified({}, eff)`` возвращали ПОБАЙТНО
        одно и то же — оператор не мог отличить «применил и не сумел проверить»
        от «не понял, о чём вы». Заявление здесь сильнее, чем у соседнего теста:
        то сторожит имя, это — саму различимость.
        """
        empty = observability_verified({}, {})

        answer = observability_verified(_nest(path, _default_at(path)), {})

        assert answer != empty, f"{'.'.join(path)}: ответ на непустой запрос совпал с ответом на пустой: {answer}"


class TestDefaultValuedRequestIsVerifiedAgainstTheReadback:
    """Д2 ревью: ``stats.enabled: true`` подтверждается, а не молчит.

    До починки ключ подтверждался только В ОДНУ СТОРОНУ — выключение да,
    включение нет, — потому что верхний цикл пропускал путь по правилу
    «``baseline`` этого пути не менял», где ``baseline`` — СХЕМНЫЕ ДЕФОЛТЫ, а не
    действующее состояние.
    """

    def test_enabled_true_against_a_live_true_is_confirmed(self) -> None:
        verdict = observability_verified({"stats": {"enabled": True}}, {"stats": {"enabled": True}})

        assert verdict["verdict"] == "confirmed", verdict
        assert verdict["checked"] == 1, verdict
        assert verdict["unverifiable"] == [], verdict

    def test_enabled_true_against_a_live_false_is_a_named_mismatch(self) -> None:
        verdict = observability_verified({"stats": {"enabled": True}}, {"stats": {"enabled": False}})

        assert verdict["verdict"] == "failed", verdict
        assert verdict["mismatches"] == [{"key": "stats.enabled", "expected": True, "actual": False}], verdict


class TestNoFalseNameWhenTheRequestRepeatsTheDefault:
    """Д1 ревью: три ключа, которые readback ЗНАЕТ, не смеют попасть в ``unverifiable``.

    Регрессия была внесена вместе с зондом первой редакции: ``console: true``
    совпадает со схемным дефолтом, изолированная раскладка выходила неотличимой
    от раскладки пустого запроса, и зонд объявлял секцию непотреблённой, положив
    в ``expected`` сырой схемный путь. Ложное имя тут хуже отсутствующего:
    отличить его от честного ``documents.factory`` оператору нечем.
    """

    READBACK = {
        "logger": {"channels": {"console": {"enabled": True}}, "retention_days": 9},
        "command": {"log_success": False},
    }
    REQUEST = {"console": True, "file": True, "retention_days": 9, "commands": {"log_success": False}}

    def test_no_leaf_the_readback_answers_is_named_unverifiable(self) -> None:
        """Д1 в исходной форме: ключ, чей путь раскладки readback ОТДАЁТ, назван быть не смеет.

        Значения намеренно НЕ дефолтные — иначе экспандер молчит и проверять
        нечего (это отдельный контракт, тест ниже). Здесь оба ключа
        материализуются, оба находятся в readback'е, и `unverifiable` обязан
        быть пуст.
        """
        readback = {"logger": {"retention_days": 9}, "command": {"log_success": False}}
        verdict = observability_verified({"retention_days": 9, "commands": {"log_success": False}}, readback)

        assert verdict["unverifiable"] == [], (
            f"названы непроверяемыми пути, которые readback отдаёт: {verdict['unverifiable']}"
        )
        # ЛИТЕРАЛ, а не len(): пустой `unverifiable` достижим и у слепого вердикта
        # (ровно это и был дефект M1). Сверены `retention_days` →
        # `logger.retention_days` и `commands.log_success` → `command.log_success`.
        assert verdict["checked"] == 2, verdict
        assert verdict["verdict"] == "confirmed", verdict

    def test_a_leaf_at_its_own_default_is_named_not_swallowed(self) -> None:
        """Контракт для листа, чью раскладку экспандер при ЭТОМ значении не эмитит.

        `console: true` — схемный дефолт, и при нём экспандер каналы не строит
        вовсе: сверять нечего НИ ПОД КАКИМ именем. Два выхода — промолчать или
        назвать. Выбрано назвать, и вот почему: молчание и есть тот отказ, ради
        которого делалась Task 2.9 (M1 — «ключ не упомянут» читается оператором
        как «всё в порядке»). Имя `console` в `unverifiable` не лжёт: вердикт
        действительно НЕ проверил этот путь. Цена — шум на запросе, который
        ничего не меняет; она названа в `docs/claude/OPEN_QUESTIONS.md`.

        Второй ассерт — про НЕЗАВИСИМОСТЬ ОТ СОСЕДЕЙ. Первая редакция называла
        лист «последним рубежом» только при полностью пустом `expected`, и один и
        тот же `console: true` назывался в одиночку и молчал рядом с проверяемым
        ключом. Свойство принадлежит листу, а не запросу.
        """
        alone = observability_verified({"console": True}, self.READBACK)
        assert alone["unverifiable"] == ["console"], alone

        with_neighbour = observability_verified(self.REQUEST, self.READBACK)
        assert with_neighbour["unverifiable"] == ["console", "file"], with_neighbour
        assert with_neighbour["checked"] == 2, with_neighbour
        assert with_neighbour["verdict"] == "confirmed", with_neighbour

    def test_a_toggle_that_materialises_a_whole_table_is_named_by_its_own_name(self) -> None:
        """``console: false`` МАТЕРИАЛИЗУЕТ стол каналов — и потому не сверяется.

        Прежняя редакция теста требовала обратного: сверки
        ``logger.channels.console.enabled`` и запрета имени ``console``. Одна
        сверка там действительно была — в комплекте с **56 именами** остального
        стола в ``unverifiable`` (на базе ``f84817cf`` — 47: шум предсуществующий,
        зонд добавил девять) и с риском ложного ``failed``, воспроизведённым
        ревью живьём на соседнем ключе ``errors.enabled``.

        Причина у обоих одна: отпечаток брался по ОБЪЕДИНЕНИЮ путей двух полюсов,
        то есть включал пути, различающиеся лишь НАЛИЧИЕМ. Переключатель, гасящий
        или зажигающий целую секцию раскладки, забирал в отпечаток всю её, а
        значения соседям доставались из схемных дефолтов — вердикт требовал
        дефолт от настройки, которую оператор выставил сам.

        После реза по ПЕРЕСЕЧЕНИЮ вердикт говорит про ``console`` то же, что про
        остальные восемь листьев такого рода: «не проверил», под именем, которое
        написал оператор. Это слабее сверки и честнее её: проверку, которую нельзя
        отличить от вранья, отличить от вранья нельзя. Настоящую дорогу этим
        ключам даст реестр описателей ручек (Task 4.9).
        """
        verdict = observability_verified({"console": False}, self.READBACK)

        assert verdict["unverifiable"] == ["console"], verdict
        assert verdict["mismatches"] == [], verdict
        assert verdict["checked"] == 0, verdict


class TestASectionSwitchDoesNotAccuseItsNeighbours:
    """Находка А-1 ревью (итерация 2), воспроизведённая на ЖИВОМ стенде.

    Сценарий оператора в два шага: сперва он выставил уровень и стектрейс, затем
    спросил про ОДИН ключ — ``errors.enabled``. Вердикт отвечал ``failed`` и
    называл ``error.default_level`` и ``error.include_stacktrace`` — ключи,
    которых оператор в этом запросе не писал, — требуя от них СХЕМНЫЙ ДЕФОЛТ
    поверх значений, выставленных им же секундой раньше. Ложная тревога дороже
    отсутствующей: на неё полагаются.

    Отличие от соседнего класса ниже: там ``effective`` пуст и сравнивать не с
    чем, поэтому ложная тревога не проявлялась. Здесь readback ОТДАЁТ эти пути —
    и ровно эта половина не была рассмотрена ни одним тестом, пока её не нашёл
    живой прогон.
    """

    READBACK = {"error": {"default_level": "ERROR", "include_stacktrace": False}}

    def test_asking_about_the_switch_does_not_fail_on_untouched_neighbours(self) -> None:
        verdict = observability_verified({"errors": {"enabled": True}}, self.READBACK)

        assert verdict["mismatches"] == [], (
            f"вердикт обвинил соседей, которых запрос не трогал: {verdict['mismatches']}"
        )
        assert verdict["verdict"] != "failed", verdict
        assert verdict["unverifiable"] == ["errors.enabled"], verdict
        assert verdict["checked"] == 0, verdict


class TestAnExtinguishedSectionIsNamedBySchemaNotByLayout:
    """Д3 ревью: ``errors.enabled: false`` гасит секцию раскладки целиком.

    ``expand_observability`` отдаёт ``error: {}`` — то есть ``enabled``
    потреблён, а ``level``/``include_stacktrace``/``channels`` исчезают вместе с
    секцией. Прежний вердикт называл оператору ``error`` — ИМЯ, которого нет ни
    в его конфиге (там ``errors``), ни в схеме, ни в readback'е. Пустой словарь
    раскладки — не поле, а погашенная секция, и сравнивать его не с чем.
    """

    def test_both_leaves_are_named_by_their_schema_paths(self) -> None:
        verdict = observability_verified({"errors": {"enabled": False, "level": "ERROR"}}, {})

        assert verdict["unverifiable"] == ["errors.enabled", "errors.level"], verdict
        assert verdict["checked"] == 0, verdict

    def test_the_internal_section_name_is_absent_from_the_answer(self) -> None:
        verdict = observability_verified({"errors": {"enabled": False, "level": "ERROR"}}, {})

        assert "error" not in verdict["unverifiable"], (
            f"вердикт назвал внутреннее имя раскладки вместо ключа оператора: {verdict}"
        )


class TestTheProbeDoesNotSpeakForTheOperator:
    """Зонд подставляет ВТОРОЙ ПОЛЮС значения — и не смеет этим шуметь.

    У ``stats`` стоит ``model_validator(mode="before")``, который на ``enabled:
    false`` пишет оператору предупреждение «метрики не будут собираться вовсе»
    (ADR-PM-046). Собери зонд второй полюс словарём и прогони через
    ``model_validate`` — и оператор, попросивший ``enabled: true``, получил бы в
    журнале голос о ВЫКЛЮЧЕННОЙ плоскости. Ложный голос дороже отсутствующего:
    его читают. Отсюда ``model_copy`` в ``_with_leaf``.
    """

    def test_asking_to_enable_the_plane_logs_no_warning_about_disabling_it(self, caplog: Any) -> None:
        import logging

        with caplog.at_level(logging.WARNING, logger="observability_config"):
            observability_verified({"stats": {"enabled": True}}, {"stats": {"enabled": True}})

        assert caplog.records == [], f"зонд заговорил за оператора: {[r.getMessage()[:80] for r in caplog.records]}"

    def test_the_operators_own_disabling_still_speaks(self, caplog: Any) -> None:
        """Контроль к тесту выше: голос НА МЕСТЕ, когда оператор правда гасит плоскость.

        Без этой половины тест выше зелен и у механизма, который заглушил
        предупреждение целиком, — то есть доказывал бы ровно противоположное
        задуманному.
        """
        import logging

        with caplog.at_level(logging.WARNING, logger="observability_config"):
            observability_verified({"stats": {"enabled": False}}, {"stats": {"enabled": False}})

        assert any("stats.enabled" in r.getMessage() for r in caplog.records), (
            f"предупреждение ADR-PM-046 пропало вовсе: {[r.getMessage()[:80] for r in caplog.records]}"
        )
