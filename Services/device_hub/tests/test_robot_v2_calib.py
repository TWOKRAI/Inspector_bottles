"""Тесты автора T5.4c: команды ``calib_belt``, ``calib_frame``, ``calib_tools`` (драйвер v2 и операции данных).

Purpose:
    Приёмка (``Plugins/hub/device_hub/tests/test_t54_calib_commands_acceptance.py``) пишется слепо; здесь — то, что
    видно только автору: запись двух параметров ленты одним захватом ``_param_lock`` (откат первой записи при NAK
    второй), ошибка хранилища на второй записи БЕЗ отката (метки расходятся, тик возвращает роботу значения файла),
    ``base_rev`` сверяется первой даже когда записывать нечего, ``dry_run`` ничего не трогает, офлайн-операции данных
    ``calib_frame`` / ``calib_tools`` на временном хранилище.
    Швы только публичные: ``client_factory`` драйвера (подкласс ``RobotClientV2`` с NAK на ``param_set``),
    ``monkeypatch.setattr`` на ``save_params`` модуля ``robot_driver_v2.params``, ``drv.tick``; новых строк в
    ``_SEAMS`` сторожа ``test_no_private_driver_state.py`` нет.

Public API:
    Только тесты ``test_*``.

Stability: lite
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest

from multiprocess_framework.modules.base_manager import open_scope

from Services.device_hub.manager import DeviceManager
from Services.device_hub.robot_data_ops import run_op
from Services.robot_comm.core.client_v2 import RobotClientV2
from Services.robot_comm.core.registers import ROBOT_UNIT_ID
from Services.robot_comm.errors import RobotNak
from Services.robot_comm.programs.program import FrameDef
from Services.robot_comm.robot_data import load_frames, load_params, load_points
from Services.robot_comm.store import RobotDataStore
from Services.robot_comm.tests.e2e_rig_v2 import E2eRig, bounded

DEV = "rob_v2"
TEXT_BAD_ARGS = "неверные аргументы команды робота"
TEXT_SHORT = "мало хода ленты между отметками"
TEXT_OFF_AXIS = "лента не вдоль оси робота"
TEXT_NO_ENCODER = "энкодер не изменился между отметками"
TEXT_STORE_ERROR = "ошибка хранилища данных робота"
TEXT_HALF = "калибровка ленты записана не полностью"
TEXT_NOT_APPLIED = "параметры ленты записаны, применение не прошло — повторите применение"
TEXT_SYNCING = "идёт синхронизация параметров"
TEXT_BAD_MARKS = "неверные отметки ленты"
TEXT_FACTOR_RANGE = "коэффициент ленты вне диапазона параметра"
TEXT_NO_POINT = "точка не найдена"
TEXT_IN_BASE = "точка СК должна быть в базе"
TEXT_FRAME_BAD_POINTS = "неверные точки подгонки СК"
_FACTOR = "P_BELT_FACTOR"
_DIR = "P_BELT_DIR"
_DEFAULT_FACTOR = 14447
_DEFAULT_DIR = 1
_TICK_DEADLINE_S = 10.0

# Отметки: ход +Y на 200 мм за 1384 импульса (14451 = round(200 / 1384 * 1e5)), ось 1 — по умолчанию
_PLUS_Y = [{"x_mm": 250.0, "y_mm": -100.0, "encoder": 1000}, {"x_mm": 250.0, "y_mm": 100.0, "encoder": 2384}]
# Ход по -X на 200 мм за 1384 импульса: ось 2
_MINUS_X = [{"x_mm": 300.0, "y_mm": 0.0, "encoder": 1000}, {"x_mm": 100.0, "y_mm": 0.0, "encoder": 2384}]
# Ход +Y на 144.47 мм за 1000 импульсов: ось 1 и коэффициент 14447 — как умолчания робота, записывать нечего
_NOOP = [{"x_mm": 250.0, "y_mm": 0.0, "encoder": 0}, {"x_mm": 250.0, "y_mm": 144.47, "encoder": 1000}]

_SCOPE: Any = None


@pytest.fixture(autouse=True)
def driver_scope() -> Iterator[Any]:
    global _SCOPE
    scope = open_scope("rv2calib", budget_s=6.0)
    _SCOPE = scope
    try:
        yield scope
    finally:
        _SCOPE = None
        report = scope.close()
        assert list(report.survivors) == [], f"выжившие потоки области теста: {list(report.survivors)}"


class _FaultClient(RobotClientV2):
    """Клиент с крючками на ``param_set`` / ``param_apply`` (шов ``client_factory``): крючок бросает исключение
    или ждёт событие ДО вызова настоящего метода. Крючки — атрибуты класса, ``_hub`` сбрасывает их при выходе."""

    set_hook: Callable[[str, int], None] | None = None
    apply_hook: Callable[[], None] | None = None

    def param_set(self, name: str, raw: int) -> Any:
        if _FaultClient.set_hook is not None:
            _FaultClient.set_hook(name, raw)
        return super().param_set(name, raw)

    def param_apply(self) -> Any:
        if _FaultClient.apply_hook is not None:
            _FaultClient.apply_hook()
        return super().param_apply()


def _nak(*_args: Any) -> None:
    raise RobotNak(1, None, "nak", None, ())


class _Hub:
    def __init__(self, mgr: DeviceManager, rig: E2eRig, drv: Any, store: RobotDataStore, errors: list[Any]) -> None:
        self.mgr, self.rig, self.drv, self.store, self.errors = mgr, rig, drv, store, errors
        self._mark = len(rig.core.events())  # записи sim при подключении (sync_params пишет все параметры) — не в счёт

    def call(self, op: str, args: dict) -> dict:
        return bounded(lambda: self.mgr.call(DEV, op, dict(args)), 15.0)

    def belt(self, marks: list[dict], **extra: Any) -> dict:
        """``calib_belt`` с ``base_rev`` из файла (если не задан в ``extra``)."""
        args = {"marks": marks, "base_rev": self.file_rev(), **extra}
        return self.call("calib_belt", args)

    def robot(self, name: str) -> int:
        return bounded(lambda: self.rig.client.param_get(name))

    def robot_belt(self) -> tuple[int, int]:
        return self.robot(_FACTOR), self.robot(_DIR)

    def file_rev(self) -> str | None:
        return load_params(self.store, DEV).rev

    def file_belt(self) -> tuple[int, int]:
        values = load_params(self.store, DEV).values
        return values[_FACTOR], values[_DIR]

    def sim_texts(self) -> list[str]:
        return [text for _stamp, text in self.rig.core.events()[self._mark :]]

    def count(self, needle: str) -> int:
        return len([t for t in self.sim_texts() if needle in t])


@contextmanager
def _hub(tmp_path: Path, client_factory: Callable[..., Any] = RobotClientV2) -> Iterator[_Hub]:
    """Менеджер с драйвером v2 над ``E2eRig``; тик НЕ идёт сам: тест зовёт ``drv.tick`` явно."""
    store = RobotDataStore(tmp_path / "robot")
    errors: list[Any] = []

    def publish(path: str, payload: Any) -> None:
        if path.endswith(".last_error"):
            errors.append(payload)

    mgr = DeviceManager(
        store=None,
        publish_cb=publish,
        spawn=_SCOPE.spawn,
        robot_store=store,
        driver_options={("robot", "delta_v2"): {"client_factory": client_factory}},
    )
    with E2eRig() as rig:
        mgr.upsert(
            {
                "id": DEV,
                "name": DEV,
                "kind": "robot",
                "protocol": "delta_v2",
                "transport": {"type": "tcp", "host": "127.0.0.1", "port": rig.port, "unit_id": ROBOT_UNIT_ID},
            }
        )
        try:
            assert bounded(lambda: mgr.connect(DEV), 60.0) is True
            yield _Hub(mgr, rig, mgr.get_driver(DEV), store, errors)
        finally:
            _FaultClient.set_hook = _FaultClient.apply_hook = None  # отключение не должно идти через крючки
            try:
                bounded(lambda: mgr.disconnect(DEV), 15.0)
            except Exception:  # noqa: BLE001 — уборка не подменяет исключение теста
                pass


def _until(cond: Callable[[], bool], deadline_s: float, what: str) -> None:
    end = time.monotonic() + deadline_s
    while time.monotonic() < end:
        if cond():
            return
        time.sleep(0.05)
    raise AssertionError(f"не дождались: {what}")


# --------------------------------------------------------------------------------------------------
# calib_belt: драйвер v2 против sim
# --------------------------------------------------------------------------------------------------


def test_calib_belt_writes_and_applies_on_sim(tmp_path: Path) -> None:
    """R1: ход +Y (ось по умолчанию) -> пишется один P_BELT_FACTOR, PARAM_APPLY снимает TLM_CFG_PENDING."""
    from Services.robot_comm.core.protocol_v2 import REG

    with _hub(tmp_path) as hub:
        answer = hub.belt(_PLUS_Y)
        assert answer["status"] == "ok", answer
        assert answer["written"] == [_FACTOR]
        assert answer["applied"] is True
        assert answer["direction"] == 1
        assert answer["raw_factor"] == 14451
        assert answer["delta_enc"] == 1384
        assert answer["rev"] == hub.file_rev()
        assert hub.robot(_FACTOR) == 14451
        assert hub.rig.core.regs[REG["TLM_CFG_PENDING"]] == 0
        assert hub.file_belt() == (14451, _DEFAULT_DIR)


def test_calib_belt_axis_change_writes_both(tmp_path: Path) -> None:
    """R2: ход по -X -> пишутся P_BELT_DIR и P_BELT_FACTOR (в этом порядке); робот и файл: ось 2."""
    with _hub(tmp_path) as hub:
        answer = hub.belt(_MINUS_X)
        assert answer["status"] == "ok", answer
        assert answer["written"] == [_DIR, _FACTOR]
        assert answer["direction"] == 2
        assert hub.robot_belt() == (14451, 2)
        assert hub.file_belt() == (14451, 2)


def test_calib_belt_dry_run_untouched(tmp_path: Path) -> None:
    """R3: dry_run даёт расчёт, но робот, файл и ревизия остаются прежними."""
    with _hub(tmp_path) as hub:
        rev_before = hub.file_rev()
        writes_before = hub.count("op=PARAM_SET")
        answer = hub.belt(_MINUS_X, dry_run=True)
        assert answer["status"] == "ok", answer
        assert answer["applied"] is False
        assert answer["written"] == []
        assert (answer["direction"], answer["raw_factor"]) == (2, 14451)
        assert hub.robot_belt() == (_DEFAULT_FACTOR, _DEFAULT_DIR)
        assert hub.file_rev() == rev_before
        assert hub.count("op=PARAM_SET") == writes_before
        assert hub.count("op=PARAM_APPLY") == 0


@pytest.mark.parametrize(
    "args",
    [
        {"base_rev": None},
        {"marks": [_PLUS_Y[0]], "base_rev": None},
        {"marks": [{**_PLUS_Y[0], "encoder": 1.0}, _PLUS_Y[1]], "base_rev": None},
        {"marks": [{**_PLUS_Y[0], "encoder": 2**31}, _PLUS_Y[1]], "base_rev": None},
        {"marks": [{**_PLUS_Y[0], "x_mm": True}, _PLUS_Y[1]], "base_rev": None},
        {"marks": [{**_PLUS_Y[0], "x_mm": float("nan")}, _PLUS_Y[1]], "base_rev": None},
        {"marks": _PLUS_Y, "base_rev": None, "dry_run": "yes"},
        {"marks": _PLUS_Y},
    ],
    ids=["no_marks", "one_mark", "float_encoder", "encoder_2_31", "bool_x", "nan_x", "dry_run_str", "no_base_rev"],
)
def test_calib_belt_bad_args_constant_text(tmp_path: Path, args: dict) -> None:
    """R4: плохие аргументы -> постоянный текст, робот не тронут."""
    with _hub(tmp_path) as hub:
        assert hub.call("calib_belt", args) == {"status": "error", "message": TEXT_BAD_ARGS}
        assert hub.robot_belt() == (_DEFAULT_FACTOR, _DEFAULT_DIR)
        assert hub.count("op=PARAM_SET") == 0


@pytest.mark.parametrize(
    ("marks", "text"),
    [
        ([{"x_mm": 250.0, "y_mm": 0.0, "encoder": 0}, {"x_mm": 250.0, "y_mm": 10.0, "encoder": 100}], TEXT_SHORT),
        ([{"x_mm": 250.0, "y_mm": 0.0, "encoder": 0}, {"x_mm": 450.0, "y_mm": 17.5, "encoder": 1384}], TEXT_OFF_AXIS),
        (
            [{"x_mm": 250.0, "y_mm": 0.0, "encoder": 500}, {"x_mm": 250.0, "y_mm": 200.0, "encoder": 500}],
            TEXT_NO_ENCODER,
        ),
    ],
    ids=["short_travel", "angle_5deg", "encoder_unchanged"],
)
def test_calib_belt_refusals_no_writes(tmp_path: Path, marks: list[dict], text: str) -> None:
    """R5: отказы математики -> её текст, ничего не записано, PARAM_APPLY не звался."""
    with _hub(tmp_path) as hub:
        assert hub.belt(marks) == {"status": "error", "message": text}
        assert hub.robot_belt() == (_DEFAULT_FACTOR, _DEFAULT_DIR)
        assert hub.count("op=PARAM_SET") == 0
        assert hub.count("op=PARAM_APPLY") == 0


def test_calib_belt_stale_rev(tmp_path: Path) -> None:
    """R6: чужая base_rev -> current_rev; то же, когда записывать нечего; робот не тронут, PARAM_APPLY не звался."""
    with _hub(tmp_path) as hub:
        assert hub.belt(_PLUS_Y)["status"] == "ok"  # создаёт params.yaml
        rev = hub.file_rev()
        assert rev is not None
        before = (hub.robot_belt(), hub.count("op=PARAM_SET"), hub.count("op=PARAM_APPLY"))

        stale = hub.call("calib_belt", {"marks": _MINUS_X, "base_rev": "чужая"})
        assert stale["status"] == "error", stale
        assert stale["current_rev"] == rev

        # отметки дают текущие значения робота (14451 / ось 1 — после первой калибровки): записывать нечего
        same = [{"x_mm": 250.0, "y_mm": -100.0, "encoder": 1000}, {"x_mm": 250.0, "y_mm": 100.0, "encoder": 2384}]
        nothing = hub.call("calib_belt", {"marks": same, "base_rev": "чужая"})
        assert nothing["status"] == "error", nothing
        assert nothing["current_rev"] == rev

        assert (hub.robot_belt(), hub.count("op=PARAM_SET"), hub.count("op=PARAM_APPLY")) == before
        assert hub.file_rev() == rev


def test_calib_belt_nothing_to_write_still_applies(tmp_path: Path) -> None:
    """Записывать нечего, ревизия верна -> ok, written пуст, rev — текущая, PARAM_APPLY вызван."""
    with _hub(tmp_path) as hub:
        rev = hub.file_rev()
        answer = hub.belt(_NOOP)
        assert answer["status"] == "ok", answer
        assert answer["written"] == []
        assert answer["applied"] is True
        assert answer["rev"] == rev
        assert hub.count("op=PARAM_APPLY") == 1


def test_calib_belt_second_write_nak_rolls_back_first(tmp_path: Path) -> None:
    """R7 (а): NAK на P_BELT_FACTOR после записи P_BELT_DIR -> P_BELT_DIR робота и файла прежний (1), ответ — ошибка."""
    with _hub(tmp_path, client_factory=_FaultClient) as hub:
        _FaultClient.set_hook = lambda name, raw: _nak() if name == _FACTOR else None
        answer = hub.belt(_MINUS_X)
        _FaultClient.set_hook = None
        assert answer == {"status": "error", "message": "nak"}
        assert hub.robot_belt() == (_DEFAULT_FACTOR, _DEFAULT_DIR)
        assert hub.file_belt() == (_DEFAULT_FACTOR, _DEFAULT_DIR)
        assert hub.count("op=PARAM_APPLY") == 0
        assert hub.drv.is_connected  # замок отпущен, драйвер жив
        assert hub.belt(_PLUS_Y)["status"] == "ok"


def test_calib_belt_nak_on_first_write_changes_nothing(tmp_path: Path) -> None:
    """NAK на ПЕРВОЙ записи (P_BELT_DIR): откатывать нечего, робот и файл прежние, PARAM_APPLY не звался, ошибок нет."""
    with _hub(tmp_path, client_factory=_FaultClient) as hub:
        _FaultClient.set_hook = lambda name, raw: _nak() if name == _DIR else None
        answer = hub.belt(_MINUS_X)
        assert answer == {"status": "error", "message": "nak"}
        assert hub.robot_belt() == hub.file_belt() == (_DEFAULT_FACTOR, _DEFAULT_DIR)
        assert hub.count("op=PARAM_SET") == 0
        assert hub.count("op=PARAM_APPLY") == 0
        assert hub.errors == []


def test_calib_belt_nak_and_failed_rollback_reports_half(tmp_path: Path) -> None:
    """NAK на втором шаге И откат первого шага тоже не прошёл: ответ — NAK, last_error заканчивается «записана не
    полностью»; робот и файл одинаковы (P_BELT_DIR уже новый, P_BELT_FACTOR старый)."""
    dir_calls: list[int] = []

    def hook(name: str, raw: int) -> None:
        if name == _FACTOR:
            _nak()
        if name == _DIR:
            dir_calls.append(raw)
            if len(dir_calls) >= 2:  # откат (и его повтор внутри param_set) не доходит до робота
                raise RuntimeError("link")

    with _hub(tmp_path, client_factory=_FaultClient) as hub:
        _FaultClient.set_hook = hook
        answer = hub.belt(_MINUS_X)
        assert answer == {"status": "error", "message": "nak"}
        assert len(dir_calls) >= 2  # откат пробовался
        assert hub.errors[-1] == TEXT_HALF
        assert hub.robot_belt() == hub.file_belt() == (_DEFAULT_FACTOR, 2)
        assert hub.count("op=PARAM_APPLY") == 0


def test_calib_belt_apply_failure_keeps_writes_and_retry_applies(tmp_path: Path) -> None:
    """PARAM_APPLY бросает: ответ — TEXT_BELT_NOT_APPLIED с written из двух параметров, applied False, записи не
    откатываются (робот == файл); повтор с тем же rev -> ok, written пуст, applied True, TLM_CFG_PENDING снят."""
    from Services.robot_comm.core.protocol_v2 import REG

    applies: list[int] = []

    def apply_hook() -> None:
        applies.append(1)
        if len(applies) == 1:
            raise RuntimeError("boom")

    with _hub(tmp_path, client_factory=_FaultClient) as hub:
        _FaultClient.apply_hook = apply_hook
        answer = hub.belt(_MINUS_X)
        assert answer["status"] == "error", answer
        assert answer["message"] == TEXT_NOT_APPLIED
        assert (answer["written"], answer["applied"]) == ([_DIR, _FACTOR], False)
        assert (answer["direction"], answer["raw_factor"]) == (2, 14451)
        assert answer["rev"] == hub.file_rev()
        assert hub.robot_belt() == hub.file_belt() == (14451, 2)
        assert hub.rig.core.regs[REG["TLM_CFG_PENDING"]] == 1

        retry = hub.call("calib_belt", {"marks": _MINUS_X, "base_rev": answer["rev"]})
        assert retry["status"] == "ok", retry
        assert (retry["written"], retry["applied"], retry["rev"]) == ([], True, answer["rev"])
        assert hub.rig.core.regs[REG["TLM_CFG_PENDING"]] == 0
        assert len(applies) == 2


def test_calib_belt_holds_one_lock_over_both_writes(tmp_path: Path) -> None:
    """Оба параметра пишутся под одним захватом _param_lock: пока первый calib_belt стоит на P_BELT_DIR, второй
    calib_belt и param_set получают «идёт синхронизация параметров»; после отпускания робот == файл."""
    entered, release = threading.Event(), threading.Event()

    def hook(name: str, raw: int) -> None:
        if name == _DIR and not entered.is_set():
            entered.set()
            release.wait(15.0)

    with _hub(tmp_path, client_factory=_FaultClient) as hub:
        _FaultClient.set_hook = hook
        first: dict[str, Any] = {}
        worker = threading.Thread(target=lambda: first.update(answer=hub.belt(_MINUS_X)), daemon=True)
        worker.start()
        try:
            assert entered.wait(15.0), "первый calib_belt не дошёл до записи P_BELT_DIR"
            busy = {"status": "error", "message": TEXT_SYNCING}
            assert hub.belt(_PLUS_Y) == busy
            assert hub.call("param_set", {"name": "P_SPD_DEFAULT", "value": 55, "base_rev": None}) == busy
        finally:
            release.set()
            worker.join(15.0)
        assert not worker.is_alive()
        assert first["answer"]["status"] == "ok", first
        assert hub.robot_belt() == hub.file_belt() == (14451, 2)


def test_calib_belt_second_write_store_error_tick_restores(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """R7 (б): сбой хранилища на второй записи -> ответ — ошибка хранилища, last_error — «записана не полностью»;
    откатов нет; один тик возвращает роботу значения файла: P_BELT_DIR == 2 в роботе и файле, P_BELT_FACTOR старый."""
    import Services.device_hub.drivers.robot_driver_v2.params as module

    real_save = module.save_params
    calls: list[int] = []

    def flaky_save(*args: Any, **kwargs: Any) -> str:
        calls.append(1)
        if len(calls) >= 2:
            raise OSError("disk full")
        return real_save(*args, **kwargs)

    with _hub(tmp_path) as hub:
        monkeypatch.setattr(module, "save_params", flaky_save)
        answer = hub.belt(_MINUS_X)
        assert answer == {"status": "error", "message": TEXT_STORE_ERROR}, answer
        assert TEXT_HALF in hub.errors
        assert len(calls) == 2  # откат через сохранение файла не пробовался
        # шаг 1 записан полностью, шаг 2 дошёл до робота, но не до файла
        assert hub.file_belt() == (_DEFAULT_FACTOR, 2)
        assert hub.robot_belt() == (14451, 2)
        monkeypatch.setattr(module, "save_params", real_save)

        def restored() -> bool:
            bounded(lambda: hub.drv.tick(None), 15.0)
            return hub.robot(_FACTOR) == _DEFAULT_FACTOR

        _until(restored, _TICK_DEADLINE_S, "тик вернул роботу P_BELT_FACTOR из файла")
        assert hub.robot_belt() == (_DEFAULT_FACTOR, 2)
        assert hub.file_belt() == (_DEFAULT_FACTOR, 2)


@pytest.mark.parametrize(
    ("marks", "text"),
    [
        ([{"x_mm": 1e308, "y_mm": 0.0, "encoder": 0}, {"x_mm": -1e308, "y_mm": 0.0, "encoder": 1000}], TEXT_BAD_MARKS),
        ([{"x_mm": 0.0, "y_mm": 0.0, "encoder": 0}, {"x_mm": 1e308, "y_mm": 0.0, "encoder": 1}], TEXT_FACTOR_RANGE),
    ],
    ids=["travel_overflows_float", "factor_overflows_float"],
)
def test_calib_belt_float_overflow_gives_constant_text(tmp_path: Path, marks: list[dict], text: str) -> None:
    """Конечные, но огромные отметки: постоянный текст калибровки, не английское «cannot convert float infinity»."""
    with _hub(tmp_path) as hub:
        assert hub.belt(marks) == {"status": "error", "message": text}
        assert hub.robot_belt() == (_DEFAULT_FACTOR, _DEFAULT_DIR)
        assert hub.count("op=PARAM_SET") == 0


# --------------------------------------------------------------------------------------------------
# calib_frame / calib_tools: офлайн-операции данных
# --------------------------------------------------------------------------------------------------

_COS30, _SIN30 = 0.8660254037844386, 0.5
# Углы листа A4: номинал в СК -> положение в базе при повороте 30 градусов и сдвиге (300, -100, -40)
_LOCALS = [[0.0, 0.0, 0.0], [297.0, 0.0, 0.0], [0.0, 210.0, 0.0], [297.0, 210.0, 0.0]]


def _base_of(local: list[float]) -> tuple[float, float, float]:
    x, y, z = local
    return (300.0 + x * _COS30 - y * _SIN30, -100.0 + x * _SIN30 + y * _COS30, -40.0 + z)


def _run(store: RobotDataStore, op: str, args: dict) -> dict:
    return run_op(store, DEV, op, args, {}, log=logging.getLogger("test_calib"))


def _save_point(store: RobotDataStore, name: str, xyz: tuple[float, float, float], frame: str | None = None) -> None:
    rev = load_points(store, DEV)[1]
    point: dict[str, Any] = {"name": name, "x": xyz[0], "y": xyz[1], "z": xyz[2], "rz": 0.0, "hand": 1}
    if frame is not None:
        point["frame"] = frame
    assert _run(store, "point_save", {"point": point, "base_rev": rev})["status"] == "ok"


def _frame_args(store: RobotDataStore, count: int = 4) -> dict:
    return {
        "name": "sheet",
        "points": [{"point": f"s{i}", "local": _LOCALS[i]} for i in range(count)],
        "base_rev": load_frames(store, DEV)[1],
    }


def test_calib_frame_fit_and_save(tmp_path: Path) -> None:
    """R8: подгонка по углам листа -> ok, СК в frames.yaml, to_base(local) рядом с точками; отказы — тексты."""
    store = RobotDataStore(tmp_path / "robot")
    for i, local in enumerate(_LOCALS):
        _save_point(store, f"s{i}", _base_of(local))
    answer = _run(store, "calib_frame", _frame_args(store))
    assert answer["status"] == "ok", answer
    assert isinstance(answer["residuals_mm"], list) and len(answer["residuals_mm"]) == 4
    assert answer["max_residual_mm"] < 0.5
    assert answer["yaw_deg"] == pytest.approx(30.0, abs=0.05)
    frames, rev = load_frames(store, DEV)
    assert rev == answer["rev"]
    assert answer["frame"] == frames["sheet"].to_dict()
    frame = frames["sheet"]
    assert isinstance(frame, FrameDef)
    for i, local in enumerate(_LOCALS):
        got = frame.to_base(local[0], local[1], local[2], 0.0)[:3]
        assert got == pytest.approx(_base_of(local), abs=0.5)


def test_calib_frame_refusals(tmp_path: Path) -> None:
    """R8: нет точки / точка не в базе / чужая ревизия / плохие аргументы — постоянные тексты, файл СК не создан."""
    store = RobotDataStore(tmp_path / "robot")
    for i, local in enumerate(_LOCALS[:3]):
        _save_point(store, f"s{i}", _base_of(local))
    missing = _run(store, "calib_frame", _frame_args(store, count=4))  # s3 не сохранена
    assert missing == {"status": "error", "message": TEXT_NO_POINT}

    _save_point(store, "s3", _base_of(_LOCALS[3]), frame="other")
    assert _run(store, "calib_frame", _frame_args(store, count=4)) == {"status": "error", "message": TEXT_IN_BASE}

    stale = _run(store, "calib_frame", {**_frame_args(store, count=3), "base_rev": "чужая"})
    assert stale["status"] == "error", stale
    assert stale["current_rev"] == load_frames(store, DEV)[1]

    bad = {**_frame_args(store, count=3), "points": _frame_args(store, count=2)["points"]}  # меньше трёх точек
    assert _run(store, "calib_frame", bad) == {"status": "error", "message": TEXT_BAD_ARGS}
    assert _run(
        store, "calib_frame", {**_frame_args(store, count=3), "points": [{"point": "s0", "local": [True, 0, 0]}] * 3}
    ) == {
        "status": "error",
        "message": TEXT_BAD_ARGS,
    }
    assert load_frames(store, DEV)[0] == {}


def test_calib_frame_huge_int_is_bad_args(tmp_path: Path) -> None:
    """local[0] = 10**400 проходит isinstance(Real), но не переводится во float -> TEXT_BAD_ARGS, не OverflowError."""
    store = RobotDataStore(tmp_path / "robot")
    for i, local in enumerate(_LOCALS[:3]):
        _save_point(store, f"s{i}", _base_of(local))
    args = _frame_args(store, count=3)
    args["points"][0]["local"] = [10**400, 0.0, 0.0]
    assert _run(store, "calib_frame", args) == {"status": "error", "message": TEXT_BAD_ARGS}
    assert load_frames(store, DEV)[0] == {}


_REPO_ROOT = Path(__file__).resolve().parents[3]
_OP_CODE = (
    "import json, logging, sys\n"
    "from Services.device_hub.robot_data_ops import run_op\n"
    "from Services.robot_comm.store import RobotDataStore\n"
    "answer = run_op(RobotDataStore(sys.argv[1]), sys.argv[2], 'calib_frame', json.loads(sys.argv[3]), {},\n"
    "                log=logging.getLogger('calib'))\n"
    "print(json.dumps(answer))\n"
)


def _calib_frame_in_subprocess(store_dir: Path, args: dict, deadline_s: float = 10.0) -> dict:
    """``calib_frame`` над готовым хранилищем в дочернем процессе с дедлайном. Поток с join не годится:
    ``np.linalg.svd`` на inf держит GIL и вешает весь прогон; дочерний процесс по дедлайну убивается."""
    env = {**os.environ, "PYTHONPATH": str(_REPO_ROOT)}
    try:
        out = subprocess.run(
            [sys.executable, "-c", _OP_CODE, str(store_dir), DEV, json.dumps(args)],
            capture_output=True,
            text=True,
            timeout=deadline_s,
            stdin=subprocess.DEVNULL,
            check=True,
            cwd=_REPO_ROOT,
            env=env,
        )
    except subprocess.TimeoutExpired:
        pytest.fail(f"calib_frame не вернулся за {deadline_s} с (зависание)")
    return json.loads(out.stdout)


def test_calib_frame_huge_local_is_refused_without_hang(tmp_path: Path) -> None:
    """local = [1e308, 0, 0] (конечное число): fit_frame отказывает «неверные точки», исполнитель не виснет."""
    store = RobotDataStore(tmp_path / "robot")
    for i, local in enumerate(_LOCALS[:3]):
        _save_point(store, f"s{i}", _base_of(local))
    args = _frame_args(store, count=3)
    args["points"][0]["local"] = [1e308, 0.0, 0.0]
    assert _calib_frame_in_subprocess(tmp_path / "robot", args) == {"status": "error", "message": TEXT_FRAME_BAD_POINTS}
    assert load_frames(store, DEV)[0] == {}


def test_calib_frame_huge_saved_point_is_refused_without_hang(tmp_path: Path) -> None:
    """Сохранённая точка с x = 1e308 (point_save её принимает): подгонка отказывает «неверные точки», не виснет."""
    store = RobotDataStore(tmp_path / "robot")
    _save_point(store, "s0", (1e308, 0.0, 0.0))
    for i, local in enumerate(_LOCALS[1:3], start=1):
        _save_point(store, f"s{i}", _base_of(local))
    assert _calib_frame_in_subprocess(tmp_path / "robot", _frame_args(store, count=3)) == {
        "status": "error",
        "message": TEXT_FRAME_BAD_POINTS,
    }
    assert load_frames(store, DEV)[0] == {}


def test_calib_tools_read_only(tmp_path: Path) -> None:
    """R9: у t2 нет t2_exit -> отчёт по двум инструментам; ревизия points.yaml и файлов не изменилась."""
    store = RobotDataStore(tmp_path / "robot")
    for name, z in (("t1_over", 50.0), ("t1_pick", 10.0), ("t1_exit", 30.0), ("t2_over", 50.0), ("t2_pick", 10.0)):
        _save_point(store, name, (100.0, 100.0, z))
    rev = load_points(store, DEV)[1]
    answer = _run(store, "calib_tools", {})
    assert answer == {
        "status": "ok",
        "tools": [
            {"tool": 1, "ok": True, "missing": [], "problems": []},
            {"tool": 2, "ok": False, "missing": ["t2_exit"], "problems": []},
        ],
        "rev": rev,
    }
    assert load_points(store, DEV)[1] == rev
    assert load_frames(store, DEV)[1] is None
