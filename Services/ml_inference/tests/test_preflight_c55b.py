"""Слепая приёмка C-55b: `ml_inference` сам проверяет ассеты модели (RED до правки).

Источник контракта — `plans/word-layout/tasks/C-55b.md` («Решения владельца», «Харнес», «REDS»).
Тесты идут только по публичному пути: `ModelRegistry.diagnose` / `scan`, `MLInferencePlugin.configure` /
`process` / `cmd_reload_model`, регистры на чтение (`plugin._reg`), снапшот настоящего `HealthState`.
Ожидаемые значения — литералы спецификации, ни одно не вычисляется из кода под тестом.

Тесты 1–8 — реестр (`diagnose`): серьёзность (`error` / `warning` / `info`) и `path` находки.
Тесты 9–10 — плагин: ошибка ассета не блокирует старт, health процесса уходит в `degraded`, плагин
остаётся в pass-through; после появления ассетов `cmd_reload_model` возвращает `ok`.

Вызовы, способные повиснуть (`configure` / `process` / `cmd_reload_model`), идут в daemon-потоке
с дедлайном `join`.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import numpy as np
import pytest

from multiprocess_framework.modules.process_module.health import HealthReporter, HealthState
from Services.ml_inference.backends.base import BaseInferenceBackend
from Services.ml_inference.core.model_spec import ModelSpec
from Services.ml_inference.core.registry import ModelRegistry
from Services.ml_inference.plugin.plugin import MLInferencePlugin

# Дедлайн одного вызова плагина, секунды: зависший вызов падает тестом, а не вешает прогон.
_DEADLINE_S = 10.0

# Sidecar харнеса по умолчанию (по строке на ключ): name / input_size / resize_policy / labels.
_SIDECAR_DEFAULT = "name: m1\ninput_size: [8, 8]\nresize_policy: stretch\nlabels: m1_classes.txt\n"


# --------------------------------------------------------------------------- #
# Харнес
# --------------------------------------------------------------------------- #


def _write_assets(
    root: Path,
    *,
    weights: str | None = "m1.onnx",
    sidecar: str | None = _SIDECAR_DEFAULT,
    labels: str | None = "A\n",
) -> None:
    """Положить ассеты модели `m1` в `root`; `None` — этого файла нет.

    Реестр содержимое весов не читает, поэтому веса — `b"x"`.
    """
    root.mkdir(parents=True, exist_ok=True)
    if weights is not None:
        (root / weights).write_bytes(b"x")
    if sidecar is not None:
        (root / "m1.yaml").write_text(sidecar, encoding="utf-8")
    if labels is not None:
        (root / "m1_classes.txt").write_text(labels, encoding="utf-8")


def _root(tmp_path: Path) -> Path:
    """Каталог моделей в той форме, в какой его хранит реестр (`Path.resolve()`).

    На Windows `tmp_path` бывает в коротком (8.3) виде — сравнение путей идёт с resolved-формой.
    """
    return tmp_path.resolve()


class _FakeBackend(BaseInferenceBackend):
    """Backend-заглушка: фиксированные выходы, без onnxruntime (копия из test_acceptance_always_label)."""

    def __init__(self, outputs: dict[str, np.ndarray]) -> None:
        super().__init__()
        self._outputs = outputs
        self.infer_calls = 0

    def load(self, spec: ModelSpec, device: str = "cpu") -> None:
        self._spec = spec

    def infer(self, tensor: np.ndarray) -> dict[str, np.ndarray]:
        self.infer_calls += 1
        return self._outputs

    def unload(self) -> None:
        self._spec = None


def _call_with_deadline[T](fn: Callable[[], T]) -> T:
    """Вызвать `fn` в daemon-потоке с дедлайном; исключение вызова пробрасывается как есть."""
    box: dict[str, Any] = {}

    def _runner() -> None:
        try:
            box["value"] = fn()
        except BaseException as exc:  # noqa: BLE001 — пробросим в поток теста без потерь
            box["exc"] = exc

    thread = threading.Thread(target=_runner, daemon=True)
    thread.start()
    thread.join(_DEADLINE_S)
    if thread.is_alive():
        pytest.fail(f"вызов не вернулся за {_DEADLINE_S} с (завис)")
    if "exc" in box:
        raise box["exc"]
    return box["value"]


def _make_plugin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[MLInferencePlugin, HealthState, list[tuple[str, Any]], MagicMock]:
    """Плагин с настоящими `HealthState`/`HealthReporter` и подменённым backend; `configure` НЕ вызван.

    Шов загрузки модели ставится ДО `configure`. Возвращает (плагин, состояние здоровья,
    список вызовов `track` как (имя типа исключения, payload), ctx).
    """
    monkeypatch.setattr(
        "Services.ml_inference.engine._make_backend",
        lambda _t: _FakeBackend({"logits": np.array([[1.0]], dtype=np.float32)}),
    )
    calls: list[tuple[str, Any]] = []
    state = HealthState(
        log=lambda m: None,
        track=lambda exc, payload=None: calls.append((type(exc).__name__, payload)),
        log_only=False,
    )
    ctx = MagicMock()
    ctx.config = {"model": "m1", "models_dir": str(tmp_path)}
    ctx.registers = None
    ctx.state_proxy = None
    ctx.process_name = "ml_proc"
    ctx.health = HealthReporter(state, source="ml_inference")
    return MLInferencePlugin(), state, calls, ctx


# --------------------------------------------------------------------------- #
# Реестр: ModelRegistry.diagnose
# --------------------------------------------------------------------------- #


def test_all_present_onnx_is_info(tmp_path: Path) -> None:
    """Все ассеты на месте (.onnx) → info, path = файл весов, в тексте есть id модели."""
    _write_assets(tmp_path)

    d = ModelRegistry(tmp_path).diagnose("m1")

    assert d.severity == "info"
    assert d.path == _root(tmp_path) / "m1.onnx"
    assert "m1" in d.message


def test_pt_and_pth_weights_are_info(tmp_path: Path) -> None:
    """Веса .pt и .pth (по очереди, в отдельных каталогах) тоже дают info, path = этот файл."""
    for suffix in (".pt", ".pth"):
        root = tmp_path / suffix.lstrip(".")
        _write_assets(root, weights=f"m1{suffix}")

        d = ModelRegistry(root).diagnose("m1")

        assert d.severity == "info", f"{suffix}: {d.severity} / {d.message}"
        assert d.path == _root(root) / f"m1{suffix}", suffix


def test_missing_weights_is_error(tmp_path: Path) -> None:
    """Есть только sidecar (и метки), весов нет → error, path = <каталог>/<id>."""
    _write_assets(tmp_path, weights=None)

    d = ModelRegistry(tmp_path).diagnose("m1")

    assert d.severity == "error"
    assert d.path == _root(tmp_path) / "m1"


def test_missing_sidecar_is_error(tmp_path: Path) -> None:
    """Есть только m1.onnx, sidecar нет → error, path = m1.yaml."""
    _write_assets(tmp_path, sidecar=None, labels=None)

    d = ModelRegistry(tmp_path).diagnose("m1")

    assert d.severity == "error"
    assert d.path == _root(tmp_path) / "m1.yaml"


def test_broken_sidecar_is_error_without_pydantic_text(tmp_path: Path) -> None:
    """Битый sidecar → error, path = sidecar; многострочный текст pydantic в message не попадает."""
    bad_input_size = tmp_path / "input_size"
    _write_assets(bad_input_size, sidecar='input_size: "abc"\n')
    d = ModelRegistry(bad_input_size).diagnose("m1")
    assert d.severity == "error"
    assert d.path == _root(bad_input_size) / "m1.yaml"
    assert "validation error" not in d.message

    not_a_mapping = tmp_path / "list"
    _write_assets(not_a_mapping, sidecar="- 1\n")
    d = ModelRegistry(not_a_mapping).diagnose("m1")
    assert d.severity == "error"
    assert d.path == _root(not_a_mapping) / "m1.yaml"


def test_missing_models_dir_is_error(tmp_path: Path) -> None:
    """Каталога моделей нет → error, path = этот несуществующий каталог."""
    d = ModelRegistry(tmp_path / "nope").diagnose("m1")

    assert d.severity == "error"
    assert d.path == _root(tmp_path) / "nope"


def test_model_id_input(tmp_path: Path) -> None:
    """Недопустимый id → error без path и без сырого значения в тексте; пустой id → warning."""
    _write_assets(tmp_path)
    registry = ModelRegistry(tmp_path)

    for raw in ("../m1", "a/b", "a\\b", "C:m1", "m\n1", "a..b"):
        d = registry.diagnose(raw)
        assert d.severity == "error", f"{raw!r}: {d.severity} / {d.message!r}"
        assert d.path is None, f"{raw!r}: path={d.path!r}"
        assert raw not in d.message, f"{raw!r}: сырое значение попало в message"

    empty = registry.diagnose("")
    assert empty.severity == "warning"
    assert empty.path == _root(tmp_path)


def test_sidecar_paths_must_exist(tmp_path: Path) -> None:
    """Пути из sidecar (weights / labels) обязаны существовать, файл меток — не пуст."""
    # weights: other.onnx — файла нет, при этом m1.onnx на месте
    case = tmp_path / "weights_redirect"
    _write_assets(case, sidecar=_SIDECAR_DEFAULT + "weights: other.onnx\n")
    d = ModelRegistry(case).diagnose("m1")
    assert d.severity == "error"
    assert d.path == _root(case) / "other.onnx"

    # labels: none.txt — файла меток нет
    case = tmp_path / "labels_missing"
    _write_assets(
        case,
        sidecar="name: m1\ninput_size: [8, 8]\nresize_policy: stretch\nlabels: none.txt\n",
    )
    d = ModelRegistry(case).diagnose("m1")
    assert d.severity == "error"
    assert d.path == _root(case) / "none.txt"

    # m1_classes.txt пуст
    case = tmp_path / "labels_empty"
    _write_assets(case, labels="")
    d = ModelRegistry(case).diagnose("m1")
    assert d.severity == "error"
    assert d.path == _root(case) / "m1_classes.txt"

    # m1_classes.txt только из пробелов и переводов строк
    case = tmp_path / "labels_blank"
    _write_assets(case, labels="  \n\n")
    d = ModelRegistry(case).diagnose("m1")
    assert d.severity == "error"
    assert d.path == _root(case) / "m1_classes.txt"


# --------------------------------------------------------------------------- #
# Плагин: configure / process / cmd_reload_model
# --------------------------------------------------------------------------- #


def test_plugin_missing_weights_degrades_and_passes_through(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Пустой каталог моделей: старт не падает, health `degraded`, один инцидент, pass-through."""
    plugin, state, calls, ctx = _make_plugin(tmp_path, monkeypatch)

    _call_with_deadline(lambda: plugin.configure(ctx))  # без исключения

    snap = state.snapshot()
    assert snap["status"] == "degraded"
    assert "m1" in snap["degraded_reason"]
    assert len(calls) == 1
    assert calls[0][0] == "ModelAssetError"
    assert plugin._reg.loaded_model == ""
    assert plugin._reg.last_error != ""

    out = _call_with_deadline(lambda: plugin.process([{"frame": np.zeros((8, 8, 3), np.uint8)}]))
    assert len(out) == 1


def test_plugin_recovers_own_degraded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Деградация из-за ассетов снимается сама, когда ассеты появились и `cmd_reload_model` отработал."""
    plugin, state, _calls, ctx = _make_plugin(tmp_path, monkeypatch)

    _call_with_deadline(lambda: plugin.configure(ctx))
    # Промежуточное состояние: сегодня здесь "ok" — поэтому тест красный до правки.
    assert state.snapshot()["status"] == "degraded"

    _write_assets(tmp_path)
    _call_with_deadline(lambda: plugin.cmd_reload_model({}))

    assert state.snapshot()["status"] == "ok"
    assert plugin._reg.loaded_model == "m1"
    assert plugin._reg.last_error == ""
