"""Симулятор робота v2 для стенда SPI (S0-S3): SimRobotServer + RobotSimCoreV2, управляется файлом.

Восстановлено по описанию стенда C-29 (`plans/robot-protocol-v2/tasks/C-29.stand.md`, handoff T5.3h): скрипты C-29
жили в scratchpad и потеряны. Запуск и числа - `README.md` рядом.

Команды (строка в управляющий файл `--ctl`; сим читает новые строки каждые 50 мс):
    drop            остановить слушателя (обрыв связи; ядро робота живёт)
    up <ms>         через <ms> мс поднять слушателя заново
    delay <ms>      задержка ответа на КАЖДЫЙ Modbus-доступ (`SimRobotServer.delay_ms`), без рестарта слушателя
    mark <имя>      строка границы сценария в журнал (`MARK <имя>`); count.py режет журнал по ней
    quit            выйти

Журнал `--log`: строка `<epoch_s.mmm> <ВИД> <текст>`. Виды: `CTL` (команда принята / `done`), `MARK`, `IO` (обмен:
`R`/`W`, адрес, значения), `EV` (события ядра `[v2] CMD/DONE/ERR ...`), `SIM` (старт / останов).
Часы - `time.time()` (одна машина с оркестратором).

Запуск (не из каталога `process_module`):
    PYTHONPATH=<worktree> <main .venv>/python sim_v2.py --log sim.log --ctl sim.log.ctl [--start-down] [--delay-ms 300]
"""

from __future__ import annotations

import argparse
import sys
import threading
import time
from pathlib import Path


def _stamp() -> str:
    return f"{time.time():.3f}"


class _Log:
    """Журнал сима: одна строка на событие, flush на каждую (читает count.py и оркестратор вживую)."""

    def __init__(self, path: Path) -> None:
        self._fh = path.open("a", encoding="utf-8", buffering=1)
        self._lock = threading.Lock()

    def line(self, kind: str, text: str) -> None:
        with self._lock:
            self._fh.write(f"{_stamp()} {kind} {text}\n")

    def close(self) -> None:
        with self._lock:
            self._fh.close()


def main() -> int:
    ap = argparse.ArgumentParser(description="Сим робота v2 для стенда SPI")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=5021)
    ap.add_argument("--unit", type=int, default=2)
    ap.add_argument("--log", required=True, type=Path)
    ap.add_argument("--ctl", required=True, type=Path)
    ap.add_argument("--delay-ms", type=int, default=300, help="начальная задержка ответа, мс (C-29: 300)")
    ap.add_argument("--start-down", action="store_true", help="слушатель НЕ поднят: S0 стартует без связи")
    args = ap.parse_args()

    # Импорты после разбора аргументов: `--help` не тянет pymodbus.
    from Services.robot_comm.core.protocol_v2 import REG
    from Services.robot_comm.server.sim_core_v2 import RobotSimCoreV2
    from Services.robot_comm.server.sim_robot import SimRobotServer

    names = {addr: name for name, addr in REG.items()}
    log = _Log(args.log)
    args.ctl.touch()

    def on_write(fc: int, address: int, values: list[int] | None) -> None:
        # None у values - чтение (контракт SimRobotServer.on_write); имя адреса - из карты v2 (CMD_ARGS и т.п. - база).
        name = names.get(address, f"0x{address:04X}")
        if values is None:
            log.line("IO", f"R {name} fc={fc}")
        else:
            log.line("IO", f"W {name} fc={fc} {list(values)}")

    core = RobotSimCoreV2(on_event=lambda text: log.line("EV", text))
    server = SimRobotServer(args.host, args.port, args.unit, core=core, on_write=on_write)
    server.delay_ms = args.delay_ms
    server.start()
    if args.start_down:
        server.stop_listener()  # ядро и тикер живут, порт отпущен: «связи нет»
    log.line("SIM", f"start {args.host}:{args.port} unit={args.unit} delay_ms={args.delay_ms} down={args.start_down}")

    stop = threading.Event()
    timers: list[threading.Timer] = []

    def do_up(ms: int) -> None:
        try:
            server.start_listener(ready_timeout=5.0)
            log.line("CTL", f"done up {ms}")
        except Exception as exc:  # noqa: BLE001 - стенд: ошибку в журнал, не молчать
            log.line("CTL", f"FAIL up {ms}: {type(exc).__name__}: {exc}")

    def handle(cmd: str) -> None:
        parts = cmd.split()
        if not parts:
            return
        op = parts[0]
        log.line("CTL", f"recv {cmd}")
        if op == "drop":
            server.stop_listener()
            log.line("CTL", "done drop")
        elif op == "up":
            ms = int(parts[1]) if len(parts) > 1 else 0
            timer = threading.Timer(ms / 1000.0, do_up, args=(ms,))
            timer.daemon = True
            timer.start()
            timers.append(timer)
        elif op == "delay":
            server.delay_ms = int(parts[1])
            log.line("CTL", f"done delay {server.delay_ms}")
        elif op == "mark":
            log.line("MARK", parts[1] if len(parts) > 1 else "?")
        elif op == "quit":
            stop.set()
        else:
            log.line("CTL", f"FAIL неизвестная команда {cmd!r}")

    pos = 0
    try:
        while not stop.is_set():
            time.sleep(0.05)
            with args.ctl.open("r", encoding="utf-8") as fh:
                fh.seek(pos)
                chunk = fh.read()
                pos = fh.tell()
            for raw in chunk.splitlines():
                handle(raw.strip())
    except KeyboardInterrupt:
        pass
    finally:
        for timer in timers:
            timer.cancel()
        try:
            server.stop()
        finally:
            log.line("SIM", "stop")
            log.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
