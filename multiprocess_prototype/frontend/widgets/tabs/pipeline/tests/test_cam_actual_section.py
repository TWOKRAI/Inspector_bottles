# -*- coding: utf-8 -*-
"""Тесты CamActualSection — блок actual-телеметрии камеры (F.6).

Покрытие:
- show_for биндит 7 путей state store и показывает блок;
- hide_and_unbind / dispose снимают все подписки (баланс bind/unbind = 0);
- смена процесса перепривязывает без утечки (баланс сохраняется);
- разрешение собирается из раздельных width/height через общий _cam_res;
- «FPS (измеренный)» биндится ВНЕ поддерева cam.actual и снимается вместе с прочими;
- без bindings блок не показывается и не падает.

Седьмая строка добавлена Р3.5-15 (поправка владельца 2026-08-17): слот «Кадров/с»
на карточке процесса снят как прикладной в generic-виджете, измеренная частота
переехала сюда — в место, где уже известно, что перед нами камера.
"""

from __future__ import annotations

from typing import Any

import pytest

pytest.importorskip("PySide6")

from multiprocess_prototype.frontend.widgets.tabs.pipeline.inspector.cam_actual_section import (
    CamActualSection,
)


class _FakeBindings:
    """Двойник GuiStateBindings: считает bind/unbind, хранит formatter'ы по пути."""

    def __init__(self) -> None:
        self.bind_count = 0
        self.unbind_count = 0
        self.live = 0
        self.formatters: dict[str, Any] = {}

    def bind(self, path: str, widget: Any, prop: str = "value", *, formatter: Any = None) -> tuple:
        self.bind_count += 1
        self.live += 1
        self.formatters[path] = formatter
        return ("handle", path, self.bind_count)

    def unbind(self, handle: Any) -> None:
        self.unbind_count += 1
        self.live -= 1


def test_show_for_binds_seven_paths(qtbot):
    section = CamActualSection()
    qtbot.addWidget(section)
    b = _FakeBindings()
    section.set_bindings(b)

    section.show_for("camera_0")

    assert b.bind_count == 7
    base = "processes.camera_0.state.cam.actual"
    for suffix in ("fps", "exposure", "gain", "fourcc", "width", "height"):
        assert f"{base}.{suffix}" in b.formatters
    assert not section.isHidden()


def test_measured_fps_binds_outside_the_cam_actual_subtree(qtbot):
    """`capture_fps` — уровень ПРОЦЕССА (ADR-PM-038), а не actual-параметр камеры.

    Уедь он под `base`, путь стал бы `…state.cam.actual.capture_fps` — туда никто
    не пишет, и строка была бы вечным прочерком. Проверяется адрес, а не факт
    вызова: адрес — это всё, чем строка отличается от неработающей.

    Ред. 2026-08-20 (Ф1 «порта наблюдений», Task 1.4): адрес стал ГЛОБОМ —
    метрика уехала в поддерево СВОЕГО писателя (`state.plugins.<писатель>.…`),
    и имя писателя в GUI не зашивается. Плоский адрес обязан ИСЧЕЗНУТЬ, а не
    остаться рядом: две подписки на одну строку — это двойная публикация, ровно
    тот класс, который фаза хоронит.
    """
    section = CamActualSection()
    qtbot.addWidget(section)
    b = _FakeBindings()
    section.set_bindings(b)

    section.show_for("camera_0")

    assert "processes.camera_0.state.plugins.*.capture_fps" in b.formatters
    assert "processes.camera_0.state.capture_fps" not in b.formatters
    assert "processes.camera_0.state.cam.actual.capture_fps" not in b.formatters


def test_measured_fps_keeps_one_decimal(qtbot):
    """12.5 обязаны остаться 12.5, а не «12 fps».

    Соседний форматтер actual-строк округляет до целого (`:.0f`), и переиспользуй
    его эта строка — потерялся бы ровно тот знак, ради которого её и завели
    (сравнить измеренные 12.5 с 25 по драйверу).
    """
    section = CamActualSection()
    qtbot.addWidget(section)
    b = _FakeBindings()
    section.set_bindings(b)
    section.show_for("camera_0")

    fmt = b.formatters["processes.camera_0.state.plugins.*.capture_fps"]
    assert fmt(12.5) == "12.5 fps"
    assert fmt(0.0) == "0.0 fps"


def test_the_two_fps_captions_are_distinguishable(qtbot):
    """Две строки про FPS рядом — подписи обязаны различаться однозначно.

    Иначе задача меняет одну ложь на другую: оператор видит два числа под
    неразличимыми подписями и не знает, какое из них что. Судится по СОДЕРЖИМОМУ
    формы, а не по константе `_ROWS`: константу можно поменять, не тронув форму.
    """
    from PySide6.QtWidgets import QFormLayout, QLabel

    section = CamActualSection()
    qtbot.addWidget(section)
    layout = section.layout()
    assert isinstance(layout, QFormLayout)

    captions = []
    for row in range(layout.rowCount()):
        item = layout.itemAt(row, QFormLayout.ItemRole.LabelRole)
        if item is not None and isinstance(item.widget(), QLabel):
            captions.append(item.widget().text())

    fps_captions = [c for c in captions if "FPS" in c]
    assert len(fps_captions) == 2, captions
    assert len(set(fps_captions)) == 2, f"подписи двух строк FPS совпали: {fps_captions}"


def test_measured_fps_handle_is_released_on_hide_and_dispose(qtbot):
    """Новая подписка попадает в ТОТ ЖЕ `_handles` — иначе это утечка Н-4.

    Утечку видно только на смене ноды: секция скрылась, а хэндл продолжает жить в
    GuiStateBindings и писать в мёртвый QLabel через weakref. Поэтому судится
    балансом (7 навешено → 7 снято), а не «unbind был вызван».
    """
    for teardown in ("hide_and_unbind", "dispose"):
        section = CamActualSection()
        qtbot.addWidget(section)
        b = _FakeBindings()
        section.set_bindings(b)
        section.show_for("camera_0")
        assert b.live == 7, teardown

        getattr(section, teardown)()

        assert b.live == 0, f"{teardown}: подписки пережили teardown"
        assert b.unbind_count == 7, teardown
        assert section._handles == [], teardown


def test_hide_and_unbind_balances(qtbot):
    section = CamActualSection()
    qtbot.addWidget(section)
    b = _FakeBindings()
    section.set_bindings(b)
    section.show_for("camera_0")

    section.hide_and_unbind()

    assert b.unbind_count == b.bind_count
    assert b.live == 0
    assert section._handles == []
    assert section.isHidden()


def test_dispose_balances_and_idempotent(qtbot):
    section = CamActualSection()
    qtbot.addWidget(section)
    b = _FakeBindings()
    section.set_bindings(b)
    section.show_for("camera_0")

    section.dispose()
    assert b.live == 0
    unbound_after_first = b.unbind_count

    section.dispose()  # идемпотентно — лишних unbind нет
    assert b.unbind_count == unbound_after_first


def test_reshow_does_not_leak(qtbot):
    section = CamActualSection()
    qtbot.addWidget(section)
    b = _FakeBindings()
    section.set_bindings(b)

    section.show_for("camera_0")
    section.show_for("camera_1")  # смена процесса: старые сняты, новые навешены

    assert b.live == 7  # только текущие живы
    assert b.unbind_count == 7  # предыдущие 7 сняты
    # Подписка на capture_fps перевешена на НОВЫЙ процесс, а не осталась на старом:
    # она биндится вне `base`, то есть мимо общего префикса — самое вероятное место
    # забыть подстановку имени процесса.
    assert "processes.camera_1.state.plugins.*.capture_fps" in b.formatters


def test_resolution_combines_width_and_height(qtbot):
    section = CamActualSection()
    qtbot.addWidget(section)
    b = _FakeBindings()
    section.set_bindings(b)
    section.show_for("camera_0")

    base = "processes.camera_0.state.cam.actual"
    width_fmt = b.formatters[f"{base}.width"]
    height_fmt = b.formatters[f"{base}.height"]
    width_fmt(1920)
    result = height_fmt(1080)
    assert result == "1920×1080"


def test_no_bindings_is_noop(qtbot):
    section = CamActualSection()
    qtbot.addWidget(section)
    # Без set_bindings — show_for не показывает блок и не падает.
    section.show_for("camera_0")
    assert section.isHidden()
    assert section._handles == []
    section.dispose()  # тоже не падает


# =========================================================================== #
#  Настоящая проводка — против фейк-харнесса выше                              #
#                                                                             #
#  Находка фазового ревью Ф1 (Task 1.5): все тесты этого файла сверяют СТРОКУ  #
#  адреса в `_FakeBindings.formatters`. Переименуй метод у настоящих           #
#  GuiStateBindings или сломай матчер глоба — здесь останется зелено.          #
#  Правило проекта: «фейк-харнесс доказывает харнесс», поэтому один тест       #
#  обязан провести настоящую дельту через настоящий объект до текста метки.    #
# =========================================================================== #


class _FakeBridge:
    """Двойник DataReceiverBridge: отдаёт свой state_callback обратно тесту."""

    def __init__(self) -> None:
        self.state_callback = None

    def set_state_callback(self, cb) -> None:
        self.state_callback = cb


def _real_bindings_section(qtbot):
    """Настоящие GuiStateBindings + настоящая секция. Возвращает (section, feed)."""
    from multiprocess_prototype.frontend.state.bindings import GuiStateBindings

    bridge = _FakeBridge()
    bindings = GuiStateBindings(bridge)
    section = CamActualSection()
    qtbot.addWidget(section)
    section.set_bindings(bindings)
    section.show_for("camera_0")

    def feed(path: str, value):
        bridge.state_callback({"data_type": "state_delta", "path": path, "value": value})

    return section, feed


def test_a_real_delta_reaches_the_measured_fps_label(qtbot):
    """Дельта по пути писателя → текст метки. Наблюдаемый эффект, не адрес.

    Якорь существования в паре с отрицанием: сначала метка пуста (прочерк),
    потом на настоящей дельте становится литералом «12.5 fps». Без первой
    половины тест был бы зелен и у метки, которая с рождения показывает всё
    подряд.
    """
    section, feed = _real_bindings_section(qtbot)
    label = section._labels["capture_fps"]
    before = label.text()

    feed("processes.camera_0.state.plugins.capture.capture_fps", 12.5)

    assert before != "12.5 fps", f"метка показывала результат ДО дельты: {before!r}"
    assert label.text() == "12.5 fps", (
        f"настоящая дельта по пути писателя не доехала до метки: {label.text()!r}. "
        "Фейк-тесты выше этого не увидят — они сверяют строку адреса, а не доставку"
    )


def test_the_coarse_subtree_delta_does_not_feed_the_leaf_glob(qtbot):
    """Грубая дельта на корень поддерева листовой глоб НЕ матчит — измерено.

    Так выглядит первый тик после появления писателя: стор отдаёт
    ``…state.plugins`` целиком (значение — dict), и только со второго тика идут
    листовые дельты. Метка поэтому оживает НЕ на первом тике. Свойство записано
    тестом, а не комментарием: если матчер однажды начнёт разворачивать dict-
    значения, красное здесь скажет, что задержка исчезла (это улучшение — тест
    придётся переписать осознанно, а не обнаружить расхождение на стенде).
    """
    section, feed = _real_bindings_section(qtbot)
    label = section._labels["capture_fps"]

    feed("processes.camera_0.state.plugins", {"capture": {"capture_fps": 12.5}})
    after_coarse = label.text()
    feed("processes.camera_0.state.plugins.capture.capture_fps", 12.5)

    assert after_coarse != "12.5 fps", "грубая дельта неожиданно накормила листовой глоб"
    assert label.text() == "12.5 fps", "листовая дельта следом обязана доехать"


def test_two_writers_of_capture_fps_share_one_label(qtbot):
    """Два писателя одного имени → одна метка, побеждает последняя дельта.

    **Это ОГРАНИЧЕНИЕ, а не гарантия, и оно здесь зафиксировано нарочно.**
    Ф1 хоронит спор за имя в ДЕРЕВЕ (писатель — сегмент пути, два писателя = два
    разных листа), но в этой строке инспектора глоб ``plugins.*`` сводит их
    обратно в один QLabel, и имя писателя не видно. Соседний виджет
    (``_telemetry_controls._plugin_readout``) на тот же вопрос отвечает иначе —
    печатает «писатель: значение» всегда.

    Довод, почему здесь оставлено так: секция показывается ТОЛЬКО для камерной
    ноды (``camera_service`` либо ``capture``, см. докстринг модуля), и второго
    писателя ``capture_fps`` в этом процессе рецепты не заводят. Лекарство, если
    заведут, уже есть в API и названо: ``GuiStateBindings.bind_fanout`` — та же
    дорога, которой пользуются строки рантайм-воркеров.

    Тест краснеет в день, когда поведение изменят, — и это ровно то, чего от
    него ждут: молча такое менять нельзя.
    """
    section, feed = _real_bindings_section(qtbot)
    label = section._labels["capture_fps"]

    feed("processes.camera_0.state.plugins.capture.capture_fps", 12.5)
    first = label.text()
    feed("processes.camera_0.state.plugins.capture_two.capture_fps", 30.0)

    assert first == "12.5 fps"
    assert label.text() == "30.0 fps", (
        "поведение двух писателей в этой строке изменилось — перечитай докстринг "
        "теста и реши осознанно (bind_fanout с именем писателя либо новый довод)"
    )
    assert "capture_two" not in label.text(), "имя писателя в этой строке не печатается (см. довод)"
