# -*- coding: utf-8 -*-
"""Контрактный тест защиты кадра на входе дисплея (Task R.1/R.2, plans/code-reader-gui.md).

Каждый кадр, пришедший на слот через ``ImagePanelWidget.display_frame(slot_id, frame)``, проверяется
ДО отрисовки. Здесь проверяется внешний контракт, не реализация:

* принимаются: uint8 gray ``(H,W)``, ``(H,W,1)``, BGR ``(H,W,3)``, не-непрерывные срезы;
* отвергаются (заглушка «Ошибка кадра», процесс жив): BGRA, uint16, float32, ndim 4, ndim 1;
* ``None`` и пустой массив: заглушка «Нет сигнала»;
* счётчики ``ImagePanelPresenter.frame_stats(slot_id)`` -> ``{"received","shown","rejected"}``;
* на отвергнутый кадр одна строка WARNING с «ожидали» и «пришло» (shape, dtype, nbytes);
  сто одинаковых подряд — одна строка, ``rejected == 100``.

Каждый кейс идёт в ОТДЕЛЬНОМ подпроцессе (offscreen Qt), с дедлайном: нативное падение
(0xC0000005) или зависание становится красным тестом, а не убивает pytest. Результат ребёнок
печатает одной JSON-строкой ``RESULT:``; ожидаемые значения здесь записаны литералами.

Запуск:
    python -m pytest multiprocess_prototype/frontend/widgets/image_panel/tests/test_frame_guard_contract.py -q
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from functools import lru_cache
from pathlib import Path

import pytest

# Корень проекта, в котором крутятся дети. FRAME_GUARD_ROOT — только для прогона теста против другого дерева.
_ROOT = Path(os.environ.get("FRAME_GUARD_ROOT") or Path(__file__).resolve().parents[5])
_DEADLINE_S = 60

_H, _W = 1024, 1280

# Текст заглушек (литералы контракта).
_PLACEHOLDER_REJECT = "Ошибка кадра"
_PLACEHOLDER_NO_SIGNAL = "Нет сигнала"

_RECEIVED, _SHOWN, _REJ = "received", "shown", "rejected"

# ---------------------------------------------------------------------------
# Ребёнок. Только ASCII: код идёт через ``python -c`` (командная строка Windows).
# ---------------------------------------------------------------------------
_CHILD = r"""
import faulthandler, json, logging, sys
faulthandler.enable()
import numpy as np
from PySide6.QtWidgets import QApplication

spec = json.loads(sys.argv[1])
kind, count = spec["kind"], spec["count"]
H, W = spec["h"], spec["w"]


def build(kind):
    if kind == "none":
        return None
    if kind == "gray":
        f = np.zeros((H, W), dtype=np.uint8)
        f[:, W // 2:] = 255
        return f
    if kind == "gray_c1":
        f = np.zeros((H, W, 1), dtype=np.uint8)
        f[:, W // 2:, 0] = 255
        return f
    if kind == "bgr":
        f = np.zeros((H, W, 3), dtype=np.uint8)
        f[:, : W // 2, 0] = 255
        f[:, W // 2:, 2] = 255
        return f
    if kind == "gray_strided":
        base = np.zeros((H, 2 * W), dtype=np.uint8)
        base[:, W:] = 255
        return base[:, ::2]
    if kind == "bgr_strided":
        base = np.zeros((H, 2 * W, 3), dtype=np.uint8)
        base[:, : W, 0] = 255
        base[:, W:, 2] = 255
        return base[:, ::2, :]
    if kind == "bgra":
        return np.zeros((H, W, 4), dtype=np.uint8)
    if kind == "u16_gray":
        return np.zeros((H, W), dtype=np.uint16)
    if kind == "f32_gray":
        return np.zeros((H, W), dtype=np.float32)
    if kind == "f32_bgr":
        return np.zeros((H, W, 3), dtype=np.float32)
    if kind == "ndim4":
        return np.zeros((1, H, W, 3), dtype=np.uint8)
    if kind == "ndim1":
        return np.zeros((H * W,), dtype=np.uint8)
    if kind == "empty_2d":
        return np.zeros((0, W), dtype=np.uint8)
    if kind == "empty_1d":
        return np.zeros((0,), dtype=np.uint8)
    if kind == "huge_gray":
        return np.zeros((8192, 8192), dtype=np.uint8)
    raise SystemExit("unknown kind " + kind)


class Cap(logging.Handler):
    def __init__(self):
        logging.Handler.__init__(self, logging.DEBUG)
        self.records = []

    def emit(self, record):
        try:
            msg = record.getMessage()
        except Exception as exc:  # broken format string is a result, not a crash of the harness
            msg = "<getMessage failed: %r>" % (exc,)
        self.records.append({"level": record.levelname, "logger": record.name, "msg": msg})


cap = Cap()
logging.getLogger().addHandler(cap)

# Self-test of the capture path: the same facade the presenter module uses.
from multiprocess_framework.modules.logger_module import get_std_logger
get_std_logger("multiprocess_prototype.frontend.widgets.image_panel.presenter").warning("__selftest__")
capture_ok = any("__selftest__" in r["msg"] for r in cap.records)
cap.records = [r for r in cap.records if "__selftest__" not in r["msg"]]

from multiprocess_prototype.frontend.widgets.image_panel.widget import ImagePanelWidget

app = QApplication([])
w = ImagePanelWidget()
w.set_displays([{"id": "main", "label": "Main", "enabled": True, "x": 0, "y": 0}])

frame = build(kind)
contiguous = None if frame is None else bool(frame.flags["C_CONTIGUOUS"])
shape = None if frame is None else list(frame.shape)

for _ in range(count):
    w.display_frame("main", frame)
app.processEvents()

label = w._presenter._slots["main"]._label
pm = label.pixmap()
pixmap_null = pm is None or pm.isNull()
left = right = None
if not pixmap_null:
    img = pm.toImage()
    y = img.height() // 2
    cl = img.pixelColor(int(img.width() * 0.1), y)
    cr = img.pixelColor(int(img.width() * 0.9), y)
    left = [cl.red(), cl.green(), cl.blue()]
    right = [cr.red(), cr.green(), cr.blue()]

stats, stats_error = None, None
try:
    stats = w._presenter.frame_stats("main")
    stats = {str(k): v for k, v in dict(stats).items()}
    stats_types = {k: type(v).__name__ for k, v in stats.items()}
except Exception as exc:
    stats_error = "%s: %s" % (type(exc).__name__, exc)
    stats_types = None

print("RESULT:" + json.dumps({
    "text": label.text(),
    "pixmap_null": pixmap_null,
    "left": left,
    "right": right,
    "contiguous": contiguous,
    "shape": shape,
    "stats": stats,
    "stats_types": stats_types,
    "stats_error": stats_error,
    "log": cap.records,
    "capture_ok": capture_ok,
}))
sys.stdout.flush()
"""

# Что принимается: ключ -> ожидаемые цвета (RGB) у 10% и 90% ширины показанной картинки.
_BLACK, _WHITE = [0, 0, 0], [255, 255, 255]
_BLUE, _RED = [0, 0, 255], [255, 0, 0]  # BGR-кадр: слева синий канал, справа красный
_ACCEPTED = {
    "gray": (_BLACK, _WHITE),
    "gray_c1": (_BLACK, _WHITE),
    "bgr": (_BLUE, _RED),
    "gray_strided": (_BLACK, _WHITE),
    "bgr_strided": (_BLUE, _RED),
}

# Что отвергается: ключ -> (shape как печатает numpy, dtype, nbytes). Все литералы.
_REJECTED = {
    "bgra": ("(1024, 1280, 4)", "uint8", "5242880"),
    "u16_gray": ("(1024, 1280)", "uint16", "2621440"),
    "f32_gray": ("(1024, 1280)", "float32", "5242880"),
    "f32_bgr": ("(1024, 1280, 3)", "float32", "15728640"),
    "ndim4": ("(1, 1024, 1280, 3)", "uint8", "3932160"),
    "ndim1": ("(1310720,)", "uint8", "1310720"),
}

_NO_SIGNAL = ("none", "empty_2d", "empty_1d")


@lru_cache(maxsize=None)
def _run(kind: str, count: int = 1, h: int = _H, w: int = _W) -> dict:
    """Один кейс в отдельном процессе. Дедлайн, код выхода и хвост stderr — в результат."""
    env = dict(os.environ)
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["PYTHONUTF8"] = "1"
    env["PYTHONPATH"] = str(_ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    spec = json.dumps({"kind": kind, "count": count, "h": h, "w": w})
    out: dict = {"timeout": False, "returncode": None, "stderr_tail": "", "result": None}
    try:
        proc = subprocess.run(
            [sys.executable, "-c", _CHILD, spec],
            cwd=str(_ROOT),
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=_DEADLINE_S,
        )
    except subprocess.TimeoutExpired:
        out["timeout"] = True
        return out
    out["returncode"] = proc.returncode
    out["stderr_tail"] = proc.stderr[-1500:]
    for line in proc.stdout.splitlines():
        if line.startswith("RESULT:"):
            out["result"] = json.loads(line[len("RESULT:") :])
    return out


def _alive(case: dict, what: str) -> dict:
    """Процесс дожил до отчёта: не таймаут, код 0, результат получен. Возвращает result."""
    assert not case["timeout"], f"{what}: подпроцесс не уложился в {_DEADLINE_S} с (зависание)"
    assert case["returncode"] == 0, (
        f"{what}: подпроцесс упал, код выхода {case['returncode']!r} "
        f"(3221225477 = 0xC0000005)\nstderr: {case['stderr_tail']}"
    )
    assert case["result"] is not None, f"{what}: ребёнок не напечатал RESULT\nstderr: {case['stderr_tail']}"
    return case["result"]


def _guard_lines(result: dict) -> list[dict]:
    """Строки лога, похожие на сообщение защиты: «ожидали» и «пришло» (регистр не важен)."""
    return [r for r in result["log"] if "ожидали" in r["msg"].lower() and "пришло" in r["msg"].lower()]


def _stats_ok(result: dict, what: str) -> dict:
    assert result["stats_error"] is None, f"{what}: frame_stats('main') -> {result['stats_error']}"
    stats = result["stats"]
    for key in (_RECEIVED, _SHOWN, _REJ):
        assert key in stats, f"{what}: в frame_stats нет ключа {key!r}: {stats}"
        assert result["stats_types"][key] == "int", f"{what}: {key} не int: {result['stats_types']}"
    return stats


# ---------------------------------------------------------------------------
# Принимаемые кадры
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("kind", sorted(_ACCEPTED))
def test_принятый_кадр_показан_процесс_жив(kind: str) -> None:
    """СТОРОЖ (может быть зелёным до реализации): допустимый кадр показан верно."""
    result = _alive(_run(kind), kind)
    left, right = _ACCEPTED[kind]

    assert result["pixmap_null"] is False, f"{kind}: pixmap пуст, text={result['text']!r}"
    assert result["text"] == ""
    assert result["left"] == left
    assert result["right"] == right


@pytest.mark.parametrize("kind", ["gray_strided", "bgr_strided"])
def test_срез_кейс_действительно_не_непрерывный(kind: str) -> None:
    """Валидность самого теста: срез ``frame[:, ::2]`` и правда не C-contiguous."""
    result = _alive(_run(kind), kind)

    assert result["contiguous"] is False


@pytest.mark.parametrize("kind", sorted(_ACCEPTED))
def test_принятый_кадр_считается_показанным(kind: str) -> None:
    result = _alive(_run(kind), kind)

    stats = _stats_ok(result, kind)
    assert (stats[_RECEIVED], stats[_SHOWN], stats[_REJ]) == (1, 1, 0)


@pytest.mark.parametrize("kind", sorted(_ACCEPTED))
def test_принятый_кадр_не_пишет_предупреждений_защиты(kind: str) -> None:
    result = _alive(_run(kind), kind)

    assert result["capture_ok"] is True, "перехват логов в подпроцессе не работает"
    assert _guard_lines(result) == []


# ---------------------------------------------------------------------------
# Отвергаемые кадры
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("kind", sorted(_REJECTED))
def test_отвергнутый_кадр_даёт_заглушку_ошибка_кадра(kind: str) -> None:
    result = _alive(_run(kind), kind)

    assert result["text"] == _PLACEHOLDER_REJECT


@pytest.mark.parametrize("kind", sorted(_REJECTED))
def test_отвергнутый_кадр_считается_отброшенным(kind: str) -> None:
    result = _alive(_run(kind), kind)

    stats = _stats_ok(result, kind)
    assert (stats[_RECEIVED], stats[_SHOWN], stats[_REJ]) == (1, 0, 1)


@pytest.mark.parametrize("kind", sorted(_REJECTED))
def test_отвергнутый_кадр_пишет_ровно_одну_строку_warning(kind: str) -> None:
    result = _alive(_run(kind), kind)

    assert result["capture_ok"] is True, "перехват логов в подпроцессе не работает"
    lines = _guard_lines(result)
    assert len(lines) == 1, f"{kind}: строк с «ожидали»/«пришло»: {len(lines)}; весь лог: {result['log']}"
    assert lines[0]["level"] == "WARNING"


@pytest.mark.parametrize("kind", sorted(_REJECTED))
def test_строка_про_отвергнутый_кадр_называет_shape_и_dtype(kind: str) -> None:
    shape, dtype, _ = _REJECTED[kind]
    result = _alive(_run(kind), kind)

    lines = _guard_lines(result)
    assert lines, f"{kind}: нет строки с «ожидали»/«пришло»; весь лог: {result['log']}"
    msg = lines[0]["msg"]
    came = msg[msg.lower().index("пришло") :]
    assert shape in came, f"{kind}: shape {shape!r} не после «пришло»: {msg!r}"
    assert dtype in came, f"{kind}: dtype {dtype!r} не после «пришло»: {msg!r}"


@pytest.mark.parametrize("kind", sorted(_REJECTED))
def test_строка_про_отвергнутый_кадр_называет_nbytes(kind: str) -> None:
    _, _, nbytes = _REJECTED[kind]
    result = _alive(_run(kind), kind)

    lines = _guard_lines(result)
    assert lines, f"{kind}: нет строки с «ожидали»/«пришло»; весь лог: {result['log']}"
    msg = lines[0]["msg"]
    assert nbytes in msg[msg.lower().index("пришло") :], f"{kind}: nbytes {nbytes} не после «пришло»: {msg!r}"


def test_сто_одинаковых_отвергнутых_кадров_дают_одну_строку_и_счётчик_сто() -> None:
    result = _alive(_run("bgra", count=100), "bgra x100")

    assert result["capture_ok"] is True, "перехват логов в подпроцессе не работает"
    stats = _stats_ok(result, "bgra x100")
    assert (stats[_RECEIVED], stats[_SHOWN], stats[_REJ]) == (100, 0, 100)
    lines = _guard_lines(result)
    assert len(lines) == 1, f"строк с «ожидали»/«пришло»: {len(lines)} (ждали ровно 1)"


# ---------------------------------------------------------------------------
# None и пустой кадр: «Нет сигнала», прежнее поведение
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("kind", _NO_SIGNAL)
def test_пустой_кадр_даёт_заглушку_нет_сигнала(kind: str) -> None:
    """СТОРОЖ (может быть зелёным до реализации): прежнее поведение сохранено."""
    result = _alive(_run(kind), kind)

    assert result["text"] == _PLACEHOLDER_NO_SIGNAL


@pytest.mark.parametrize("kind", _NO_SIGNAL)
def test_пустой_кадр_считается_принятым_но_не_показанным_и_не_отброшенным(kind: str) -> None:
    result = _alive(_run(kind), kind)

    stats = _stats_ok(result, kind)
    assert (stats[_RECEIVED], stats[_SHOWN], stats[_REJ]) == (1, 0, 0)


# ---------------------------------------------------------------------------
# Очень большой кадр
# ---------------------------------------------------------------------------
def test_огромный_кадр_8192x8192_не_роняет_процесс() -> None:
    """Показан или отвергнут — не важно, важно: код выхода 0 и слот в одном из двух состояний."""
    result = _alive(_run("huge_gray", h=8192, w=8192), "huge_gray 8192x8192")

    assert result["text"] in ("", _PLACEHOLDER_REJECT)


def test_огромный_кадр_8192x8192_учтён_счётчиками() -> None:
    result = _alive(_run("huge_gray", h=8192, w=8192), "huge_gray 8192x8192")

    stats = _stats_ok(result, "huge_gray 8192x8192")
    assert stats[_RECEIVED] == 1
    assert stats[_SHOWN] + stats[_REJ] == 1
