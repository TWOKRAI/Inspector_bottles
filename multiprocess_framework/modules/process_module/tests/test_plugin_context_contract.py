# -*- coding: utf-8 -*-
"""Задача 4.2 (Н-6, Н-9): контекст плагина несёт ВЕСЬ протокол, дорога документов судится.

Два дефекта одного класса — «объявлено в контракте, отсутствует в реализации», и оба
жили потому, что оракулом служил рукописный список:

* **Н-6.** ``SubPluginContext`` нёс ``log_info``/``log_error`` — два метода из пяти.
  Тот же дефект уже чинили в ``PluginContext`` (A2/Б-2), но починка на одной развилке
  не покрыла соседнюю: вложенный плагин, звавший ``ctx.log_warning`` в ветке штатной
  деградации, получал ``AttributeError`` и падал.
* **Н-9.** ``PluginContext.write_document`` читает сток с сервисов
  (``getattr(services, DOCUMENT_SINK_ATTR)``), а ``IProcessServices`` о нём не знал, и
  дубль сервисов стока не имел. Дорога вердикта существовала в коде и отсутствовала в
  контракте: пройти её в тесте плагина было нечем, отказать — тем более.

**Оракул здесь — сам протокол**, а не список в тесте: имена берутся из
``IProcessServices`` через ``inspect``. Рукописная копия разошлась бы с источником точно
так же, как разошлись три списка в трёх местах до A2, — и тест подтверждал бы сам себя.
"""

from __future__ import annotations

import inspect

import pytest

from multiprocess_framework.modules.process_module.managers.observability_wiring import (
    DOCUMENT_SINK_ATTR,
    document_plane_report,
)
from multiprocess_framework.modules.process_module.plugins.base import (
    PluginContext,
    SubPluginContext,
)
from multiprocess_framework.modules.process_module.plugins.interfaces import IProcessServices
from multiprocess_framework.modules.process_module.plugins.testing import (
    MockDocumentSink,
    MockProcessServices,
)


def _protocol_members() -> set[str]:
    """Публичные имена, объявленные протоколом ``IProcessServices`` — из него самого."""
    return {name for name, _ in inspect.getmembers(IProcessServices) if not name.startswith("_")}


def _log_methods() -> set[str]:
    """Пятёрка ``log_*`` — тоже из протокола, а не перечислением."""
    return {name for name in _protocol_members() if name.startswith("log_")}


# ==============================================================================
# Оракул не должен быть вакуумным
# ==============================================================================


class TestTheOracleItself:
    def test_the_protocol_lists_all_five_log_methods(self) -> None:
        """Пять — не четыре и не два. Сломанный разбор протокола обязан краснеть здесь."""
        assert _log_methods() == {"log_debug", "log_info", "log_warning", "log_error", "log_critical"}

    def test_the_oracle_is_wider_than_logging(self) -> None:
        """Оракул шире ``log_*`` — иначе он сторожил бы одну грань контракта из многих.

        Именно узость прежней проверки (только логирование) оставила дорогу документов
        несудимой: она была за пределами того, на что смотрел оракул.
        """
        beyond_logs = _protocol_members() - _log_methods()
        # ``stats_manager`` (этап 6, 1.1) — здесь по тому же доводу, что и сток:
        # порт, который читает фасад, обязан быть в протоколе, иначе дорога
        # существует в коде и отсутствует в контракте. Сама дорога судится в
        # ``test_plugin_stats_road.py``; здесь — только ширина оракула.
        assert {
            "send_message",
            "receive_message",
            "get_config",
            DOCUMENT_SINK_ATTR,
            "stats_manager",
        } <= beyond_logs

    def test_the_protocol_names_the_sink_exactly_as_the_code_reads_it(self) -> None:
        """Имя стока в протоколе совпадает с константой, по которой его читает фасад.

        Два рукописных упоминания одного имени разъезжаются молча: объявление осталось
        бы, а ``write_document`` читал бы другой атрибут — и путь снова стал бы несудим
        при зелёном контракт-тесте.
        """
        assert DOCUMENT_SINK_ATTR in _protocol_members()


# ==============================================================================
# Н-6: суб-контекст несёт весь протокол
# ==============================================================================


class TestTheSubContextCarriesTheProtocol:
    @pytest.mark.parametrize("method", sorted(_log_methods()))
    def test_every_log_method_exists_and_is_callable(self, method: str) -> None:
        """Каждый объявленный протоколом ``log_*`` есть у суб-контекста и вызывается.

        Проверяется ВЫЗОВ, а не ``hasattr``: поле, оставленное значением ``None``,
        прошло бы проверку существования и упало бы у вызывающего.
        """
        sub = SubPluginContext()
        fn = getattr(sub, method, None)
        assert callable(fn), f"суб-контекст не несёт {method} — вложенный плагин упадёт AttributeError"
        fn("проверка вызова")

    def test_the_parent_context_carries_them_too(self) -> None:
        """Пара к предыдущему: у родителя пятёрка тоже полная (A2 не откатили)."""
        ctx = PluginContext(services=MockProcessServices(), config={})
        for method in _log_methods():
            assert callable(getattr(ctx, method, None)), f"PluginContext потерял {method}"

    def test_a_forwarded_log_reaches_the_parent(self) -> None:
        """Проброшенный из родителя метод действительно пишет туда же.

        Наличие поля — половина контракта; вторая половина в том, что запись
        вложенного плагина не исчезает по дороге.
        """
        services = MockProcessServices()
        parent = PluginContext(services=services, config={}, plugin_name="parent")
        sub = SubPluginContext(log_warning=parent.log_warning)

        sub.log_warning("деградация, но не отказ")

        assert any(entry["msg"] == "деградация, но не отказ" for entry in services.logs)

    def test_from_parent_forwards_every_log_road(self) -> None:
        """``from_parent`` пробрасывает ВСЮ пятёрку — список берётся из протокола.

        Поле у суб-контекста и проброс родителем — разные половины: с полями, но без
        проброса, ``log_warning`` вложенного плагина уходил бы в no-op. Это тише
        прежнего ``AttributeError`` и потому хуже: падение ищут, бесшумную потерю нет.
        """
        services = MockProcessServices()
        parent = PluginContext(services=services, config={}, plugin_name="parent")
        sub = SubPluginContext.from_parent(parent, config={"nested": True})

        assert sub.config == {"nested": True}
        for method in sorted(_log_methods()):
            getattr(sub, method)(f"запись через {method}")
        said = {entry["msg"] for entry in services.logs}
        for method in _log_methods():
            assert f"запись через {method}" in said, f"{method} не доехал до родителя"

    def test_from_parent_forwards_the_document_road(self) -> None:
        """И дорогу документов — иначе вердикт вложенного плагина исчезал бы молча."""
        sink = MockDocumentSink()
        parent = PluginContext(services=MockProcessServices(document_sink=sink), config={}, plugin_name="parent")

        assert SubPluginContext.from_parent(parent).write_document("verdict", "из вложенного") is True
        assert sink.documents[0]["summary"] == "из вложенного"

    def test_the_default_log_is_silent_but_not_missing(self) -> None:
        """Без родителя вызов безопасен: no-op, а не исключение.

        У вложенного контекста своего логгера нет по построению — и это законно.
        Незаконно другое: уронить плагин на попытке сказать.
        """
        assert SubPluginContext().log_critical("некому слушать") is None


# ==============================================================================
# Н-9: дорога документов судится — и проходится, и отказывает
# ==============================================================================


class TestTheDocumentRoadIsJudged:
    def test_the_fake_satisfies_the_protocol_with_the_sink_declared(self) -> None:
        """Дубль остаётся годным по протоколу — вместе с новым объявлением стока."""
        assert isinstance(MockProcessServices(), IProcessServices)
        assert hasattr(MockProcessServices(), DOCUMENT_SINK_ATTR)

    def test_a_real_process_satisfies_the_protocol_too(self) -> None:
        """Не только дубль: НАСТОЯЩИЙ ``ProcessModule`` тоже удовлетворяет протоколу.

        Проверка на одном дубле доказала бы дубль. Сток публикуется на процессе только
        когда плоскость настроена, поэтому процесс без секции ``observability.documents``
        атрибута не имел вовсе — и объявление стока в протоколе сделало бы штатную
        конфигурацию НЕ удовлетворяющей контракту. Держит это атрибут класса со значением
        ``None``; снимут его — покраснеет здесь, а не в проде на dev-проверке.
        """
        from multiprocess_framework.modules.process_module.core.process_module import ProcessModule

        process = ProcessModule(name="contract_probe")
        assert hasattr(process, DOCUMENT_SINK_ATTR), "у процесса без плоскости нет даже имени стока"
        assert getattr(process, DOCUMENT_SINK_ATTR) is None, "плоскость не поднята — сток обязан быть None"
        assert isinstance(process, IProcessServices)

    def test_a_document_reaches_the_sink(self) -> None:
        """Прямой путь: вердикт доезжает, конверт собран."""
        sink = MockDocumentSink()
        ctx = PluginContext(services=MockProcessServices(document_sink=sink), config={}, plugin_name="checker")

        assert ctx.write_document("verdict", "деталь бракована", defect="скол") is True
        assert len(sink.documents) == 1
        document = sink.documents[0]
        assert document["kind"] == "verdict"
        assert document["summary"] == "деталь бракована"
        assert document["source"] == "checker"
        assert document["defect"] == "скол"

    def test_the_fake_can_refuse_and_the_refusal_is_visible(self) -> None:
        """Дубль умеет отказать, и отказ виден И вызывающему, И отчёту плоскости.

        Дубль-всегда-успех сделал бы этот путь непроверяемым: «записано» и «сток
        отказал» выглядели бы одинаково, а различает их именно возврат ``False``.
        """
        sink = MockDocumentSink(refuse=True)
        services = MockProcessServices(document_sink=sink)
        ctx = PluginContext(services=services, config={}, plugin_name="checker")

        assert ctx.write_document("verdict", "деталь бракована") is False
        assert sink.dropped == 1
        assert sink.documents == []
        report = document_plane_report(services)["documents"]
        assert report["declared"] is True, "плоскость объявлена — отказ не должен читаться как её отсутствие"
        assert report["dropped"] == 1

    def test_a_storage_failure_does_not_take_the_line_down(self) -> None:
        """Исключение стока стоит документа, а не линии — и названо ПРИЧИНОЙ.

        Ищется текст самого сбоя, а не слово «documents»: первая редакция этой проверки
        грепала подстроку ``documents`` и оставалась зелёной, когда стока не было вовсе,
        — сообщение про ненастроенную плоскость содержит адрес ключа
        ``observability.documents``. Тест проходил по чужой ветке. Найдено инъекцией
        «дубль сервисов снова без стока»: она обязана была уронить эту проверку и не
        уронила.
        """
        sink = MockDocumentSink(raises=RuntimeError("диск отвалился"))
        services = MockProcessServices(document_sink=sink)
        ctx = PluginContext(services=services, config={}, plugin_name="checker")

        assert ctx.write_document("verdict", "деталь бракована") is False
        said = [entry for entry in services.logs if "диск отвалился" in entry["msg"]]
        assert said, f"причина сбоя не названа ни одной записью: {services.logs}"
        assert said[0]["level"] == "ERROR", f"сбой хранилища сказан уровнем {said[0]['level']}"

    def test_no_sink_is_a_named_state_not_a_silent_one(self) -> None:
        """Плоскость не настроена — законно, но не безмолвно: счётчик растёт."""
        services = MockProcessServices()  # document_sink=None — как процесс без секции
        ctx = PluginContext(services=services, config={}, plugin_name="checker")

        assert ctx.write_document("verdict", "деталь бракована") is False
        report = document_plane_report(services)["documents"]
        assert report["declared"] is False
        assert report["without_sink"] == 1

    def test_the_sub_context_can_carry_the_parent_road(self) -> None:
        """Вложенный плагин пишет вердикт через проброшенную дорогу родителя."""
        sink = MockDocumentSink()
        parent = PluginContext(services=MockProcessServices(document_sink=sink), config={}, plugin_name="parent")
        sub = SubPluginContext(write_document=parent.write_document)

        assert sub.write_document("verdict", "из вложенного") is True
        assert sink.documents[0]["summary"] == "из вложенного"

    def test_without_a_parent_the_sub_context_refuses_in_the_same_shape(self) -> None:
        """Без родителя — ``False``, та же форма ответа, что у процесса без плоскости.

        Вторая форма отказа заставила бы плагин знать, в каком контексте он живёт.
        """
        assert SubPluginContext().write_document("verdict", "некуда") is False
