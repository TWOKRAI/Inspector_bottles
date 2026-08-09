"""Ф8.7 — вердикт об отбраковке уходит документом, а не строкой журнала.

Опасные места именно ЭТОГО механизма (тесты автора):

1. **Частота.** Дефектное изделие видно детектору десятки кадров подряд, а запись
   документа синхронная (медиана 3.6 мс, max 928 мс). Вердикт обязан писаться на
   ФРОНТЕ решения pass→reject, иначе одна отбраковка даёт десятки документов и
   останавливает линию. Это главное свойство файла.
2. **Границы фронта.** Выключение плагина посреди брака, сброс счётчиков, чередование
   pass/reject — каждая из этих ситуаций либо теряет вердикт, либо удваивает его.
3. **Отказ дороги.** Плоскость не настроена или БД отказала — решение об отбраковке
   всё равно обязано уехать по своей дороге, а потеря — быть посчитанной и названной
   ровно один раз, а не строкой на каждый кадр.

Контекст здесь — не ``MagicMock`` (в отличие от соседнего ``test_plugin.py``): фальшивка,
которая на любой вызов отвечает истиной, зелена и при полностью снятой записи —
«фальшивка-всегда-успех глушит гейт».
"""

from __future__ import annotations

from typing import Any, Dict, List

import numpy as np
import pytest

from Plugins.control.robot_control.plugin import RobotControlPlugin


class _Ctx:
    """PluginContext в объёме, который использует плагин. Умеет отказывать в записи."""

    def __init__(self, config: Dict[str, Any] | None = None, *, accept: bool = True) -> None:
        self.config = config or {}
        self.registers = None
        self.command_manager = None
        self.process_name = "inspector"
        self.plugin_name = "robot_control"
        self.documents: List[Dict[str, Any]] = []
        self.errors: List[str] = []
        self._accept = accept

    def write_document(self, kind: str, summary: str = "", /, **fields: Any) -> bool:
        self.documents.append({"kind": kind, "summary": summary, **fields})
        return self._accept

    def log_info(self, message: str, **kwargs: Any) -> None:
        pass

    def log_error(self, message: str, **kwargs: Any) -> None:
        self.errors.append(message)


def _frame() -> np.ndarray:
    return np.zeros((100, 100, 3), dtype=np.uint8)


def _defect(area: int = 1600) -> dict:
    return {"bbox": [10, 10, 50, 50], "center": [30, 30], "area": area}


def _plugin(ctx: _Ctx) -> RobotControlPlugin:
    plugin = RobotControlPlugin()
    plugin.configure(ctx)
    return plugin


def _feed(plugin: RobotControlPlugin, *frames: list) -> None:
    """Прогнать кадры по одному — так их и отдаёт конвейер."""
    for detections in frames:
        plugin.process([{"frame": _frame(), "detections": detections}])


class TestVerdictReachesThePlane:
    def test_rejection_writes_one_document_of_kind_verdict(self) -> None:
        ctx = _Ctx({"min_defect_area": 500})
        _feed(_plugin(ctx), [_defect(1600)])

        assert len(ctx.documents) == 1
        assert ctx.documents[0]["kind"] == "verdict"

    def test_pass_writes_nothing(self) -> None:
        """Пара к предыдущему: годное изделие документа не порождает.

        Не бережливость, а арифметика: 25 кадров/с × документ = 25 синхронных
        записей в секунду на дороге, чей худший наблюдённый вызов 928 мс.
        """
        ctx = _Ctx({"min_defect_area": 500})
        _feed(_plugin(ctx), [], [_defect(100)], [])

        assert ctx.documents == []

    def test_document_carries_the_threshold_that_decided(self) -> None:
        """Вердикт без порога нечем оспорить: «почему брак» отвечается только вместе с ним."""
        ctx = _Ctx({"min_defect_area": 500})
        _feed(_plugin(ctx), [_defect(1600), _defect(900)])

        doc = ctx.documents[0]
        assert doc["min_defect_area"] == 500
        assert doc["defect_count"] == 2
        assert doc["defect_area_max"] == 1600.0
        assert doc["defect_area_total"] == 2500.0
        assert doc["action"] == "reject"

    def test_summary_names_the_rejection_number(self) -> None:
        ctx = _Ctx({"min_defect_area": 500})
        _feed(_plugin(ctx), [_defect()], [], [_defect()])

        assert ctx.documents[0]["summary"].startswith("отбраковка #1")
        assert ctx.documents[1]["summary"].startswith("отбраковка #2")


class TestOneDocumentPerRejection:
    def test_a_series_of_defective_frames_is_one_verdict(self) -> None:
        """ГЛАВНОЕ свойство: 10 кадров одного брака → один документ, не десять."""
        ctx = _Ctx({"min_defect_area": 500})
        plugin = _plugin(ctx)

        _feed(plugin, *[[_defect()] for _ in range(10)])

        assert len(ctx.documents) == 1
        assert plugin._total_rejected == 10, "решение при этом принимается на каждом кадре"

    def test_a_good_frame_between_defects_opens_a_new_rejection(self) -> None:
        """Пара к предыдущему: без неё «один документ» держалось бы и на снятой записи."""
        ctx = _Ctx({"min_defect_area": 500})
        _feed(_plugin(ctx), [_defect()], [_defect()], [], [_defect()])

        assert len(ctx.documents) == 2

    def test_disabling_mid_rejection_closes_the_front(self) -> None:
        """Выключили посреди брака, включили обратно — это НОВАЯ отбраковка.

        Не сбрось выключение фронт — повторное включение на том же дефекте не дало бы
        вердикта вовсе: фронта-то не было.

        По ДВА кадра брака с каждой стороны выключения не для полноты: с одним
        ожидаемое число (2) совпадало с тем, что даёт запись на КАЖДОМ кадре, и тест
        оставался зелёным под инъекцией «фронт снят» — совпадение констант прятало
        различие. С двумя ответы расходятся: 2 против 4.
        """
        ctx = _Ctx({"min_defect_area": 500})
        plugin = _plugin(ctx)

        _feed(plugin, [_defect()], [_defect()])
        plugin.cmd_disable({})
        _feed(plugin, [_defect()])
        plugin.cmd_enable({})
        _feed(plugin, [_defect()], [_defect()])

        assert len(ctx.documents) == 2

    def test_reset_counters_does_not_reopen_the_front(self) -> None:
        """Сброс статистики — не изменение состояния линии. Сбрось он фронт, следующий
        кадр той же отбраковки выдал бы второй вердикт об одном изделии."""
        ctx = _Ctx({"min_defect_area": 500})
        plugin = _plugin(ctx)

        _feed(plugin, [_defect()])
        plugin.cmd_reset_counters({})
        _feed(plugin, [_defect()])

        assert len(ctx.documents) == 1


class TestFailureIsCountedAndNamedOnce:
    def test_line_keeps_deciding_when_the_plane_refuses(self) -> None:
        ctx = _Ctx({"min_defect_area": 500}, accept=False)
        plugin = _plugin(ctx)

        result = plugin.process([{"frame": _frame(), "detections": [_defect()]}])

        assert result[0]["inspection_result"]["action"] == "reject"

    def test_loss_is_visible_through_the_command_surface(self) -> None:
        """Путь наружу — ``get_stats``: расхождение видно без похода в БД."""
        ctx = _Ctx({"min_defect_area": 500}, accept=False)
        plugin = _plugin(ctx)

        _feed(plugin, [_defect()], [], [_defect()])

        stats = plugin.cmd_get_stats({})
        assert stats["verdicts_unwritten"] == 2
        assert stats["verdicts_written"] == 0

    def test_written_verdicts_are_counted_too(self) -> None:
        ctx = _Ctx({"min_defect_area": 500})
        plugin = _plugin(ctx)

        _feed(plugin, [_defect()], [], [_defect()])

        assert plugin.cmd_get_stats({})["verdicts_written"] == 2

    def test_the_cause_is_named_exactly_once_per_run(self) -> None:
        """Линия выдаёт брак сериями; причина отказа от кадра к кадру не меняется.
        Строка на каждый вердикт была бы штормом на пути, уже признанном отказавшим."""
        ctx = _Ctx({"min_defect_area": 500}, accept=False)
        plugin = _plugin(ctx)

        _feed(plugin, *[[_defect()], [], [_defect()], [], [_defect()]])

        assert len(ctx.errors) == 1
        assert "observability.documents" in ctx.errors[0]
        assert "verdicts_unwritten" in ctx.errors[0], "строка обязана назвать, где смотреть счёт"


class TestVerdictsAreNotDiagnosticLogLines:
    def test_rejection_does_not_go_to_the_journal_at_all(self) -> None:
        """Правило «вердикты о качестве в диагностические логи не пишутся» снято тем,
        что у них появилась своя дорога, — а не тем, что их стали писать в обе."""
        ctx = _Ctx({"min_defect_area": 500})
        _feed(_plugin(ctx), [_defect()])

        assert ctx.errors == []
        assert len(ctx.documents) == 1


def test_verdict_is_written_before_the_mechanism_delay(monkeypatch: pytest.MonkeyPatch) -> None:
    """Документ несёт время РЕШЕНИЯ, а не время механизма.

    Задержка отбраковки бывает в сотни миллисекунд (синхронизация с толкателем), и
    вердикт, записанный ПОСЛЕ неё, датировался бы моментом механизма. Проверяется
    порядком двух событий, а не фактом вызова: шпион на имя метода сторожил бы имя.

    ``time`` подменяется в пространстве имён модуля плагина, а не глобально: патч
    самого ``time`` действовал бы на весь процесс и на соседние тесты.
    """
    order: List[str] = []

    class _FakeTime:
        @staticmethod
        def sleep(seconds: float) -> None:
            order.append(f"slept:{seconds}")

    import Plugins.control.robot_control.plugin as plugin_mod

    monkeypatch.setattr(plugin_mod, "time", _FakeTime)

    ctx = _Ctx({"min_defect_area": 500, "reject_delay_ms": 200})
    plugin = _plugin(ctx)
    original = ctx.write_document

    def _spy(kind: str, summary: str = "", /, **fields: Any) -> bool:
        order.append("wrote")
        return original(kind, summary, **fields)

    ctx.write_document = _spy  # type: ignore[assignment]

    _feed(plugin, [_defect()])

    assert order == ["wrote", "slept:0.2"]
