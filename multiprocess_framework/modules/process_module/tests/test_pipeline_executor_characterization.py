"""Характеризационные тесты PipelineExecutor (C6(d) инкремент 1, паттерн F).

Фиксируют ТЕКУЩЕЕ поведение ``_execute_chain`` / ``_send_results`` ДО перевода
исполнения на ``ChainRunnable`` из chain_module. Ожидания здесь — контракт, который
рефактор обязан сохранить бит-в-бит. НЕ менять ожидания при рефакторинге: если тест
краснеет — краснеет поведение, а не тест.

Отличие от ``test_pipeline_executor.py``: там базовые юниты (одобренные ожидания),
здесь — точечная фиксация тонких инвариантов, которые легко потерять при переходе
на chain-движок:
    - circuit breaker открывается ровно на N-м фейле при ПРОД-значении max=5;
    - reset счётчика fails на успехе (перемежающийся успех не даёт открыть breaker);
    - auto-reset по таймауту;
    - error-policy = pass-through + тег ``inspection_status="not_inspected"``
      (items ПРОДОЛЖАЮТ течь, не отбрасываются);
    - критический bypassed → тег ``"suspect"``; некритический bypassed → без тега;
    - items ЗАМЕНЯЮТСЯ выходом плагина (identity/содержимое от плагина, не от входа);
    - ``if not items: break`` — плагин ПОСЛЕ опустошившего цепочку фильтра НЕ вызывается;
    - per-item ``target``-override vs default ``chain_targets`` в ``_send_results``.
"""

from __future__ import annotations

from multiprocess_framework.modules.process_module.generic.pipeline_executor import (
    PipelineExecutor,
)
from multiprocess_framework.modules.process_module.plugins.base import (
    ProcessModulePlugin,
)


# --------------------------------------------------------------------------- #
#  Тестовые плагины                                                            #
# --------------------------------------------------------------------------- #


class ReplacePlugin(ProcessModulePlugin):
    """Возвращает СОВСЕМ новый список — проверка «items заменяются выходом»."""

    name = "replace"
    category = "processing"

    def configure(self, ctx): ...
    def start(self, ctx): ...

    def process(self, items):
        # Полностью новый список новых dict — ни identity, ни содержимое входа.
        return [{"replaced": True, "n": len(items)}]


class DropAllPlugin(ProcessModulePlugin):
    """Всегда возвращает пустой список — опустошает цепочку."""

    name = "drop_all"
    category = "processing"

    def configure(self, ctx): ...
    def start(self, ctx): ...

    def process(self, items):
        return []


class SpyPlugin(ProcessModulePlugin):
    """Записывает, был ли вызван process() (для проверки ``if not items: break``)."""

    name = "spy"
    category = "processing"

    def __init__(self):
        super().__init__()
        self.calls: list[int] = []

    def configure(self, ctx): ...
    def start(self, ctx): ...

    def process(self, items):
        self.calls.append(len(items))
        return items


class FlakyPlugin(ProcessModulePlugin):
    """Падает, пока ``fail`` == True; переключается извне для проверки reset."""

    name = "flaky"
    category = "processing"

    def __init__(self):
        super().__init__()
        self.fail = True

    def configure(self, ctx): ...
    def start(self, ctx): ...

    def process(self, items):
        if self.fail:
            raise ValueError("flaky failure")
        return items


class AlwaysFailPlugin(ProcessModulePlugin):
    name = "always_fail"
    category = "processing"

    def configure(self, ctx): ...
    def start(self, ctx): ...

    def process(self, items):
        raise RuntimeError("always fails")


def _make(plugins, **kw):
    return PipelineExecutor(
        plugins=plugins,
        chain_targets=kw.pop("chain_targets", ["out"]),
        shm_middleware=None,
        send_fn=kw.pop("send_fn", lambda t, m: None),
        **kw,
    )


# --------------------------------------------------------------------------- #
#  Circuit breaker — прод-значение max=5                                       #
# --------------------------------------------------------------------------- #


class TestCircuitBreakerProdThreshold:
    def test_breaker_opens_exactly_on_fifth_fail_prod_value(self):
        """ПРОД max_consecutive_fails=5: 4 фейла — не bypassed, 5-й — bypassed."""
        executor = _make([AlwaysFailPlugin()], max_consecutive_fails=5)

        for i in range(4):
            executor._execute_chain([{"v": i}])
            assert not executor.is_bypassed("always_fail"), f"bypassed рано на {i + 1}-м фейле"

        # 5-й фейл открывает breaker.
        executor._execute_chain([{"v": 4}])
        assert executor.is_bypassed("always_fail")

    def test_success_resets_consecutive_fails_counter(self):
        """Перемежающийся успех сбрасывает счётчик — breaker НЕ открывается."""
        plugin = FlakyPlugin()
        executor = _make([plugin], max_consecutive_fails=3)

        # 2 фейла (порог 3 не достигнут).
        plugin.fail = True
        executor._execute_chain([{"v": 1}])
        executor._execute_chain([{"v": 2}])
        assert not executor.is_bypassed("flaky")

        # Успех сбрасывает счётчик.
        plugin.fail = False
        executor._execute_chain([{"v": 3}])
        assert not executor.is_bypassed("flaky")

        # Снова 2 фейла — счётчик стартовал с нуля, порог не достигнут.
        plugin.fail = True
        executor._execute_chain([{"v": 4}])
        executor._execute_chain([{"v": 5}])
        assert not executor.is_bypassed("flaky")

        # 3-й подряд — теперь открывается.
        executor._execute_chain([{"v": 6}])
        assert executor.is_bypassed("flaky")

    def test_auto_reset_after_timeout(self):
        import time

        executor = _make([AlwaysFailPlugin()], max_consecutive_fails=1, auto_reset_sec=0.05)
        executor._execute_chain([{"v": 1}])
        assert executor.is_bypassed("always_fail")

        time.sleep(0.08)
        executor._check_auto_reset()
        assert not executor.is_bypassed("always_fail")


# --------------------------------------------------------------------------- #
#  Error policy — pass-through + тег, items продолжают течь                     #
# --------------------------------------------------------------------------- #


class TestErrorPolicyPassThrough:
    def test_error_tags_not_inspected_and_items_keep_flowing(self):
        """Ошибка плагина: items НЕ отбрасываются, все получают not_inspected."""
        executor = _make([AlwaysFailPlugin()])
        items = [{"v": 1}, {"v": 2}, {"v": 3}]
        result = executor._execute_chain(items)
        assert len(result) == 3  # ни один item не потерян
        assert all(r["inspection_status"] == "not_inspected" for r in result)

    def test_tagged_items_continue_to_next_plugin(self):
        """После ошибки помеченные items доходят до следующего плагина цепочки."""
        spy = SpyPlugin()
        executor = _make([AlwaysFailPlugin(), spy])
        result = executor._execute_chain([{"v": 1}, {"v": 2}])
        # Плагин-после-ошибки ВЫЗВАН с теми же 2 items (pass-through, не break).
        assert spy.calls == [2]
        assert all(r["inspection_status"] == "not_inspected" for r in result)


# --------------------------------------------------------------------------- #
#  Bypassed: критический → suspect, некритический → без тега                    #
# --------------------------------------------------------------------------- #


class TestBypassSuspectTagging:
    def test_critical_bypassed_marks_suspect(self):
        executor = _make([AlwaysFailPlugin()], max_consecutive_fails=1, critical_plugins=["always_fail"])
        executor._execute_chain([{"v": 1}])  # открыть breaker
        assert executor.is_bypassed("always_fail")

        result = executor._execute_chain([{"v": 99}])
        assert result[0]["inspection_status"] == "suspect"

    def test_noncritical_bypassed_no_tag(self):
        executor = _make([AlwaysFailPlugin()], max_consecutive_fails=1)
        executor._execute_chain([{"v": 1}])  # открыть breaker
        assert executor.is_bypassed("always_fail")

        result = executor._execute_chain([{"v": 99}])
        assert "inspection_status" not in result[0]


# --------------------------------------------------------------------------- #
#  Items заменяются выходом плагина                                            #
# --------------------------------------------------------------------------- #


class TestItemsReplacedByOutput:
    def test_items_are_replaced_not_mutated(self):
        """Выход = то, что вернул плагин (новый список), а не вход."""
        executor = _make([ReplacePlugin()])
        items = [{"v": 1}, {"v": 2}]
        result = executor._execute_chain(items)
        assert result == [{"replaced": True, "n": 2}]
        assert result is not items


# --------------------------------------------------------------------------- #
#  if not items: break — плагин после опустошения не вызывается                 #
# --------------------------------------------------------------------------- #


class TestEmptyBreak:
    def test_plugin_after_empty_is_not_called(self):
        spy = SpyPlugin()
        executor = _make([DropAllPlugin(), spy])
        result = executor._execute_chain([{"v": 1}])
        assert result == []
        # Ключевой инвариант: плагин ПОСЛЕ опустошившего цепочку НЕ вызван.
        assert spy.calls == []


# --------------------------------------------------------------------------- #
#  Routing в _send_results                                                     #
# --------------------------------------------------------------------------- #


class TestSendRoutingCharacterization:
    def test_default_chain_targets_fanout(self):
        sent = []
        executor = _make([ReplacePlugin()], chain_targets=["a", "b"], send_fn=lambda t, m: sent.append((t, m)))
        executor._send_results([{"v": 1}])
        assert [t for t, _ in sent] == ["a", "b"]

    def test_per_item_target_override_wins(self):
        sent = []
        executor = _make([ReplacePlugin()], chain_targets=["default"], send_fn=lambda t, m: sent.append((t, m)))
        executor._send_results([{"v": 1, "target": "special"}])
        assert [t for t, _ in sent] == ["special"]
        # target удаляется из item (pop) при роутинге.
        assert "target" not in sent[0][1]["data"]


# --------------------------------------------------------------------------- #
#  suspect-тег критического bypassed — ПОЗИЦИОННАЯ семантика (Fable HIGH)       #
# --------------------------------------------------------------------------- #
#  Старое поведение: тег "suspect" ставился НА ПОЗИЦИИ bypassed-critical
#  плагина — на items, существующие В ТОТ момент цепочки. Значит:
#    - живой плагин ПОСЛЕ этой позиции перезаписывает статус своим значением;
#    - живой плагин ДО позиции, вернувший НОВЫЕ dict'ы, не мешает тегу
#      (тег ставится на его выход).


class StatusWriterPlugin(ProcessModulePlugin):
    """Пишет inspection_status (работа inspection-плагина) — in-place."""

    def __init__(self, status="ok"):
        super().__init__()
        self.name = "writer"
        self.category = "processing"
        self._status = status

    def configure(self, ctx): ...
    def start(self, ctx): ...

    def process(self, items):
        for it in items:
            it["inspection_status"] = self._status
        return items


class ReplaceListStatusPlugin(ProcessModulePlugin):
    """Возвращает СВЕЖИЕ dict'ы без inspection_status (замена списка — контракт)."""

    name = "replacer"
    category = "processing"

    def configure(self, ctx): ...
    def start(self, ctx): ...

    def process(self, items):
        return [{"fresh": True, "v": it.get("v")} for it in items]


class TestSuspectPositionSemantics:
    def _bypass_critical(self, executor):
        """Открыть breaker критического always_fail (max_fails=1 → 1 фейл)."""
        executor._execute_chain([{"v": 0}])
        assert executor.is_bypassed("always_fail")

    def test_downstream_critical_suspect_beats_upstream_status(self):
        """[writer('ok') → critical bypassed]: suspect на позиции critical побеждает 'ok'."""
        executor = _make(
            [StatusWriterPlugin("ok"), AlwaysFailPlugin()],
            max_consecutive_fails=1,
            critical_plugins=["always_fail"],
        )
        self._bypass_critical(executor)
        result = executor._execute_chain([{"v": 1}])
        assert result[0]["inspection_status"] == "suspect"

    def test_upstream_critical_then_writer_status_wins(self):
        """[critical bypassed → writer('ok')]: статус плагина ниже по цепочке побеждает."""
        executor = _make(
            [AlwaysFailPlugin(), StatusWriterPlugin("ok")],
            max_consecutive_fails=1,
            critical_plugins=["always_fail"],
        )
        self._bypass_critical(executor)
        result = executor._execute_chain([{"v": 1}])
        assert result[0]["inspection_status"] == "ok"

    def test_suspect_survives_list_replacement_before_critical(self):
        """[replacer(новые dict'ы) → critical bypassed]: suspect ставится на СВЕЖИЙ выход."""
        executor = _make(
            [ReplaceListStatusPlugin(), AlwaysFailPlugin()],
            max_consecutive_fails=1,
            critical_plugins=["always_fail"],
        )
        self._bypass_critical(executor)
        result = executor._execute_chain([{"v": 1}])
        assert result[0].get("fresh") is True  # выход именно replacer'а
        assert result[0]["inspection_status"] == "suspect"
