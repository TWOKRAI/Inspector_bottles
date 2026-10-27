"""Слепая живая приёмка T5.3d2: драйвер робота v2 через настоящий backend_ctl (plans/robot-protocol-v2/tasks/T5.3d2.md).

Purpose:
    Три живых теста над ``BackendHarness(with_base=True)`` (процесс ``devices`` поднимается настоящий) и ``E2eRig``
    (sim v2 в процессе теста, по TCP):

    * ``test_backend_ctl_moves_sim`` (REDS 10) — точки, программа, jog, очередь заданий и срок ответа ``robot_stop``
      во время ``robot_jog_release`` (О9) через ``backend_ctl``;
    * ``test_process_stop_one_stop_per_robot`` (RED 16) — остановка процесса ``devices`` при активном подтверждённом
      jog: по одному стопу на робота (допуск гонки «поводок или выключение» ``d1 - L1 in (0, 1)``);
    * ``test_process_stop_after_lease_expiry_stops_standing_robot`` (RED 16b) — удержание пропало за 0,6 с до
      ``process.stop``: поводок закрыл jog (одна строка в логе), выключение остановило стоящего робота (``d1 == 2``).

    Проверяется наблюдаемый эффект: ответы команд, регистр ``STOP_REQ`` у робота (sim событий ``STOP_REQ`` не пишет),
    строки журналов ``<log_dir>/devices/*.log``. Ожидаемые значения — литералы брифа и поправки 2026-10-20.

Public API:
    Только тесты ``test_*``.

Stability: lite

Гейт: каждый тест — ``harness_smoke`` и пропускается без ``DEVICE_HUB_LIVE=1`` (маркера ``live`` в проекте нет).
Запуск: ``DEVICE_HUB_LIVE=1 python -m pytest Services/device_hub/tests/test_robot_v2_live_backend.py -q
-p no:cacheprovider -m harness_smoke``. Живой прогон идёт синхронно, через ворота машины (``machine_gate.sh heavy``).

Допущения теста (не из спеки):
    * Предел ожидания программы ``p1`` до ``done`` — 60 с (бриф срока не задаёт).
    * ``robot_jog_hold`` в шаге 9 REDS 10 и ответ ``robot_stop`` проверяются на ``status == "ok"`` — иначе ответ
      за 1,5 с мог бы быть отказом, а не остановкой.
    * Пауза между ``ok`` держателя меряется по времени ОТПРАВКИ запросов, на которые пришёл ``ok`` (поправка
      2026-10-20, п. 5(в), говорит «пришедший»: по приходу ответа прогон ИНВАЛИДЕН в 2 из 3 живых прогонов — ответ на
      ``jog_hold``, отправленный до ``process.stop``, приходит на ~0,45 с позже, к концу ``process.stop``); пауза по
      приходу ответов идёт в отчёт. Держатель между отправками спит 0,02 с.
"""

from __future__ import annotations

import os
import socket
import threading
import time
from pathlib import Path
from typing import Any

import pytest

from backend_ctl.events import iter_state_deltas
from backend_ctl.harness import BackendHarness
from backend_ctl.protocol import unwrap
from Services.robot_comm.tests.e2e_rig_v2 import E2eRig

pytestmark = [
    pytest.mark.harness_smoke,
    pytest.mark.skipif(
        os.environ.get("DEVICE_HUB_LIVE") != "1",
        reason="живой прогон бэкенда с sim робота — только явно, DEVICE_HUB_LIVE=1",
    ),
]

_CONNECT_DEADLINE_S = 20.0
_PROGRAM_DEADLINE_S = 60.0
_HOLD_GAP_MAX_S = 0.15  # пауза между ok держателя больше — тест ИНВАЛИДЕН
_HOLDER_SLEEP_S = 0.02
_PROCESS_STOP_MAX_S = 2.5
_STOP_REPLY_MAX_S = 1.5

# Строки журнала devices/messages.log (литералы поправки 2026-10-20).
_LINE_L1 = "робот 'r1': jog остановлен поводком: окно удержания истекло"
_LINE_A1 = "робот 'r1': jog остановлен поводком после начала остановки"
_LINE_E1 = "робот 'r1': jog остановлен поводком: область закрывается"
_LINE_INTERRUPTED = "робот 'r1': поводок jog прерван"


def _free_port() -> int:
    """Свободный TCP-порт для backend_ctl (образец ``apps/line_sim/tests/test_f1_task11_acceptance.py:60``)."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _cmd(drv: Any, target: str, command: str, args: dict[str, Any], timeout: float = 10.0) -> dict[str, Any]:
    """Команда процессу, ответ развёрнут до листа хендлера."""
    return unwrap(drv.send_command(target, command, args, timeout=timeout), leaf=True)


def _state_value(drv: Any, path: str) -> Any:
    """``state.get`` пути: значение листа при ``status == "ok"``, иначе ``None`` (пути ещё нет)."""
    leaf = _cmd(drv, "ProcessManager", "state.get", {"path": path}, timeout=5.0)
    if leaf.get("status") == "ok":
        return leaf.get("value")
    return None


def _wait_connected(drv: Any, device_id: str) -> None:
    """Ждать ``devices.state.<id>.conn`` -> ``{"conn": "connected"}`` (дедлайн 20 с, шаг 0,05 с).

    Ответ «Путь не существует» до первой публикации — не ошибка, ждём дальше.
    """
    path = f"devices.state.{device_id}.conn"
    deadline = time.monotonic() + _CONNECT_DEADLINE_S
    last: Any = None
    while time.monotonic() < deadline:
        last = _state_value(drv, path)
        if isinstance(last, dict) and last.get("conn") == "connected":
            return
        time.sleep(0.05)
    pytest.fail(f"{path} не стал connected за {_CONNECT_DEADLINE_S} с, последнее значение: {last!r}")


def _upsert_and_connect(drv: Any, device_id: str, port: int) -> None:
    """``device_upsert`` + ``device_connect`` + ожидание подключения (шаг 3 REDS 10)."""
    up = _cmd(
        drv,
        "devices",
        "device_upsert",
        {
            "id": device_id,
            "name": device_id,
            "kind": "robot",
            "protocol": "delta_v2",
            "transport": {"type": "tcp", "host": "127.0.0.1", "port": port, "unit_id": 2},
        },
    )
    assert up.get("status") == "ok", f"device_upsert {device_id}: {up}"
    con = _cmd(drv, "devices", "device_connect", {"device_id": device_id})
    assert con.get("status") == "ok", f"device_connect {device_id}: {con}"
    assert con.get("conn") == "connecting", f"device_connect {device_id}: ожидалось conn == 'connecting', {con}"
    _wait_connected(drv, device_id)


def _telemetry(drv: Any, device_id: str) -> dict[str, Any]:
    leaf = _cmd(drv, "devices", "robot_get_telemetry", {"device_id": device_id})
    tel = leaf.get("telemetry")
    assert isinstance(tel, dict), f"robot_get_telemetry {device_id}: нет telemetry: {leaf}"
    return tel


def _count_lines(log_dir: Path, needle: str) -> tuple[int, dict[str, int]]:
    """Строки со вхождением ``needle`` во всех ``<log_dir>/devices/*.log``: итог и разбивка по файлам."""
    per_file: dict[str, int] = {}
    for path in sorted((log_dir / "devices").glob("*.log")):
        text = path.read_text(encoding="utf-8", errors="replace")
        n = sum(1 for line in text.splitlines() if needle in line)
        if n:
            per_file[path.name] = n
    return sum(per_file.values()), per_file


class _JogHolder:
    """Поток-держатель: ``robot_jog_hold`` каждые ~0,02 с + ответ, проверка условий достоверности прогона.

    Условия (бриф, шаг 5 и поправка): ответ ``ok``; пауза между соседними ``ok`` не больше 0,15 с; любой не-``ok`` ДО
    отправки ``process.stop`` — предусловие провалено. После отправки (``mark_stop_sending``) не-``ok`` допустимы
    (процесс ``devices`` перестаёт отвечать), но любой ``ok`` после паузы больше 0,15 с — тоже провал предусловия.
    """

    def __init__(self, drv: Any, device_id: str) -> None:
        self._drv = drv
        self._device_id = device_id
        self._halt = threading.Event()
        self._lock = threading.Lock()
        self._ok_times: list[float] = []  # время прихода ответа
        self._ok_sends: list[float] = []  # время отправки запроса, на который пришёл ok
        self._max_arrival_gap = 0.0
        self._problems: list[str] = []
        self._stop_sending_at: float | None = None
        self._non_ok_after_stop = 0
        self._thread = threading.Thread(target=self._run, name="jog-holder", daemon=True)

    # --- жизненный цикл ---

    def start(self) -> None:
        self._thread.start()

    def halt_and_join(self, deadline_s: float = 6.0) -> None:
        self._halt.set()
        self._thread.join(deadline_s)

    def alive(self) -> bool:
        return self._thread.is_alive()

    def mark_stop_sending(self) -> None:
        """Вызвать непосредственно перед отправкой ``process.stop``."""
        with self._lock:
            self._stop_sending_at = time.monotonic()

    # --- наблюдения ---

    @property
    def problems(self) -> list[str]:
        with self._lock:
            return list(self._problems)

    @property
    def ok_count(self) -> int:
        with self._lock:
            return len(self._ok_times)

    @property
    def last_ok(self) -> float | None:
        with self._lock:
            return self._ok_times[-1] if self._ok_times else None

    @property
    def max_arrival_gap_s(self) -> float:
        """Наибольшая пауза между приходами соседних ``ok`` (в отчёт; критерий — пауза между отправками)."""
        with self._lock:
            return self._max_arrival_gap

    @property
    def non_ok_after_stop(self) -> int:
        with self._lock:
            return self._non_ok_after_stop

    def fail_if_invalid(self, numbers: object = None) -> None:
        problems = self.problems
        if problems:
            tail = "" if numbers is None else f"; числа прогона: {numbers}"
            pytest.fail(
                "ТЕСТ ИНВАЛИДЕН (предусловие jog провалено, не красный по продукту): " + "; ".join(problems) + tail
            )

    # --- тело потока ---

    def _run(self) -> None:
        args = {"device_id": self._device_id, "dir": 1, "spd": 20}
        while not self._halt.is_set():
            status: Any
            t_send = time.monotonic()
            try:
                res = self._drv.send_command("devices", "robot_jog_hold", args, timeout=1.0)
                status = unwrap(res, leaf=True).get("status")
            except Exception as exc:  # noqa: BLE001 — исключение отправки = не-ok, классифицируется ниже
                status = f"exception: {exc!r}"
            now = time.monotonic()
            with self._lock:
                after_stop = self._stop_sending_at is not None and now >= self._stop_sending_at
                if status == "ok":
                    if self._ok_times:
                        self._max_arrival_gap = max(self._max_arrival_gap, now - self._ok_times[-1])
                    # пауза меряется между ОТПРАВКАМИ: ответ на jog_hold, отправленный до process.stop, может прийти
                    # поздно (PM занят остановкой процесса), JOG_CONT при этом ушёл вовремя
                    if self._ok_sends and t_send - self._ok_sends[-1] > _HOLD_GAP_MAX_S:
                        where = "после отправки process.stop" if after_stop else "до process.stop"
                        self._problems.append(
                            f"пауза между отправками jog_hold с ok {t_send - self._ok_sends[-1]:.3f} с "
                            f"> {_HOLD_GAP_MAX_S} с ({where})"
                        )
                    self._ok_times.append(now)
                    self._ok_sends.append(t_send)
                elif after_stop:
                    self._non_ok_after_stop += 1
                else:
                    self._problems.append(f"ответ jog_hold не ok до process.stop: {status!r}")
            self._halt.wait(_HOLDER_SLEEP_S)


def _wait_first_ok(holder: _JogHolder, deadline_s: float = 3.0) -> None:
    """Первый ``ok`` держателя доказывает достижимость ``robot_jog_hold`` (не «No handler for key»)."""
    deadline = time.monotonic() + deadline_s
    while time.monotonic() < deadline:
        holder.fail_if_invalid()
        if holder.ok_count >= 1:
            return
        time.sleep(0.02)
    holder.fail_if_invalid()
    pytest.fail(f"робот не ответил ok на robot_jog_hold за {deadline_s} с")


def _wait_moving(drv: Any, holder: _JogHolder, device_id: str, deadline_s: float = 3.0) -> None:
    """Ждать ``telemetry["moving"] is True`` при работающем держателе (дедлайн 3 с)."""
    deadline = time.monotonic() + deadline_s
    last: Any = None
    while time.monotonic() < deadline:
        holder.fail_if_invalid()
        last = _telemetry(drv, device_id).get("moving")
        if last is True:
            return
        time.sleep(0.05)
    holder.fail_if_invalid()
    pytest.fail(f"telemetry['moving'] не стал True за {deadline_s} с, последнее: {last!r}")


def _process_stop(drv: Any) -> float:
    """``process.stop devices`` -> ``success is True``, возвращает время ответа PM, с."""
    t0 = time.monotonic()
    res = drv.send_command("ProcessManager", "process.stop", {"process_name": "devices"}, timeout=15.0)
    elapsed = time.monotonic() - t0
    leaf = unwrap(res, leaf=True)
    assert leaf.get("success") is True, f"process.stop devices не success: {leaf}"
    return elapsed


def _stop_counters(rig1: E2eRig, rig2: E2eRig) -> tuple[int, int]:
    return rig1.read("STOP_REQ")[0] >> 2, rig2.read("STOP_REQ")[0] >> 2


def _report_numbers(tag: str, numbers: dict[str, Any]) -> None:
    print(f"LIVE-NUMBERS {tag}: " + ", ".join(f"{k}={v}" for k, v in numbers.items()))


# ---------------------------------------------------------------------------------------------------------------
# REDS 10
# ---------------------------------------------------------------------------------------------------------------


def test_backend_ctl_moves_sim(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """REDS 10: через backend_ctl робот в sim ходит (jog, программа), задание принято, ``robot_stop`` <= 1,5 с."""
    data_dir = tmp_path / "data"
    monkeypatch.setenv("INSPECTOR_DATA_DIR", str(data_dir))
    numbers: dict[str, Any] = {}

    with E2eRig() as rig:
        # log_dir вне шага 2 брифа: без него логи уходят в logs/ дерева (82 файла за прогон)
        with BackendHarness(with_base=True, port=_free_port(), log_dir=tmp_path / "logs", ready_timeout=60.0) as drv:
            # шаг 3: реестр и подключение
            _upsert_and_connect(drv, "r1", rig.port)

            # шаг 4: точки a и b (b — поза sim после подъёма)
            first = _cmd(
                drv,
                "devices",
                "robot_point_save",
                {
                    "device_id": "r1",
                    "point": {"name": "a", "x": 400.0, "y": 100.0, "z": -60.0, "rz": 0.0, "hand": 1, "frame": None},
                    "base_rev": None,
                },
            )
            assert first.get("status") == "ok", f"robot_point_save a: {first}"
            second = _cmd(
                drv,
                "devices",
                "robot_point_save",
                {
                    "device_id": "r1",
                    "point": {"name": "b", "x": 300.0, "y": -210.0, "z": -40.0, "rz": -100.0, "hand": 1, "frame": None},
                    "base_rev": first["rev"],
                },
            )
            assert second.get("status") == "ok", f"robot_point_save b: {second}"

            # шаг 5: программа p1
            prog = _cmd(
                drv,
                "devices",
                "robot_program_save",
                {
                    "device_id": "r1",
                    "program": {
                        "name": "p1",
                        "steps": [
                            {"op": "move", "point": "a", "kind": "JOINT"},
                            {"op": "move", "point": "b", "kind": "JOINT"},
                        ],
                    },
                    "base_rev": None,
                },
            )
            assert prog.get("status") == "ok", f"robot_program_save p1: {prog}"

            # шаг 6: jog_step на +10 мм по X
            x_before = _telemetry(drv, "r1")["x_mm"]
            step = _cmd(drv, "devices", "robot_jog_step", {"device_id": "r1", "dx": 10, "dy": 0, "spd": 50})
            assert step.get("status") == "ok", f"robot_jog_step: {step}"
            deadline = time.monotonic() + 5.0
            x_after = x_before
            while time.monotonic() < deadline:
                x_after = _telemetry(drv, "r1")["x_mm"]
                if abs(x_after - (x_before + 10.0)) <= 0.1:
                    break
                time.sleep(0.05)
            numbers["x_before"], numbers["x_after"] = x_before, x_after
            assert x_after == pytest.approx(x_before + 10.0, abs=0.1), (
                f"x_mm после jog_step: до {x_before}, после {x_after}, ожидалось до + 10.0"
            )

            # шаг 7: программа p1 доходит до done, done == total == 2, файл программы есть
            run = _cmd(drv, "devices", "robot_program_run", {"device_id": "r1", "name": "p1"})
            assert run.get("status") == "ok", f"robot_program_run: {run}"
            deadline = time.monotonic() + _PROGRAM_DEADLINE_S
            last_prog: Any = None
            while time.monotonic() < deadline:
                last_prog = _state_value(drv, "devices.state.r1.program")
                if isinstance(last_prog, dict):
                    assert last_prog.get("state") != "error", f"программа p1 упала: {last_prog}"
                    if last_prog.get("state") == "done":
                        break
                time.sleep(0.1)
            numbers["program_final"] = last_prog
            assert isinstance(last_prog, dict) and last_prog.get("state") == "done", (
                f"программа p1 не дошла до done за {_PROGRAM_DEADLINE_S} с: {last_prog!r}"
            )
            assert last_prog.get("done") == 2 and last_prog.get("total") == 2, (
                f"ожидалось done == total == 2, получено {last_prog!r}"
            )
            assert (data_dir / "robot" / "r1" / "programs" / "p1.yaml").is_file(), (
                f"файл программы не найден: {data_dir / 'robot' / 'r1' / 'programs' / 'p1.yaml'}"
            )

            # шаг 8: задание в очередь
            job = _cmd(drv, "devices", "robot_enqueue_job", {"device_id": "r1", "x_mm": 300, "y_mm": -150})
            assert job.get("status") == "ok", f"robot_enqueue_job: {job}"

            # шаг 9 (О9): robot_stop во время robot_jog_release отвечает <= 1,5 с от своей отправки
            hold = _cmd(drv, "devices", "robot_jog_hold", {"device_id": "r1", "dir": 1, "spd": 50})
            assert hold.get("status") == "ok", f"robot_jog_hold: {hold}"

            box: dict[str, Any] = {}
            release_started = threading.Event()

            def do_release() -> None:
                release_started.set()
                try:
                    box["release"] = _cmd(drv, "devices", "robot_jog_release", {"device_id": "r1"})
                except Exception as exc:  # noqa: BLE001 — исключение потока читает тест
                    box["release_exc"] = exc

            def do_stop() -> None:
                release_started.wait(2.0)
                t_send = time.monotonic()
                try:
                    box["stop"] = _cmd(drv, "devices", "robot_stop", {"device_id": "r1", "level": "SOFT"})
                except Exception as exc:  # noqa: BLE001
                    box["stop_exc"] = exc
                box["stop_elapsed"] = time.monotonic() - t_send

            t_rel = threading.Thread(target=do_release, name="live-release", daemon=True)
            t_stop = threading.Thread(target=do_stop, name="live-stop", daemon=True)
            t_rel.start()
            t_stop.start()
            t_rel.join(10.0)
            t_stop.join(10.0)
            assert not t_rel.is_alive() and not t_stop.is_alive(), "robot_jog_release / robot_stop не вернулись за 10 с"
            numbers["stop_reply_s"] = round(box.get("stop_elapsed", -1.0), 3)
            assert "stop_exc" not in box, f"robot_stop бросил: {box.get('stop_exc')!r}"
            assert "release_exc" not in box, f"robot_jog_release бросил: {box.get('release_exc')!r}"
            assert box["stop_elapsed"] <= _STOP_REPLY_MAX_S, (
                f"robot_stop ответил за {box['stop_elapsed']:.3f} с > {_STOP_REPLY_MAX_S} с; "
                f"release: {box.get('release')}"
            )
            assert box["stop"].get("status") == "ok", f"robot_stop: {box['stop']}"
            numbers["release"] = box.get("release")

    _report_numbers("REDS10", numbers)


# ---------------------------------------------------------------------------------------------------------------
# RED 16 / RED 16b
# ---------------------------------------------------------------------------------------------------------------


def _collect_log_numbers(log_dir: Path) -> dict[str, Any]:
    l1, l1_files = _count_lines(log_dir, _LINE_L1)
    a1, a1_files = _count_lines(log_dir, _LINE_A1)
    e1, e1_files = _count_lines(log_dir, _LINE_E1)
    interrupted, interrupted_files = _count_lines(log_dir, _LINE_INTERRUPTED)
    return {
        "L1": l1,
        "A1": a1,
        "E1": e1,
        "interrupted": interrupted,
        "files": {"L1": l1_files, "A1": a1_files, "E1": e1_files, "interrupted": interrupted_files},
    }


def test_process_stop_one_stop_per_robot(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """RED 16: ``process.stop devices`` при подтверждённом jog у r1 и простом r2 -> по одному стопу на робота."""
    monkeypatch.setenv("INSPECTOR_DATA_DIR", str(tmp_path / "data"))
    log_dir = tmp_path / "logs"

    with E2eRig() as rig1, E2eRig() as rig2:
        with BackendHarness(with_base=True, port=_free_port(), log_dir=log_dir, ready_timeout=60.0) as drv:
            _upsert_and_connect(drv, "r1", rig1.port)
            _upsert_and_connect(drv, "r2", rig2.port)
            before1, before2 = _stop_counters(rig1, rig2)

            holder = _JogHolder(drv, "r1")
            holder.start()
            try:
                _wait_first_ok(holder)
                _wait_moving(drv, holder, "r1")
                # (а) после moving is True держатель живёт ещё 1,0 с
                end = time.monotonic() + 1.0
                while time.monotonic() < end:
                    holder.fail_if_invalid()
                    time.sleep(0.05)
                # (б) держатель шлёт и во время process.stop; (в) метки времени ответов копит сам
                holder.mark_stop_sending()
                stop_s = _process_stop(drv)
            finally:
                holder.halt_and_join()

        after1, after2 = _stop_counters(rig1, rig2)
        last1, last2 = rig1.read("STOP_REQ")[0], rig2.read("STOP_REQ")[0]

    d1, d2 = after1 - before1, after2 - before2
    log = _collect_log_numbers(log_dir)
    numbers = {
        "d1": d1,
        "d2": d2,
        "L1": log["L1"],
        "A1": log["A1"],
        "E1": log["E1"],
        "поводок_прерван": log["interrupted"],
        "process_stop_s": round(stop_s, 3),
        "files": log["files"],
        "holder_ok": holder.ok_count,
        "holder_non_ok_after_stop": holder.non_ok_after_stop,
        "max_arrival_gap_s": round(holder.max_arrival_gap_s, 3),
        "level_last_r1": last1 & 3,
        "level_last_r2": last2 & 3,
    }
    _report_numbers("RED16", numbers)
    holder.fail_if_invalid(numbers)

    assert stop_s <= _PROCESS_STOP_MAX_S, f"process.stop devices {stop_s:.3f} с > {_PROCESS_STOP_MAX_S} с; {numbers}"
    assert d2 == 1, f"простой r2: записей STOP_REQ {d2}, ожидалось 1; {numbers}"
    assert log["A1"] == 0, f"A1 (стоп поводка после начала остановки) == {log['A1']}, ожидалось 0; {numbers}"
    assert log["E1"] == 0, f"E1 (стоп поводка: область закрывается) == {log['E1']}, ожидалось 0; {numbers}"
    assert log["L1"] in (0, 1), f"L1 == {log['L1']}, ожидалось 0 или 1; {numbers}"
    assert d1 >= 1, f"r1: записей STOP_REQ {d1}, ожидалось >= 1; {numbers}"
    assert d1 - log["L1"] in (0, 1), f"d1 - L1 == {d1 - log['L1']}, ожидалось 0 или 1; {numbers}"
    assert last1 & 3 == 1, f"уровень последней записи r1 {last1 & 3}, ожидался 1 (SOFT); {numbers}"
    assert last2 & 3 == 1, f"уровень последней записи r2 {last2 & 3}, ожидался 1 (SOFT); {numbers}"


def test_process_stop_after_lease_expiry_stops_standing_robot(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """RED 16b: удержание пропало за 0,6 с до ``process.stop`` -> поводок + стоп выключения стоящему (d1 == 2)."""
    monkeypatch.setenv("INSPECTOR_DATA_DIR", str(tmp_path / "data"))
    log_dir = tmp_path / "logs"

    with E2eRig() as rig1, E2eRig() as rig2:
        with BackendHarness(with_base=True, port=_free_port(), log_dir=log_dir, ready_timeout=60.0) as drv:
            _upsert_and_connect(drv, "r1", rig1.port)
            _upsert_and_connect(drv, "r2", rig2.port)
            before1, before2 = _stop_counters(rig1, rig2)

            holder = _JogHolder(drv, "r1")
            holder.start()
            try:
                _wait_first_ok(holder)
                _wait_moving(drv, holder, "r1")
                end = time.monotonic() + 0.3  # moving is True + 0,3 с, затем держатель замолкает
                while time.monotonic() < end:
                    holder.fail_if_invalid()
                    time.sleep(0.05)
            finally:
                holder.halt_and_join()
            holder.fail_if_invalid()
            assert not holder.alive(), "держатель не остановился за 6 с"
            last_ok = holder.last_ok
            assert last_ok is not None
            # через 0,6 с после последнего ok — process.stop
            time.sleep(max(0.0, last_ok + 0.6 - time.monotonic()))
            gap_s = time.monotonic() - last_ok
            stop_s = _process_stop(drv)

        after1, after2 = _stop_counters(rig1, rig2)
        last1, last2 = rig1.read("STOP_REQ")[0], rig2.read("STOP_REQ")[0]

    d1, d2 = after1 - before1, after2 - before2
    log = _collect_log_numbers(log_dir)
    numbers = {
        "d1": d1,
        "d2": d2,
        "L1": log["L1"],
        "A1": log["A1"],
        "E1": log["E1"],
        "поводок_прерван": log["interrupted"],
        "process_stop_s": round(stop_s, 3),
        "silence_before_stop_s": round(gap_s, 3),
        "files": log["files"],
        "holder_ok": holder.ok_count,
        "max_arrival_gap_s": round(holder.max_arrival_gap_s, 3),
        "level_last_r1": last1 & 3,
        "level_last_r2": last2 & 3,
    }
    _report_numbers("RED16b", numbers)

    assert stop_s <= _PROCESS_STOP_MAX_S, f"process.stop devices {stop_s:.3f} с > {_PROCESS_STOP_MAX_S} с; {numbers}"
    assert log["L1"] == 1, f"L1 (стоп поводка: окно удержания истекло) == {log['L1']}, ожидалось 1; {numbers}"
    assert log["A1"] == 0, f"A1 == {log['A1']}, ожидалось 0; {numbers}"
    assert d1 == 2, f"r1: записей STOP_REQ {d1}, ожидалось 2 (поводок + стоп выключения стоящему); {numbers}"
    assert d2 == 1, f"простой r2: записей STOP_REQ {d2}, ожидалось 1; {numbers}"
    assert last1 & 3 == 1, f"уровень последней записи r1 {last1 & 3}, ожидался 1 (SOFT); {numbers}"
    assert last2 & 3 == 1, f"уровень последней записи r2 {last2 & 3}, ожидался 1 (SOFT); {numbers}"


# ---------------------------------------------------------------------------------------------------------------
# T5.3e.3 (бриф 3a): L1-L3 — robot_park на живом бэкенде (форма RED 16, один робот robot_main)
# ---------------------------------------------------------------------------------------------------------------

_PARK_ID = "robot_main"
_PARK_REPLY_MAX_S = 1.0
_PARK_DONE_MAX_S = 30.0
_PARK_POLL_DEADLINE_S = 40.0
_PARK_ALREADY_MAX_S = 1.5
_READY_DEADLINE_S = 20.0
_LINE_PARK_L1 = "робот 'robot_main': jog остановлен поводком: окно удержания истекло"
_LINE_PARK_A1 = "робот 'robot_main': jog остановлен поводком после начала остановки"
_LINE_PARK_E1 = "робот 'robot_main': jog остановлен поводком: область закрывается"
_LINE_PARK_INTERRUPTED = "робот 'robot_main': поводок jog прерван"


def _connect_ready(drv: Any, port: int) -> int:
    """Подключение и готовность (C-57): ``conn == connected``, затем ``.status`` с ``ts > t_conn``; число попыток.

    ``_upsert_and_connect`` ждёт ``connected``; ``t_conn`` берётся после него (строже спеки: ждём ``.status``, снятый
    уже после ``connected``). Ответы «Путь не существует» / ``No handler for key`` / ``timeout`` — ждать дальше.
    """
    _upsert_and_connect(drv, _PARK_ID, port)
    t_conn = time.time()
    attempts = 0
    deadline = time.monotonic() + _READY_DEADLINE_S
    last: Any = None
    while time.monotonic() < deadline:
        attempts += 1
        try:
            last = _state_value(drv, f"devices.state.{_PARK_ID}.status")
        except Exception:  # noqa: BLE001 — timeout / нет хендлера: ждём дальше
            last = None
        if isinstance(last, dict) and isinstance(last.get("ts"), (int, float)) and last["ts"] > t_conn:
            return attempts
        time.sleep(0.05)
    pytest.fail(f".status с ts > t_conn не появился за {_READY_DEADLINE_S} с, последнее: {last!r}")


class _ParkHolder:
    """Держатель: ``robot_jog_hold`` каждые <= 0,1 с до ``halt_and_join``; копит ``(t_send, status, message)``."""

    def __init__(self, drv: Any) -> None:
        self._drv = drv
        self._halt = threading.Event()
        self._lock = threading.Lock()
        self._results: list[tuple[float, Any, Any]] = []
        self._t_reply: float | None = None
        self._thread = threading.Thread(target=self._run, name="park-holder", daemon=True)

    def _run(self) -> None:
        args = {"device_id": _PARK_ID, "dir": 1, "spd": 20}
        while not self._halt.is_set():
            t_send = time.monotonic()
            try:
                leaf = unwrap(self._drv.send_command("devices", "robot_jog_hold", args, timeout=1.0), leaf=True)
                status, message = leaf.get("status"), leaf.get("message")
            except Exception as exc:  # noqa: BLE001 — не-ok, классифицируется тестом
                status, message = "exception", repr(exc)
            with self._lock:
                self._results.append((t_send, status, message))
            self._halt.wait(0.05)

    def start(self) -> None:
        self._thread.start()

    def halt_and_join(self, deadline_s: float = 6.0) -> None:
        self._halt.set()
        self._thread.join(deadline_s)

    def mark_reply(self) -> None:
        with self._lock:
            self._t_reply = time.monotonic()

    def ok_count(self) -> int:
        with self._lock:
            return sum(1 for _, status, _ in self._results if status == "ok")

    def after_reply(self) -> list[tuple[float, Any, Any]]:
        with self._lock:
            return [r for r in self._results if self._t_reply is not None and r[0] >= self._t_reply]


def _wait_moving_plain(drv: Any, deadline_s: float = 5.0) -> None:
    deadline = time.monotonic() + deadline_s
    last: Any = None
    while time.monotonic() < deadline:
        last = _telemetry(drv, _PARK_ID).get("moving")
        if last is True:
            return
        time.sleep(0.05)
    pytest.fail(f"telemetry['moving'] не стал True за {deadline_s} с, последнее: {last!r}")


def _robot_park(drv: Any) -> tuple[dict[str, Any], float, float]:
    """``robot_park``: ответ-лист (исключение отправки -> ``status: error``), время ответа и момент его прихода."""
    t0 = time.monotonic()
    try:
        reply = _cmd(drv, "devices", "robot_park", {"device_id": _PARK_ID}, timeout=10.0)
    except Exception as exc:  # noqa: BLE001 — команды park нет: красный тест с понятным текстом
        reply = {"status": "error", "message": f"исключение отправки: {exc!r}"}
    t_reply = time.monotonic()
    return reply, t_reply - t0, t_reply


def _assert_park_accepted(reply: dict[str, Any], reply_s: float) -> int:
    assert reply.get("status") == "ok" and reply.get("accepted") is True, f"robot_park не принят: {reply}"
    assert reply_s <= _PARK_REPLY_MAX_S, f"ответ robot_park {reply_s:.3f} с > {_PARK_REPLY_MAX_S} с"
    seq = reply.get("seq")
    assert isinstance(seq, int), f"нет seq в ответе: {reply}"
    return seq


def _poll_park_final(drv: Any, seq: int) -> tuple[dict[str, Any], float]:
    """Опрос ``.park`` до ``value.seq == seq`` и ``state in {done, failed}`` (40 с, шаг 0,05 с): значение и момент."""
    path = f"devices.state.{_PARK_ID}.park"
    deadline = time.monotonic() + _PARK_POLL_DEADLINE_S
    last: Any = None
    while time.monotonic() < deadline:
        last = _state_value(drv, path)
        if isinstance(last, dict) and last.get("seq") == seq and last.get("state") in ("done", "failed"):
            return last, time.monotonic()
        time.sleep(0.05)
    pytest.fail(f"итог park seq={seq} не получен за {_PARK_POLL_DEADLINE_S} с, последнее: {last!r}")


def _park_log_numbers(log_dir: Path) -> dict[str, Any]:
    l1, _ = _count_lines(log_dir, _LINE_PARK_L1)
    a1, _ = _count_lines(log_dir, _LINE_PARK_A1)
    e1, _ = _count_lines(log_dir, _LINE_PARK_E1)
    interrupted, _ = _count_lines(log_dir, _LINE_PARK_INTERRUPTED)
    return {"L1": l1, "A1": a1, "E1": e1, "interrupted": interrupted}


def test_park_then_process_stop_no_lease_soft(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """L1: park при подтверждённом jog, затем ``process.stop``: d1 == 2 (SOFT release и SOFT выключения)."""
    monkeypatch.setenv("INSPECTOR_DATA_DIR", str(tmp_path / "data"))
    log_dir = tmp_path / "logs"
    numbers: dict[str, Any] = {}

    with E2eRig() as rig:
        with BackendHarness(with_base=True, port=_free_port(), log_dir=log_dir, ready_timeout=60.0) as drv:
            numbers["ready_attempts"] = _connect_ready(drv, rig.port)
            before = rig.read("STOP_REQ")[0] >> 2

            holder = _ParkHolder(drv)
            holder.start()
            try:
                deadline = time.monotonic() + 3.0
                while holder.ok_count() < 1 and time.monotonic() < deadline:
                    time.sleep(0.02)
                assert holder.ok_count() >= 1, "робот не ответил ok на robot_jog_hold за 3 с"
                _wait_moving_plain(drv)
                time.sleep(0.3)  # moving is True + 0,3 с
                reply, reply_s, t_reply = _robot_park(drv)
                holder.mark_reply()
                seq = _assert_park_accepted(reply, reply_s)
                final, t_final = _poll_park_final(drv, seq)
                time.sleep(0.2)  # держатель продолжает слать и после итога
                t_before_stop = time.monotonic()
                stop_s = _process_stop(drv)
            finally:
                holder.halt_and_join()

        after_raw = rig.read("STOP_REQ")[0]

    d1 = (after_raw >> 2) - before
    log = _park_log_numbers(log_dir)
    after = holder.after_reply()
    ok_after = [r for r in after if r[1] == "ok"]
    to_final = t_final - t_reply
    numbers.update(
        reply_s=round(reply_s, 3),
        final=final,
        to_final_s=round(to_final, 3),
        final_to_stop_s=round(t_before_stop - t_final, 3),
        d1=d1,
        process_stop_s=round(stop_s, 3),
        holds_after=len(after),
        holds_ok_after=len(ok_after),
        **log,
    )
    _report_numbers("L1", numbers)

    assert final.get("state") == "done", f"итог park: {final}; {numbers}"
    assert final.get("home") == "moved", f"home == {final.get('home')!r}, ожидалось 'moved'; {numbers}"
    assert to_final <= _PARK_DONE_MAX_S, f"итог через {to_final:.3f} с > {_PARK_DONE_MAX_S} с; {numbers}"
    assert len(after) >= 3, f"jog_hold после ответа {len(after)} < 3; {numbers}"
    assert not ok_after, f"jog_hold с ok после ответа: {ok_after}"
    assert log["L1"] == 0, f"L1 == {log['L1']}, ожидалось 0; {numbers}"
    assert log["A1"] == 0, f"A1 == {log['A1']}, ожидалось 0; {numbers}"
    assert log["E1"] == 0, f"E1 == {log['E1']}, ожидалось 0; {numbers}"
    assert d1 == 2, f"d1 == {d1}, ожидалось 2 (SOFT release и SOFT выключения); {numbers}"
    assert after_raw & 3 == 1, f"уровень последней записи {after_raw & 3}, ожидался 1 (SOFT); {numbers}"


def test_park_home_robot_then_process_stop(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """L2: park без jog, серво ON, второй park: ``home == "already"`` за <= 1,5 с; d1 == 1 (только выключение)."""
    monkeypatch.setenv("INSPECTOR_DATA_DIR", str(tmp_path / "data"))
    log_dir = tmp_path / "logs"
    numbers: dict[str, Any] = {}

    with E2eRig() as rig:
        with BackendHarness(with_base=True, port=_free_port(), log_dir=log_dir, ready_timeout=60.0) as drv:
            numbers["ready_attempts"] = _connect_ready(drv, rig.port)
            before = rig.read("STOP_REQ")[0] >> 2

            # робот выводится из дома одной командой jog_step (JOG_STEP — команда mailbox, STOP_REQ не пишет)
            x_before = _telemetry(drv, _PARK_ID)["x_mm"]
            step = _cmd(drv, "devices", "robot_jog_step", {"device_id": _PARK_ID, "dx": 80, "dy": 0, "spd": 50})
            assert step.get("status") == "ok", f"robot_jog_step: {step}"
            deadline = time.monotonic() + 10.0
            tel: dict[str, Any] = {}
            while time.monotonic() < deadline:
                tel = _telemetry(drv, _PARK_ID)
                if abs(tel["x_mm"] - (x_before + 80.0)) <= 0.1 and tel.get("moving") is False:
                    break
                time.sleep(0.05)
            moved = abs(tel["x_mm"] - (x_before + 80.0)) <= 0.1 and tel.get("moving") is False
            assert moved, f"робот не вышел из дома: {tel}"

            reply1, reply1_s, _ = _robot_park(drv)
            seq1 = _assert_park_accepted(reply1, reply1_s)
            final1, _ = _poll_park_final(drv, seq1)
            assert final1.get("state") == "done", f"первый park: {final1}"

            servo = _cmd(drv, "devices", "robot_servo", {"device_id": _PARK_ID, "on": True})
            assert servo.get("status") == "ok", f"robot_servo on: {servo}"

            reply2, reply2_s, t_reply2 = _robot_park(drv)
            seq2 = _assert_park_accepted(reply2, reply2_s)
            assert seq2 != seq1, f"seq второго park совпал с первым: {seq1}"
            final2, t_final2 = _poll_park_final(drv, seq2)
            stop_s = _process_stop(drv)

        after_raw = rig.read("STOP_REQ")[0]

    d1 = (after_raw >> 2) - before
    log = _park_log_numbers(log_dir)
    to_final2 = t_final2 - t_reply2
    numbers.update(
        d1=d1, second_final=final2, second_to_final_s=round(to_final2, 3), process_stop_s=round(stop_s, 3), **log
    )
    _report_numbers("L2", numbers)

    assert final2.get("state") == "done" and final2.get("home") == "already", f"второй park: {final2}; {numbers}"
    assert to_final2 <= _PARK_ALREADY_MAX_S, f"второй итог за {to_final2:.3f} с > {_PARK_ALREADY_MAX_S} с; {numbers}"
    assert d1 == 1, f"d1 == {d1}, ожидалось 1 (только SOFT выключения); {numbers}"
    assert log["L1"] == 0, f"L1 == {log['L1']}, ожидалось 0; {numbers}"


def test_park_running_program_then_process_stop(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """L3: идёт программа пользователя (>= 3 хода), park: дельта ``aborted`` раньше ``park_home``; итог done/moved."""
    monkeypatch.setenv("INSPECTOR_DATA_DIR", str(tmp_path / "data"))
    log_dir = tmp_path / "logs"
    numbers: dict[str, Any] = {}
    deltas: list[tuple[str, Any]] = []
    deltas_lock = threading.Lock()
    prefix = f"devices.state.{_PARK_ID}.program."

    def on_event(msg: Any) -> None:  # reader-поток драйвера: только лёгкая запись
        for delta in iter_state_deltas(msg):
            path = delta.get("path")
            if isinstance(path, str) and path.startswith(prefix):
                with deltas_lock:
                    deltas.append((path, delta.get("new_value")))

    def first_index(leaf: str, value: Any) -> int | None:
        with deltas_lock:
            for i, (path, new_value) in enumerate(deltas):
                if path == prefix + leaf and new_value == value:
                    return i
        return None

    with E2eRig() as rig:
        with BackendHarness(with_base=True, port=_free_port(), log_dir=log_dir, ready_timeout=60.0) as drv:
            numbers["ready_attempts"] = _connect_ready(drv, rig.port)
            before = rig.read("STOP_REQ")[0] >> 2

            point_a = {"name": "a", "x": 400.0, "y": 100.0, "z": -60.0, "rz": 0.0, "hand": 1, "frame": None}
            point_b = {"name": "b", "x": 300.0, "y": -210.0, "z": -40.0, "rz": -100.0, "hand": 1, "frame": None}
            first = _cmd(
                drv, "devices", "robot_point_save", {"device_id": _PARK_ID, "point": point_a, "base_rev": None}
            )
            assert first.get("status") == "ok", f"robot_point_save a: {first}"
            second = _cmd(
                drv, "devices", "robot_point_save", {"device_id": _PARK_ID, "point": point_b, "base_rev": first["rev"]}
            )
            assert second.get("status") == "ok", f"robot_point_save b: {second}"
            steps = [{"op": "move", "point": "a" if i % 2 == 0 else "b", "kind": "JOINT"} for i in range(20)]
            saved = _cmd(
                drv,
                "devices",
                "robot_program_save",
                {"device_id": _PARK_ID, "program": {"name": "p3", "steps": steps}, "base_rev": None},
            )
            assert saved.get("status") == "ok", f"robot_program_save p3: {saved}"
            run = _cmd(drv, "devices", "robot_program_run", {"device_id": _PARK_ID, "name": "p3"})
            assert run.get("status") == "ok", f"robot_program_run: {run}"

            deadline = time.monotonic() + 20.0
            prog: Any = None
            while time.monotonic() < deadline:
                prog = _state_value(drv, f"devices.state.{_PARK_ID}.program")
                if isinstance(prog, dict) and prog.get("state") == "running" and (prog.get("done") or 0) >= 3:
                    break
                time.sleep(0.05)
            running3 = isinstance(prog, dict) and prog.get("state") == "running" and (prog.get("done") or 0) >= 3
            assert running3, f"программа p3 не дошла до 3 ходов в running: {prog!r}"

            drv.subscribe(on_event)
            sub = unwrap(drv.state_subscribe(prefix + "**", timeout=10.0), leaf=True)  # открыта ДО robot_park
            assert sub.get("status") == "ok", f"state_subscribe: {sub}"

            reply, reply_s, _ = _robot_park(drv)
            seq = _assert_park_accepted(reply, reply_s)
            final, _ = _poll_park_final(drv, seq)
            deadline = time.monotonic() + 3.0  # дельты идут отдельным потоком: даём дойти
            while time.monotonic() < deadline and (
                first_index("state", "aborted") is None or first_index("name", "park_home") is None
            ):
                time.sleep(0.05)
            stop_s = _process_stop(drv)

        after_raw = rig.read("STOP_REQ")[0]

    log = _park_log_numbers(log_dir)
    aborted_i, park_i = first_index("state", "aborted"), first_index("name", "park_home")
    with deltas_lock:
        seen = list(deltas)
    numbers.update(d1=(after_raw >> 2) - before, process_stop_s=round(stop_s, 3), final=final, **log)
    _report_numbers("L3", numbers)

    assert final.get("state") == "done" and final.get("home") == "moved", f"итог park: {final}; {numbers}"
    assert aborted_i is not None, f"нет дельты program.state == 'aborted'; дельты: {seen}"
    assert park_i is not None, f"нет дельты program.name == 'park_home'; дельты: {seen}"
    assert aborted_i < park_i, f"aborted ({aborted_i}) не раньше park_home ({park_i}); дельты: {seen}"
    assert log["L1"] == 0, f"L1 == {log['L1']}, ожидалось 0; {numbers}"
    assert log["A1"] == 0, f"A1 == {log['A1']}, ожидалось 0; {numbers}"
