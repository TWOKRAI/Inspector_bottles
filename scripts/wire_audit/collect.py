"""Сборщик живых данных для аудита провода (Task 3b): паспорта сима и журнал сим-робота в JSONL.

Запуск (из корня дерева; сим и прототип поднимает оператор, сборщик их НЕ запускает и НЕ меняет)::

    PYTHONUTF8=1 python -m scripts.wire_audit.collect \\
        --proto-port 8765 --sim-port 8766 --out-dir <каталог> [--period 0.25]

Работает до Ctrl-C или файла ``<out-dir>/STOP``. Только чтение: ``state.get``, ``sim_robot.journal``,
``introspect_registers``, ``robot_param_get_all`` (``P_PICK_RZ``) — никаких записей в сим, прототип и регистры.

Файлы каталога (каждая запись пишется строкой с ``flush``, Ctrl-C данных не теряет):

* ``registers.json`` — регистр ``layout`` для столбца А и ``p_pick_rz_deg`` из параметра робота ``P_PICK_RZ``
  (один раз в начале);
* ``sim_objects.jsonl`` — по одному паспорту на ``object_id`` (при первом появлении: паспорт взятого
  объекта сим удаляет из ``sim.objects``);
* ``sim_journal.jsonl`` — строки журнала сим-робота ``{t, side, text}`` без повторов по ``(t, side, text)``
  (кольцо журнала переполняется за десятки секунд, поэтому опрос каждые 0,25 с);
* ``collect.log`` — ошибки опросов (тип исключения и текст; значений аргументов команд нет);
* ``meta.json`` — параметры запуска и счётчики ``polls, errors, objects, journal_lines`` (при выходе).

Коды выхода: 0 — остановлен штатно, 2 — ошибка аргументов или каталог уже содержит данные сбора,
3 — порт недоступен на старте. Клиент ``backend_ctl`` — ``BackendDriver(port=…)`` + ``connect()``, как в скрипте α;
логика α не используется.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import deque
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any, TextIO

_STOP_FILE = "STOP"
_NAP_STEP_S = 0.05  # шаг сна: STOP-файл замечается за один шаг, а не за весь период
_POLL_TIMEOUT_S = 2.0
_DEFAULT_PERIOD_S = 0.25
_DEFAULT_P_PICK_RZ_DEG = -100.0
_PARAM_ARGS = {"device_id": "robot_main"}  # robot_param_get_all процесса devices (читает и α)
_PARAM_SCALE = 10.0  # raw параметра робота — десятые доли градуса
_PICK_SOURCE = "robot_param_get_all"
_ERR_MSG_LIMIT = 200
# Окно запомненных ключей строк журнала. Кольцо ``wire`` держит 200 строк (``_JOURNAL_WIRE_MAXLEN``
# в robot_host): строка может вернуться в ответе только пока она в кольце, значит 5000 ключей — запас
# в 25 колец, вытесненный ключ уже не встретится. Память ограничена независимо от длительности сбора.
_SEEN_ROWS_WINDOW = 5000
_REGISTER_FIELDS = (
    "first_x",
    "first_y",
    "pitch_mm",
    "disk_radius_mm",
    "line_angle_deg",
    "place_z_mm",
    "pick_z_mm",
    "angle_zero_deg",
    "angle_invert",
    "use_pitch",
    "word_gap_slots",
)
_DATA_FILES = ("sim_objects.jsonl", "sim_journal.jsonl")

type Client = Any  # BackendDriver или его фейк: connect(), close(), send_command(), introspect_registers()


def _res(reply: Any) -> dict:
    """Ответ команды лежит в ``result``; не словарь — пустой словарь."""
    if isinstance(reply, dict):
        inner = reply.get("result")
        return inner if isinstance(inner, dict) else reply
    return {}


def _layout_register(reply: Any) -> dict:
    """Регистр ``word_layout`` из ответа ``introspect_registers``: спуск по ``result`` (до 5 уровней)."""
    node: Any = reply
    for _ in range(5):
        if not isinstance(node, dict):
            return {}
        regs = node.get("registers")
        if isinstance(regs, dict):
            word = regs.get("word_layout")
            return word if isinstance(word, dict) else {}
        node = node.get("result")
    return {}


def format_local_time(epoch_s: float) -> str:
    """Наивное локальное время ``YYYY-MM-DD HH:MM:SS,mmm`` — формат логов прототипа."""
    moment = datetime.fromtimestamp(epoch_s)
    return f"{moment:%Y-%m-%d %H:%M:%S},{moment.microsecond // 1000:03d}"


class _RecentKeys:
    """Множество последних ``size`` ключей: старейший вытесняется при переполнении."""

    def __init__(self, size: int) -> None:
        self._order: deque[Any] = deque(maxlen=size)
        self._keys: set[Any] = set()

    def __contains__(self, key: Any) -> bool:
        return key in self._keys

    def __len__(self) -> int:
        return len(self._keys)

    def add(self, key: Any) -> None:
        if key in self._keys:
            return
        if len(self._order) == self._order.maxlen:
            self._keys.discard(self._order[0])  # deque сам вытеснит его при append
        self._order.append(key)
        self._keys.add(key)


class _JsonlWriter:
    """Построчная запись JSONL с ``flush`` после каждой строки."""

    def __init__(self, path: Path) -> None:
        self._fh: TextIO = path.open("a", encoding="utf-8", newline="\n")

    def write(self, record: dict) -> None:
        self._fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        self._fh.flush()

    def close(self) -> None:
        self._fh.close()


class Collector:
    """Один сбор: два клиента, три файла, счётчики. Часы и сон подставляются (тесты)."""

    def __init__(
        self,
        *,
        out_dir: Path,
        proto: Client,
        sim: Client,
        period: float,
        clock: Callable[[], float],
        sleep: Callable[[float], None],
        wall: Callable[[], float],
    ) -> None:
        self._out_dir = out_dir
        self._proto = proto
        self._sim = sim
        self._period = period
        self._clock = clock
        self._sleep = sleep
        self._wall = wall
        self._objects = _JsonlWriter(out_dir / "sim_objects.jsonl")
        self._journal = _JsonlWriter(out_dir / "sim_journal.jsonl")
        self._log = (out_dir / "collect.log").open("a", encoding="utf-8", newline="\n")
        self._seen_objects: set[str] = set()
        self._seen_rows = _RecentKeys(_SEEN_ROWS_WINDOW)
        self._last_written: tuple[Any, Any] | None = None  # (side, text) последней записанной строки журнала
        self.polls = 0
        self.errors = 0
        self.objects = 0
        self.journal_lines = 0
        self.meta: dict[str, Any] = {}

    # --- файлы ----------------------------------------------------------------------------------------------------
    def _log_error(self, source: str, problem: str) -> None:
        self.errors += 1
        self._log.write(f"{format_local_time(self._wall())} {source}: {problem}\n")
        self._log.flush()

    def _log_exc(self, source: str, exc: BaseException) -> None:
        self._log_error(source, f"{type(exc).__name__}: {str(exc)[:_ERR_MSG_LIMIT]}")

    def write_meta(self) -> None:
        text = json.dumps(self.meta, ensure_ascii=False, indent=2)
        (self._out_dir / "meta.json").write_text(text + "\n", encoding="utf-8")

    def close(self) -> None:
        self.meta.update(polls=self.polls, errors=self.errors, objects=self.objects, journal_lines=self.journal_lines)
        self.write_meta()
        for fh in (self._objects, self._journal):
            fh.close()
        self._log.close()

    # --- один раз в начале ----------------------------------------------------------------------------------------
    def dump_registers(self) -> None:
        """``registers.json``: регистр ``layout`` и ``p_pick_rz_deg`` (параметр робота ``P_PICK_RZ``, иначе −100,0)."""
        try:
            regs = _layout_register(self._proto.introspect_registers("layout", timeout=_POLL_TIMEOUT_S))
        except Exception as exc:  # noqa: BLE001 — сбор живёт дальше, причина уходит в collect.log
            self._log_exc("registers", exc)
            self.meta["registers"] = "error"
            return
        if not regs:
            self._log_error("registers", "регистр word_layout не найден в ответе introspect_registers")
            self.meta["registers"] = "missing"
            return
        out = {key: regs[key] for key in _REGISTER_FIELDS if key in regs}
        out["p_pick_rz_deg"], source = self._read_p_pick_rz()
        self.meta["p_pick_rz_deg_source"] = source
        out["p_pick_rz_source"] = "robot_param_get_all" if source == _PICK_SOURCE else "default"  # шапка аудита
        self.meta["registers"] = "ok"
        self.meta["registers_missing"] = [key for key in _REGISTER_FIELDS if key not in regs]
        (self._out_dir / "registers.json").write_text(
            json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

    def _read_p_pick_rz(self) -> tuple[float, str]:
        """``P_PICK_RZ`` робота: ``robot_param_get_all`` процесса ``devices``, ``raw / 10`` (квант ``WIRE_SCALE``).

        Не регистр ``layout`` (там такого поля нет): та же команда, что читает α. Любая неудача (исключение,
        нет ``params`` или ``raw``) — умолчание −100,0 с пометкой «default» в ``meta.json``, причина в ``collect.log``.
        Только чтение.
        """
        try:
            reply = _res(
                self._proto.send_command("devices", "robot_param_get_all", _PARAM_ARGS, timeout=_POLL_TIMEOUT_S)
            )
            params = reply.get("params")
            entry = params.get("P_PICK_RZ") if isinstance(params, dict) else None
            raw = entry.get("raw") if isinstance(entry, dict) else None
            if isinstance(raw, int | float) and not isinstance(raw, bool):
                return raw / _PARAM_SCALE, _PICK_SOURCE
            self._log_error("p_pick_rz", "в ответе robot_param_get_all нет P_PICK_RZ.raw")
        except Exception as exc:  # noqa: BLE001 — сбор живёт дальше, причина уходит в collect.log
            self._log_exc("p_pick_rz", exc)
        return _DEFAULT_P_PICK_RZ_DEG, f"default {_DEFAULT_P_PICK_RZ_DEG} (не получен через robot_param_get_all)"

    # --- опрос ----------------------------------------------------------------------------------------------------
    def _poll_objects(self) -> None:
        reply = _res(
            self._sim.send_command("ProcessManager", "state.get", {"path": "sim.objects"}, timeout=_POLL_TIMEOUT_S)
        )
        # ключа ещё нет (status: error) — нормально до первого спавна: паспортов просто нет
        value = reply.get("value") if reply.get("status") == "ok" else None
        if not isinstance(value, dict):
            return
        stamp = format_local_time(self._wall())
        for object_id, passport in value.items():
            if object_id in self._seen_objects or not isinstance(passport, dict):
                continue
            self._seen_objects.add(object_id)
            self._objects.write(
                {
                    "object_id": object_id,
                    "class_name": passport.get("class_name"),
                    "angle_deg": passport.get("angle_deg"),
                    "lateral_px": passport.get("lateral_px"),
                    "t": stamp,
                }
            )
            self.objects += 1

    def _poll_journal(self) -> None:
        reply = _res(self._sim.send_command("robot", "sim_robot.journal", {}, timeout=_POLL_TIMEOUT_S))
        if reply.get("status") != "ok":
            message = str(reply.get("message"))[:_ERR_MSG_LIMIT]
            self._log_error("journal", f"status={reply.get('status')!r} message={message}")
            return
        wire = reply.get("wire")
        if not isinstance(wire, list):
            return
        stamp = format_local_time(self._wall())
        for row in wire:
            if not isinstance(row, dict):
                continue
            side, text = row.get("side"), row.get("text")
            key = (row.get("t"), side, text)
            if key in self._seen_rows:
                continue
            self._seen_rows.add(key)
            if self._is_merge_growth(row, side, text):
                continue  # кольцо дописало счётчик ``n`` и сдвинуло ``t`` у уже записанной строки
            self._journal.write({"t": stamp, "side": side, "text": text})
            self._last_written = (side, text)
            self.journal_lines += 1

    def _is_merge_growth(self, row: dict, side: Any, text: Any) -> bool:
        """Склеенная строка (``n > 1``) — рост уже записанной: кольцо склеивает только последнюю строку,
        поэтому такая строка, совпадающая с последней записанной, ничего нового не содержит."""
        n = row.get("n")
        return isinstance(n, int) and n > 1 and self._last_written == (side, text)

    def poll_once(self) -> None:
        """Один цикл: объекты, затем журнал; сбой одного источника не мешает второму и не останавливает сбор."""
        self.polls += 1
        for source, poll in (("objects", self._poll_objects), ("journal", self._poll_journal)):
            try:
                poll()
            except Exception as exc:  # noqa: BLE001 — одна неудача опроса не роняет сбор
                self._log_exc(source, exc)

    # --- цикл -----------------------------------------------------------------------------------------------------
    def _stop_requested(self) -> bool:
        return (self._out_dir / _STOP_FILE).exists()

    def _nap(self, total: float) -> bool:
        """Сон до ``total`` секунд шагами; ``True`` — за время сна появился STOP-файл."""
        end = self._clock() + total
        while self._clock() < end:
            if self._stop_requested():
                return True
            self._sleep(min(_NAP_STEP_S, max(end - self._clock(), 0.0)))
        return self._stop_requested()

    def loop(self) -> str:
        """Опрос до STOP-файла или Ctrl-C; возвращает причину остановки для ``meta.json``."""
        try:
            while not self._stop_requested():
                started = self._clock()
                self.poll_once()
                if self._nap(max(self._period - (self._clock() - started), 0.0)):
                    break
        except KeyboardInterrupt:
            return "interrupt"
        return "stop_file"


def _positive(text: str) -> float:
    value = float(text)
    if not value > 0:
        raise argparse.ArgumentTypeError("период должен быть > 0")
    return value


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m scripts.wire_audit.collect", description=__doc__.split("\n")[0])
    parser.add_argument("--proto-port", type=int, required=True, help="порт backend_ctl прототипа")
    parser.add_argument("--sim-port", type=int, required=True, help="порт backend_ctl сима")
    parser.add_argument("--out-dir", required=True, help="каталог для JSONL, meta.json, collect.log")
    parser.add_argument("--period", type=_positive, default=_DEFAULT_PERIOD_S, help="период опроса, с (0,25)")
    return parser


def run(
    argv: list[str],
    *,
    client_factory: Callable[[int], Client],
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
    wall: Callable[[], float] = time.time,
    err: TextIO | None = None,
) -> int:
    """Точка входа с подставляемыми швами: ``client_factory(port)``, часы, сон, поток ошибок."""
    err = err if err is not None else sys.stderr
    try:
        args = _parser().parse_args(argv)
    except SystemExit as exc:  # argparse: ошибка аргументов -> 2, --help -> 0
        return exc.code if isinstance(exc.code, int) else 2
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    if any((out_dir / name).exists() and (out_dir / name).stat().st_size for name in _DATA_FILES):
        err.write("каталог уже содержит данные сбора: нужен пустой или новый\n")
        return 2

    proto = sim = None
    try:
        sim = client_factory(args.sim_port)
        proto = client_factory(args.proto_port)
        sim.connect()
        proto.connect()
    except Exception as exc:  # noqa: BLE001 — любой отказ соединения на старте = код 3
        err.write(f"порт недоступен на старте: {type(exc).__name__}\n")
        for client in (proto, sim):
            _close_quietly(client, err)
        return 3

    stale_stop = out_dir / _STOP_FILE
    if stale_stop.exists():
        stale_stop.unlink()  # остаток прошлого запуска остановил бы сбор в первую же секунду

    collector = Collector(
        out_dir=out_dir, proto=proto, sim=sim, period=args.period, clock=clock, sleep=sleep, wall=wall
    )
    collector.meta.update(
        started=format_local_time(wall()), period_s=args.period, proto_port=args.proto_port, sim_port=args.sim_port
    )
    try:
        collector.dump_registers()
        collector.write_meta()
        collector.meta["stop_reason"] = collector.loop()
    finally:
        collector.meta["finished"] = format_local_time(wall())
        collector.close()
        for client in (proto, sim):
            _close_quietly(client, err)
    return 0


def _close_quietly(client: Client | None, err: TextIO) -> None:
    """Закрытие клиента при выходе: сбой не маскирует код возврата, но попадает в поток ошибок."""
    close = getattr(client, "close", None)
    if close is None:
        return
    try:
        close()
    except Exception as exc:  # noqa: BLE001
        err.write(f"закрытие клиента: {type(exc).__name__}\n")


def main() -> int:
    from backend_ctl.driver import BackendDriver

    return run(sys.argv[1:], client_factory=lambda port: BackendDriver(port=port))


if __name__ == "__main__":
    sys.exit(main())
