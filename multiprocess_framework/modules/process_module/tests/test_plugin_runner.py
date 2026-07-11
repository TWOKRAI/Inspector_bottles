"""Тесты PluginRunner — единый шов вызова process()/produce() + pre/post-хуки.

Покрытие (Этап 4):
- call_process/call_produce возвращают результат плагина без изменений;
- pre-хук видит входы до вызова, post-хук — входы+выходы после;
- исключение плагина пробрасывается (error policy у вызывающего, не у раннера);
- кривой хук изолируется (try/except + log), не роняет вызов;
- overhead пустого раннера на hot path < 0.1 мс.
"""

from __future__ import annotations

import time

import pytest

from multiprocess_framework.modules.process_module.generic.plugin_runner import PluginRunner
from multiprocess_framework.modules.process_module.plugins.port import Port, PortValidationError


class _FakePlugin:
    """Минимальный плагин-двойник: process/produce + имя (раннер читает .name)."""

    name = "fake"

    def __init__(self, process_fn=None, produce_fn=None) -> None:
        self._process_fn = process_fn or (lambda items: items)
        self._produce_fn = produce_fn or (lambda: [{"frame": 1}])

    def process(self, items):
        return self._process_fn(items)

    def produce(self):
        return self._produce_fn()


# ---------------------------------------------------------------------------
#  Базовый прозрачный вызов
# ---------------------------------------------------------------------------


def test_call_process_returns_plugin_output():
    runner = PluginRunner()
    plugin = _FakePlugin(process_fn=lambda items: [{**it, "seen": True} for it in items])
    result = runner.call_process(plugin, [{"val": 1}])
    assert result == [{"val": 1, "seen": True}]


def test_call_produce_returns_plugin_output():
    runner = PluginRunner()
    plugin = _FakePlugin(produce_fn=lambda: [{"frame": 42}])
    assert runner.call_produce(plugin) == [{"frame": 42}]


# ---------------------------------------------------------------------------
#  Хуки: pre видит вход, post видит вход+выход
# ---------------------------------------------------------------------------


def test_pre_and_post_hooks_called_with_expected_args():
    runner = PluginRunner()
    calls: list[tuple] = []
    runner.add_pre_hook(lambda p, m, inp: calls.append(("pre", m, inp)))
    runner.add_post_hook(lambda p, m, inp, out: calls.append(("post", m, inp, out)))

    plugin = _FakePlugin(process_fn=lambda items: [{"out": 1}])
    runner.call_process(plugin, [{"in": 1}])

    assert calls[0] == ("pre", "process", [{"in": 1}])
    assert calls[1] == ("post", "process", [{"in": 1}], [{"out": 1}])


def test_produce_pre_hook_inputs_none():
    runner = PluginRunner()
    seen: list = []
    runner.add_pre_hook(lambda p, m, inp: seen.append((m, inp)))
    runner.add_post_hook(lambda p, m, inp, out: seen.append((m, inp, out)))

    plugin = _FakePlugin(produce_fn=lambda: [{"frame": 7}])
    runner.call_produce(plugin)

    assert seen[0] == ("produce", None)
    assert seen[1] == ("produce", None, [{"frame": 7}])


# ---------------------------------------------------------------------------
#  Error policy: исключение плагина пробрасывается, post-хук НЕ зовётся
# ---------------------------------------------------------------------------


def test_plugin_exception_propagates_and_skips_post_hook():
    runner = PluginRunner()
    post_called: list = []
    runner.add_post_hook(lambda *a: post_called.append(a))

    def boom(items):
        raise ValueError("plugin failed")

    plugin = _FakePlugin(process_fn=boom)
    try:
        runner.call_process(plugin, [{"x": 1}])
        assert False, "ожидалось ValueError"
    except ValueError as e:
        assert "plugin failed" in str(e)
    assert post_called == []  # post-хук не зовётся при ошибке плагина


# ---------------------------------------------------------------------------
#  Изоляция кривого хука: не роняет вызов, ошибка логируется
# ---------------------------------------------------------------------------


def test_broken_pre_hook_isolated():
    errors: list[str] = []
    runner = PluginRunner(log_error=errors.append)
    runner.add_pre_hook(lambda *a: (_ for _ in ()).throw(RuntimeError("bad hook")))

    plugin = _FakePlugin(process_fn=lambda items: [{"ok": 1}])
    result = runner.call_process(plugin, [{"x": 1}])

    assert result == [{"ok": 1}]  # вызов прошёл несмотря на кривой хук
    assert len(errors) == 1 and "bad hook" in errors[0]


def test_broken_post_hook_isolated():
    errors: list[str] = []
    runner = PluginRunner(log_error=errors.append)
    runner.add_post_hook(lambda *a: (_ for _ in ()).throw(RuntimeError("bad post")))

    plugin = _FakePlugin(produce_fn=lambda: [{"frame": 1}])
    result = runner.call_produce(plugin)

    assert result == [{"frame": 1}]
    assert len(errors) == 1 and "bad post" in errors[0]


# ---------------------------------------------------------------------------
#  Overhead: пустой раннер на hot path < 0.1 мс/вызов
# ---------------------------------------------------------------------------


def test_empty_runner_overhead_negligible():
    runner = PluginRunner()
    plugin = _FakePlugin(process_fn=lambda items: items)
    items = [{"frame": 1}]

    n = 10_000
    t0 = time.perf_counter()
    for _ in range(n):
        runner.call_process(plugin, items)
    per_call = (time.perf_counter() - t0) / n

    # Требование Этапа 4: overhead пустого раннера < 0.1 мс. Берём запас (вызов
    # плагина-двойника + два пустых прохода по хукам — субмиллисекунда с большим зазором).
    assert per_call < 0.1e-3, f"overhead {per_call * 1e6:.1f} мкс/вызов превышает 100 мкс"


# ---------------------------------------------------------------------------
#  Bypass: enabled=False → process() не вызывается, кадр идёт насквозь
# ---------------------------------------------------------------------------


def test_disabled_plugin_passes_through_without_process():
    runner = PluginRunner()
    called: list[bool] = []

    def _proc(items):
        called.append(True)
        return [{"mutated": True}]

    plugin = _FakePlugin(process_fn=_proc)
    plugin.enabled = False
    items = [{"frame": 7}]
    out = runner.call_process(plugin, items)
    assert out is items  # тот же список — кадр без обработки
    assert called == []  # process() НЕ вызывался


def test_enabled_plugin_processes_normally():
    runner = PluginRunner()
    plugin = _FakePlugin(process_fn=lambda items: [{**it, "seen": True} for it in items])
    plugin.enabled = True
    assert runner.call_process(plugin, [{"v": 1}]) == [{"v": 1, "seen": True}]


def test_disabled_plugin_still_runs_hooks():
    """Bypass не должен ослеплять наблюдателей: pre/post-хуки срабатывают, outputs=inputs."""
    runner = PluginRunner()
    seen: list[tuple] = []
    runner.add_post_hook(lambda p, m, inp, out: seen.append((m, inp, out)))
    plugin = _FakePlugin(process_fn=lambda items: [{"x": 1}])
    plugin.enabled = False
    items = [{"frame": 1}]
    runner.call_process(plugin, items)
    assert seen == [("process", items, items)]


# ---------------------------------------------------------------------------
#  FW_PORT_VALIDATE (Ф4.3): dev-mode payload-валидатор по Port-декларациям.
#  OFF по умолчанию — прод-путь бит-в-бит прежний (см. test_off_by_default_*).
# ---------------------------------------------------------------------------


def test_port_validate_off_by_default_ignores_missing_output_field():
    """Без флага/аргумента поведение прежнее — даже если items не совпадают с outputs."""
    runner = PluginRunner()
    plugin = _FakePlugin(process_fn=lambda items: [{"no_mask_here": True}])
    plugin.outputs = [Port(name="mask", dtype="image/gray")]
    result = runner.call_process(plugin, [{"frame": 1}])
    assert result == [{"no_mask_here": True}]  # не бросило, прежнее поведение


def test_port_validate_on_raises_for_missing_output_field():
    """validate_ports=True (DI, минуя env) -> отсутствующий обязательный output-порт бросает."""
    runner = PluginRunner(validate_ports=True)
    plugin = _FakePlugin(process_fn=lambda items: [{"no_mask_here": True}])
    plugin.name = "color_mask"
    plugin.outputs = [Port(name="mask", dtype="image/gray")]

    with pytest.raises(PortValidationError) as exc_info:
        runner.call_process(plugin, [{"frame": 1}])
    msg = str(exc_info.value)
    assert "color_mask" in msg and "mask" in msg


def test_port_validate_on_raises_for_missing_input_field():
    """validate_ports=True -> отсутствующий обязательный input-порт бросает ДО вызова process()."""
    runner = PluginRunner(validate_ports=True)
    called: list[bool] = []

    def _proc(items):
        called.append(True)
        return items

    plugin = _FakePlugin(process_fn=_proc)
    plugin.name = "needs_frame"
    plugin.inputs = [Port(name="frame", dtype="image/bgr")]

    with pytest.raises(PortValidationError):
        runner.call_process(plugin, [{"not_frame": 1}])
    assert called == []  # process() не вызван — упало на входной границе


def test_port_validate_on_passes_when_fields_present():
    """validate_ports=True -> корректные items не мешают обычному вызову."""
    runner = PluginRunner(validate_ports=True)
    plugin = _FakePlugin(process_fn=lambda items: [{"mask": object()}])
    plugin.inputs = [Port(name="frame", dtype="image/bgr")]
    plugin.outputs = [Port(name="mask", dtype="image/gray")]
    result = runner.call_process(plugin, [{"frame": 1}])
    assert result == [{"mask": result[0]["mask"]}]


def test_port_validate_on_skips_optional_output():
    runner = PluginRunner(validate_ports=True)
    plugin = _FakePlugin(process_fn=lambda items: [{"frame": 1}])  # без "stats"
    plugin.outputs = [Port(name="stats", dtype="dict", optional=True)]
    result = runner.call_process(plugin, [{"frame": 1}])
    assert result == [{"frame": 1}]  # не бросило — порт optional


def test_port_validate_env_flag_enables_validation(monkeypatch):
    """FW_PORT_VALIDATE=1 в окружении включает валидацию без явного validate_ports=True."""
    monkeypatch.setenv("FW_PORT_VALIDATE", "1")
    runner = PluginRunner()
    plugin = _FakePlugin(process_fn=lambda items: [{"no_mask_here": True}])
    plugin.outputs = [Port(name="mask", dtype="image/gray")]

    with pytest.raises(PortValidationError):
        runner.call_process(plugin, [{"frame": 1}])


def test_port_validate_produce_checks_output_only():
    """call_produce: нет inputs (источник), проверяются только outputs."""
    runner = PluginRunner(validate_ports=True)
    plugin = _FakePlugin(produce_fn=lambda: [{"no_frame_here": True}])
    plugin.name = "camera"
    plugin.outputs = [Port(name="frame", dtype="image/bgr")]

    with pytest.raises(PortValidationError) as exc_info:
        runner.call_produce(plugin)
    assert "camera" in str(exc_info.value)


def test_port_validate_bypass_skips_port_check():
    """Bypass (enabled=False): items идут насквозь, свои output-порты плагина не проверяются."""
    runner = PluginRunner(validate_ports=True)
    plugin = _FakePlugin(process_fn=lambda items: [{"mutated": True}])
    plugin.enabled = False
    plugin.outputs = [Port(name="mask", dtype="image/gray")]  # не будет в проходном item
    items = [{"frame": 1}]
    result = runner.call_process(plugin, items)
    assert result is items  # прошло насквозь, без ошибки валидации
