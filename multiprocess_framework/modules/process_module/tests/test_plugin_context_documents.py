# -*- coding: utf-8 -*-
"""Ф8.7 — ``PluginContext.write_document``: дорога приложения в плоскость документов.

Это тесты АВТОРА на опасные места самого механизма (правило проекта «три роли
авторства тестов»). Независимый tester в этом заходе не вызывался — субагенты в
сессии выключены; компенсация — слом-инъекция под каждое заявленное свойство, набор
объявлен до запуска (см. врезку Task 8.7 в плане).

Опасные места, ради которых файл существует:

1. **Конверт против прикладного поля.** Род документа задаёт срок хранения. Прикладное
   поле с именем ``kind`` не имеет права увести вердикт в чужой род — иначе срок
   становится функцией случайного совпадения имён. Тот же дефект уже ловили у аудита
   (m-4 ревью Ф8), здесь он воспроизводим на второй дороге.
2. **Ненастроенная плоскость ≠ сбой.** Процесс без ключа ``observability.documents``
   обязан отвечать ``False`` молча и дёшево. Исключение или лог на каждый вызов
   превратили бы законное состояние в шум.
3. **Отказ стока не роняет линию, но и не молчит.** Сток бросил — вызывающий получает
   ``False``, а причина уходит в журнал: потерянный вердикт без следа — ровно класс
   «проглоченный сбой», ради которого плоскость и заводилась.
4. **Вложенный контекст.** ``SubPluginContext`` совместим по duck-typing; забудь мы у
   него ``write_document`` — sub-плагин упал бы с ``AttributeError`` в момент вынесения
   вердикта, то есть на самом дорогом пути.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List

import pytest

from multiprocess_framework.modules.process_module.plugins.base import (
    PluginContext,
    SubPluginContext,
)


class _RecordingSink:
    """Сток, который запоминает документы. Умеет отказывать — обоими способами."""

    def __init__(self, *, refuse: bool = False, raises: bool = False) -> None:
        self.documents: List[Dict[str, Any]] = []
        self._refuse = refuse
        self._raises = raises

    def append(self, document: Dict[str, Any]) -> bool:
        if self._raises:
            raise RuntimeError("БД недоступна")
        self.documents.append(document)
        return not self._refuse


class _Services:
    """Процесс в объёме, который читает ``PluginContext``.

    Не ``MagicMock``: фальшивка, у которой есть ЛЮБОЙ атрибут, ответила бы стоком и
    там, где его нет, — «фальшивка-всегда-успех глушит гейт».
    """

    def __init__(self, name: str = "inspector", sink: Any = None) -> None:
        self.name = name
        self.errors: List[str] = []
        if sink is not None:
            self.document_sink = sink

    # A2: пятёрка целиком — фасад штампует все пять, и дубль обязан их иметь.
    def log_debug(self, message: str, **kwargs: Any) -> None:
        pass

    def log_info(self, message: str, **kwargs: Any) -> None:
        pass

    def log_warning(self, message: str, **kwargs: Any) -> None:
        pass

    def log_error(self, message: str, **kwargs: Any) -> None:
        self.errors.append(message)

    def log_critical(self, message: str, **kwargs: Any) -> None:
        self.errors.append(message)


def _ctx(services: _Services, plugin_name: str | None = "robot_control") -> PluginContext:
    return PluginContext(services=services, plugin_name=plugin_name)


class TestEnvelopeWinsOverPayload:
    def test_payload_field_named_kind_does_not_steal_the_document_kind(self) -> None:
        """Прикладной ``kind`` уезжает в payload, род остаётся тем, что попросили."""
        sink = _RecordingSink()
        ctx = _ctx(_Services(sink=sink))

        assert ctx.write_document("verdict", "брак", kind="audit") is True

        assert sink.documents[0]["kind"] == "verdict"

    def test_payload_field_named_summary_does_not_replace_the_summary(self) -> None:
        """Второе поле конверта — так же: суть ставит вызывающий, не нагрузка."""
        sink = _RecordingSink()
        ctx = _ctx(_Services(sink=sink))

        ctx.write_document("verdict", "настоящая суть", **{"summary": "подделка"})

        assert sink.documents[0]["summary"] == "настоящая суть"

    def test_whole_payload_dict_can_be_splatted_without_a_typeerror(self) -> None:
        """Ради чего ``kind``/``summary`` сделаны позиционными.

        Прикладной словарь неизвестного состава — обычный способ звать эту дорогу.
        Обычные параметры дали бы «got multiple values» на ключе ``kind``, то есть
        вердикт терялся бы ИСКЛЮЧЕНИЕМ на линии — хуже подмены, от которой ставилась
        защита выше.
        """
        sink = _RecordingSink()
        payload = {"kind": "audit", "summary": "подделка", "action": "reject", "area": 1600}

        assert _ctx(_Services(sink=sink)).write_document("verdict", "брак", **payload) is True

        doc = sink.documents[0]
        assert (doc["kind"], doc["summary"]) == ("verdict", "брак")
        assert doc["action"] == "reject", "прикладная часть при этом не потеряна"

    def test_garbage_ts_costs_the_document_not_the_line(self) -> None:
        """Мусор в ``ts`` приходит от приложения; исключение из-за него не имеет
        права выйти наружу — сборка конверта поэтому внутри try."""
        services = _Services(sink=_RecordingSink())

        assert _ctx(services).write_document("verdict", "брак", ts="позавчера") is False

        assert len(services.errors) == 1 and "ValueError" in services.errors[0]


class TestSourceNamesTheWriter:
    def test_plugin_name_is_the_default_source(self) -> None:
        sink = _RecordingSink()
        assert _ctx(_Services(sink=sink)).write_document("verdict") is True
        assert sink.documents[0]["source"] == "robot_control"

    def test_process_name_is_used_when_the_context_is_not_a_plugin_copy(self) -> None:
        """Базовый ctx имени плагина не имеет — тогда источник это процесс, а не пустота."""
        sink = _RecordingSink()
        _ctx(_Services(name="inspector", sink=sink), plugin_name=None).write_document("verdict")
        assert sink.documents[0]["source"] == "inspector"

    def test_explicit_source_wins(self) -> None:
        sink = _RecordingSink()
        _ctx(_Services(sink=sink)).write_document("verdict", source="line_2/post_3")
        assert sink.documents[0]["source"] == "line_2/post_3"


class TestClockIsADependency:
    def test_default_ts_is_now(self) -> None:
        sink = _RecordingSink()
        before = time.time()
        _ctx(_Services(sink=sink)).write_document("verdict")
        assert before <= sink.documents[0]["ts"] <= time.time()

    def test_explicit_ts_is_taken_verbatim(self) -> None:
        """Параметр, а не патч ``time``: иначе тест правил бы часы всего процесса."""
        sink = _RecordingSink()
        _ctx(_Services(sink=sink)).write_document("verdict", ts=123.5)
        assert sink.documents[0]["ts"] == 123.5


class TestPlaneAbsentIsNotAFailure:
    def test_process_without_the_plane_answers_false_quietly(self) -> None:
        services = _Services()  # атрибута document_sink нет вовсе
        assert _ctx(services).write_document("verdict", "брак") is False
        assert services.errors == [], "ненастроенная плоскость — законное состояние, не отказ"

    def test_sink_without_append_is_refused_and_not_called(self) -> None:
        """Объект есть, метода нет — структурная проверка, а не ``isinstance`` протокола
        (импорт протокола означал бы импорт ``Services`` во фреймворк)."""
        services = _Services(sink=object())
        assert _ctx(services).write_document("verdict") is False


class TestFailureIsLoudButNotFatal:
    def test_raising_sink_does_not_escape_to_the_line(self) -> None:
        services = _Services(sink=_RecordingSink(raises=True))
        assert _ctx(services).write_document("verdict", "брак") is False

    def test_raising_sink_is_named_in_the_journal(self) -> None:
        services = _Services(sink=_RecordingSink(raises=True))
        _ctx(services).write_document("verdict", "брак")
        assert len(services.errors) == 1
        assert "verdict" in services.errors[0] and "RuntimeError" in services.errors[0]

    def test_refusing_sink_returns_false_without_a_second_complaint(self) -> None:
        """``append`` вернул ``False`` — отказ уже посчитан стоком (``dropped``).
        Вторая жалоба здесь удвоила бы учёт одной потери."""
        services = _Services(sink=_RecordingSink(refuse=True))
        assert _ctx(services).write_document("verdict") is False
        assert services.errors == []


class TestSubPluginContext:
    def test_default_refuses_instead_of_raising(self) -> None:
        """Своей плоскости у вложенного контекста нет — но и ``AttributeError`` быть не должно."""
        assert SubPluginContext().write_document("verdict", "брак") is False

    def test_parent_can_hand_its_road_down(self) -> None:
        sink = _RecordingSink()
        parent = _ctx(_Services(sink=sink))

        sub = SubPluginContext(write_document=parent.write_document)
        assert sub.write_document("verdict", "брак от вложенного") is True

        assert sink.documents[0]["summary"] == "брак от вложенного"


@pytest.mark.parametrize("kind", ["verdict", "audit", "любой_новый_род"])
def test_kind_is_a_free_string_not_a_closed_enum(kind: str) -> None:
    """Третий род не должен требовать правки фреймворка — иначе плоскость снова
    станет реестром, который чинят кодом (ровно то, что схлопнула Ф8.1)."""
    sink = _RecordingSink()
    assert _ctx(_Services(sink=sink)).write_document(kind) is True
    assert sink.documents[0]["kind"] == kind
