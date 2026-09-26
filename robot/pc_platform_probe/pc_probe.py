"""
ПК-сторона пробы платформы Delta SCARA (GATE-1 плана robot-protocol-v2).

Пара к ``probe.lua``: залей её в контроллер через DRAStudio, запусти, потом с ПК:

    python pc_probe.py all               # всё за один визит: safe, затем motion (спросит yes)
    python pc_probe.py safe              # без движения: адреса, часы, API, ПЧ, CVT…
    python pc_probe.py motion            # тесты с движением (спросит yes)
    python pc_probe.py globals           # только список функций контроллера
    python pc_probe.py call os.clock     # вызвать функцию без аргументов (опасные имена запрещены)
    python pc_probe.py clock SysTime     # скорость часов против часов ПК
    python pc_probe.py vfdread 0x0E00 6  # регистры ПЧ через мост RS-485
    python pc_probe.py servo on|off

Опции: ``--host 192.168.1.7 --port 502 --unit 2`` (по умолчанию — как в pc_cvt.py).

Итог каждого прогона — папка ``reports/<время>_<набор>/``: ``report.json`` (сырые данные),
``report.md`` (выводы для плана), ``globals.txt`` (список API). Отчёт пишется, даже если
прогон оборвался: упавшая проверка записывается с текстом ошибки, остальные идут дальше.

Сухой прогон без робота — ``dry_run.py`` (см. README).

Зависимости: pymodbus>=3.10.
"""

from __future__ import annotations

import argparse
import json
import random
import re
import sys
import threading
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from pymodbus.client import ModbusTcpClient
from pymodbus.exceptions import ModbusException

# =====================  КОНФИГУРАЦИЯ  ================================
ROBOT_IP = "192.168.1.7"
ROBOT_PORT = 502
ROBOT_UNIT = 2

# Канал пробы — копия таблицы B из probe.lua (менять парно).
CMD_FLAG, CMD_SEQ, CMD_TEST, ARG0, ARG_N = 0x1400, 0x1401, 0x1402, 0x1404, 12
RES_SEQ, RES_STATUS, RES_N, VAL0, VAL_N = 0x1410, 0x1411, 0x1412, 0x1414, 32
LIVE, CTRL, SCRATCH = 0x1440, 0x1450, 0x1460
PAGE_CHARS = 60

STATUS_TEXT = {1: "ок", 2: "ошибка теста", 3: "нет такого теста", 4: "функции нет", 5: "отказ по безопасности"}

# Адреса для проверки. rw — будущие блоки v2: пишем образец и ВОССТАНАВЛИВАЕМ прежнее значение.
# ro — только читаем: что там лежит у контроллера, неизвестно, запись может навредить.
ADDR_RW = [
    0x1000,
    0x1001,
    0x100F,
    0x1010,
    0x101F,
    0x1020,
    0x1021,
    0x1040,
    0x105F,
    0x107F,
    0x10FF,
    0x1300,
    0x1320,
    0x1363,
    0x137F,
    0x154C,
    0x1560,
    0x1600,
    0x16FF,
    0x1700,
    0x17FF,
    0x3000,  # 0x3000..0x3FFF по мануалу RL (12-2) сохраняется при выключении питания
    0x3100,
    0x3FFF,
]
ADDR_RO = [0x0000, 0x0FFF, 0x1800, 0x1FFF, 0x2000, 0x2FFF, 0x4000, 0xFFFF]
RETAIN_ADDR = 0x3F00  # метка для проверки «сохраняется при выключении» (retain-write / retain-check)
PATTERN_PC, PATTERN_LUA = 0xA55A, 0x3CC3

# Часы, которые проба вызывает сама: чистые геттеры времени.
SAFE_CLOCK_RE = re.compile(
    r"^(os\.clock|os\.time|(get_?)?sys_?time|get_?time|get_?tick_?count|tick_?count|clock|time)$", re.I
)
# Имена, которые `call`/`clock` не вызывают никогда: движение, серво, выходы, запись, сброс.
DENY_RE = re.compile(
    r"mov|servo|home|jog|^do$|cvt_|stop|write|set|arch|circle|tool|reset|run|start|scm_|delay|wait", re.I
)

POSE_TOL = 10  # ×0.1 мм: допуск «вернулся в исходную позу»
REPORTS = Path(__file__).resolve().parent / "reports"


def u16(v: int) -> int:
    return int(v) & 0xFFFF


def s16(v: int) -> int:
    v = u16(v)
    return v - 0x10000 if v >= 0x8000 else v


def i32(lo: int, hi: int) -> int:
    v = (u16(hi) << 16) | u16(lo)
    return v - 0x1_0000_0000 if v >= 0x8000_0000 else v


def text_regs(text: str) -> list[int]:
    """ASCII → регистры по 2 символа (старший байт первым), с нулём в конце."""
    data = text.encode("ascii") + b"\0"
    if len(data) % 2:
        data += b"\0"
    return [data[i] * 256 + data[i + 1] for i in range(0, len(data), 2)]


def regs_bytes(regs: list[int]) -> bytes:
    """Регистры → байты (старший байт первым). Декодировать — после склейки всех страниц."""
    return b"".join(bytes([(u16(w) >> 8) & 0xFF, u16(w) & 0xFF]) for w in regs)


# =====================  КЛИЕНТ ПРОБЫ  ===============================
@dataclass
class Result:
    status: int
    vals: list[int]
    text: str | None = None
    wall_s: float = 0.0

    @property
    def ok(self) -> bool:
        return self.status == 1


class ProbeError(RuntimeError):
    pass


class Probe:
    """Транзакции с probe.lua. pymodbus-клиент не потокобезопасен — всё под одним lock."""

    def __init__(self, host: str, port: int, unit: int) -> None:
        self.host, self.port, self.unit = host, port, unit
        self.client = ModbusTcpClient(host, port=port, timeout=2)
        self.lock = threading.Lock()
        self.seq = 0

    # ---- сырой Modbus ----
    def connect(self) -> None:
        if not self.client.connect():
            raise ProbeError(f"нет соединения с {self.host}:{self.port}")
        # Номер запроса — случайный и не равный последнему ответу пробы: проба не исполняет
        # повтор номера, и совпадение со старым запуском скрипта молча съело бы команду.
        # send() сначала увеличивает seq: опасно значение, у которого ПЕРВЫЙ отправленный номер
        # совпадёт с последним отвеченным — ПК принял бы старый ответ как свой.
        last = (self.read(RES_SEQ) or [0])[0]
        self.seq = random.randint(1, 60000)
        while self.seq % 60000 + 1 == last:
            self.seq = random.randint(1, 60000)

    def close(self) -> None:
        self.client.close()

    def read(self, addr: int, count: int = 1) -> list[int] | None:
        """FC3; None — контроллер ответил исключением (адреса нет)."""
        with self.lock:
            rr = self.client.read_holding_registers(addr, count=count, device_id=self.unit)
        return None if rr.isError() else list(rr.registers)

    def write(self, addr: int, value: int) -> bool:
        with self.lock:
            rr = self.client.write_register(addr, u16(value), device_id=self.unit)
        return not rr.isError()

    def write_many(self, addr: int, values: list[int]) -> bool:
        with self.lock:
            rr = self.client.write_registers(addr, [u16(v) for v in values], device_id=self.unit)
        return not rr.isError()

    # ---- канал пробы ----
    def wait_alive(self, timeout: float = 5.0) -> None:
        first = self.read(LIVE)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            time.sleep(0.1)
            now = self.read(LIVE)
            if first is not None and now is not None and now != first:
                return
            first = first if first is not None else now
        raise ProbeError("счётчик цикла пробы стоит: probe.lua не запущена на контроллере?")

    def send(self, test: int, args: list[int] | None = None) -> int:
        """Отправить тест, не дожидаясь ответа. Возвращает seq."""
        self.seq = self.seq % 60000 + 1
        args = (args or [])[:ARG_N]
        if not self.write_many(ARG0, args + [0] * (ARG_N - len(args))):
            raise ProbeError("запись аргументов отклонена")
        if not self.write_many(CMD_SEQ, [self.seq, test]):
            raise ProbeError("запись заголовка отклонена")
        if not self.write(CMD_FLAG, 1):  # маркер — последним, отдельной записью
            raise ProbeError("запись флага отклонена")
        return self.seq

    def poll(self, seq: int) -> Result | None:
        head = self.read(RES_SEQ, 3)
        if head is None or head[0] != seq:
            return None
        n = min(head[2], VAL_N)
        vals = self.read(VAL0, n) if n else []
        return Result(status=head[1], vals=vals or [])

    def wait(self, seq: int, timeout: float) -> Result:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            res = self.poll(seq)
            if res is not None:
                return res
            time.sleep(0.005)
        raise ProbeError(f"нет ответа на запрос {seq} за {timeout:.0f} с")

    def run(self, test: int, args: list[int] | None = None, timeout: float = 10.0, text: bool = False) -> Result:
        t0 = time.monotonic()
        res = self.wait(self.send(test, args), timeout)
        res.wall_s = time.monotonic() - t0
        if text or res.status in (2, 4, 5):
            res.text = self.fetch_text()
        return res

    def fetch_text(self) -> str:
        """Текстовый буфер пробы, постранично (тест 3). Длина — в байтах UTF-8 Lua-строки."""
        first = self.wait(self.send(3, [0]), 5.0)
        total = i32(first.vals[0], first.vals[1])
        data = bytearray(regs_bytes(first.vals[2:]))
        for page in range(1, (total + PAGE_CHARS - 1) // PAGE_CHARS):
            res = self.wait(self.send(3, [page]), 5.0)
            data += regs_bytes(res.vals[2:])
        return bytes(data[:total]).decode("utf-8", errors="replace")

    def live_fresh(self, timeout: float = 2.0) -> dict[str, int]:
        """LIVE после хотя бы одного нового цикла пробы: поза в LIVE обновляется в начале цикла,
        а после хода Mirror её уже не пишет — без ожидания читается поза ДО последнего хода."""
        first = self.live()
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            now = self.live()
            if (now["hb_motion"] - first["hb_motion"]) % 32768 >= 2:
                return now
            time.sleep(0.005)
        raise ProbeError("проба не обновляет LIVE — цикл Motion стоит?")

    def live(self) -> dict[str, int]:
        r = self.read(LIVE, 14) or [0] * 14
        return {
            "hb_motion": r[0],
            "hb_mirror": r[1],
            "moving": r[2],
            "x": s16(r[3]),
            "y": s16(r[4]),
            "z": s16(r[5]),
            "rz": s16(r[6]),
            "hand": s16(r[7]),
            "enc": i32(r[8], r[9]),
            "mirror_err": r[10],
            "last_test": r[11],
            "vfd_boot_stop": r[12],
            "pose_ok": r[13],
        }


# =====================  ОТЧЁТ  ======================================
@dataclass
class Report:
    data: dict[str, Any] = field(default_factory=dict)
    findings: list[str] = field(default_factory=list)
    errors: dict[str, str] = field(default_factory=dict)
    globals_text: str = ""

    def note(self, line: str) -> None:
        print("  • " + line)
        self.findings.append(line)


def step(rep: Report, name: str, fn: Callable[[], Any]) -> Any:
    """Одна проверка: падение записывается в отчёт, остальные продолжают."""
    try:
        return fn()
    except (ProbeError, ModbusException, OSError, ValueError, IndexError) as exc:
        rep.errors[name] = f"{type(exc).__name__}: {exc}"
        rep.note(f"[{name}] НЕ ЗАВЕРШЕНА: {exc}")
        return None


def rate(probe: Probe, key: str, seconds: float = 3.0) -> float:
    a = probe.live()[key]
    t0 = time.monotonic()
    time.sleep(seconds)
    b = probe.live()[key]
    return ((b - a) % 32768) / (time.monotonic() - t0)


def clock_verdict(delta: float, wall_s: float) -> str:
    """Пригодны ли часы для сторожевого таймера: идут в реальном времени, шаг мельче секунды."""
    if float(delta).is_integer() and 0 < delta <= 3 and abs(delta - wall_s) <= 1.0:
        return "реальное время, но шаг 1 с — грубо для таймера"
    ratio = delta / wall_s if wall_s else 0.0
    for units, name in (
        (1, "секунды"),
        (10, "1/10 с"),
        (100, "1/100 с"),
        (1000, "миллисекунды"),
        (10_000, "1/10000 с"),
        (1_000_000, "микросекунды"),
    ):
        if 0.9 * units <= ratio <= 1.1 * units:
            return f"годны ({name})"
    return "НЕ реальное время (например, процессорное — стоит во время DELAY)"


# =====================  НАБОР БЕЗ ДВИЖЕНИЯ  =========================
def check_loop(p: Probe, rep: Report) -> None:
    print("\n[цикл] частота циклов Motion и Mirror в простое")
    motion_hz = rate(p, "hb_motion")
    mirror_hz = rate(p, "hb_mirror")
    rep.data["loop"] = {"motion_hz": round(motion_hz, 1), "mirror_idle_hz": round(mirror_hz, 1)}
    rep.note(f"цикл Motion в простое: {motion_hz:.0f} Гц (период {1000 / max(motion_hz, 1e-9):.1f} мс, с DELAY 5 мс)")
    if mirror_hz < 0.5:
        rep.note("Mirror (function2) в простое НЕ крутится — всё обслуживание простоя обязано быть в Motion")
    else:
        rep.note(f"Mirror (function2) крутится и в простое: {mirror_hz:.0f} Гц")
    live = p.live()
    rep.data["boot"] = {
        "vfd_boot_stop": {1: "подтверждён", 2: "НЕ подтверждён"}.get(live["vfd_boot_stop"], "?"),
        "pose_ok": live["pose_ok"] == 1,
    }
    rep.note(f"СТОП ПЧ при старте пробы: {rep.data['boot']['vfd_boot_stop']}; поза читается: {live['pose_ok'] == 1}")


def check_api(p: Probe, rep: Report) -> list[str]:
    print("\n[api] версия Lua, библиотеки, глобальные функции")
    info = p.run(1, text=True)
    rep.data["lua_info"] = info.text
    rep.note("Lua: " + (info.text or "").replace("\n", ", "))
    res = p.run(2, timeout=30, text=True)
    if not res.ok:
        rep.note(f"дамп глобалов невозможен: {res.text}")
        return []
    rep.globals_text = res.text or ""
    names = [ln.split(" ")[0] for ln in rep.globals_text.splitlines() if ln.endswith(" function")]
    rep.data["globals_count"] = len(rep.globals_text.splitlines())
    rep.note(f"глобалов и полей таблиц: {rep.data['globals_count']} (полный список — globals.txt)")
    timers = [n for n in names if re.search(r"time|clock|tick|timer", n, re.I)]
    rep.data["time_like_functions"] = timers
    rep.note("функции, похожие на часы: " + (", ".join(timers) or "нет"))
    points = [n for n in names if re.search(r"point|pos", n, re.I)]
    rep.data["point_functions"] = points
    rep.note("функции точек/позиций: " + (", ".join(points) or "нет"))
    return names


def check_clocks(p: Probe, rep: Report, names: list[str]) -> None:
    print("\n[часы] источники времени против часов ПК")
    n = 400  # 400 × DELAY(0.005) ≈ 2 с
    base = p.run(5, [n])
    delay_ms = base.wall_s * 1000 / n
    rep.data["delay_5ms_real_ms"] = round(delay_ms, 2)
    rep.note(f"DELAY(0.005) реально длится ≈ {delay_ms:.2f} мс (оценка для таймера без часов)")
    clocks: dict[str, Any] = {}
    timer = p.run(6, [n], text=True)  # TimerOn/TimerRead — штатный таймер (RL 3-4)
    if timer.ok:
        t0, t1, _ = (timer.text or "||").split("|")
        try:
            delta = float(t1) - float(t0)
            verdict = clock_verdict(delta, timer.wall_s)
            clocks["TimerRead"] = {"delta": delta, "wall_s": round(timer.wall_s, 3), "verdict": verdict}
            rep.note(f"часы TimerOn/TimerRead: Δ={delta:g} за {timer.wall_s:.2f} с ПК → {verdict}")
        except ValueError:
            clocks["TimerRead"] = {"raw": timer.text}
    else:
        clocks["TimerRead"] = {"status": STATUS_TEXT.get(timer.status), "text": timer.text}
        rep.note(f"TimerOn/TimerRead: {STATUS_TEXT.get(timer.status)} {timer.text or ''}")
    for name in names:
        if not SAFE_CLOCK_RE.match(name):
            continue
        res = p.run(5, [n] + text_regs(name), text=True)
        if not res.ok:
            clocks[name] = {"status": STATUS_TEXT.get(res.status)}
            continue
        t0, t1, _ = (res.text or "||").split("|")
        try:
            delta = float(t1) - float(t0)
        except ValueError:
            clocks[name] = {"raw": res.text}
            continue
        verdict = clock_verdict(delta, res.wall_s)
        clocks[name] = {"delta": delta, "wall_s": round(res.wall_s, 3), "verdict": verdict}
        rep.note(f"часы {name}: Δ={delta:g} за {res.wall_s:.2f} с ПК → {verdict}")
    rep.data["clocks"] = clocks
    if not any(str(c.get("verdict", "")).startswith("годны") for c in clocks.values()):
        rep.note(
            "НЕТ пригодных часов среди безопасных кандидатов — сторожевой таймер v2 будет по оценке циклов"
            " (или проверь кандидата вручную: pc_probe.py clock ИМЯ)"
        )


def check_addresses(p: Probe, rep: Report) -> None:
    print("\n[адреса] чтение/запись ПК и видимость из Lua")
    table: dict[str, dict[str, Any]] = {}
    for addr in ADDR_RW:
        row: dict[str, Any] = {}
        orig = p.read(addr)
        row["pc_read"] = orig is not None
        if orig is not None:
            try:
                row["pc_write"] = p.write(addr, PATTERN_PC) and p.read(addr) == [PATTERN_PC]
                lua = p.run(7, [addr])
                row["lua_sees_pc"] = lua.ok and u16(lua.vals[0]) == PATTERN_PC
                wr = p.run(8, [addr, PATTERN_LUA])
                row["pc_sees_lua"] = wr.ok and p.read(addr) == [PATTERN_LUA]
            finally:
                p.write(addr, orig[0])
                row["restored"] = p.read(addr) == orig
        table[f"0x{addr:04X}"] = row
    for addr in ADDR_RO:
        table[f"0x{addr:04X}"] = {"pc_read": p.read(addr) is not None, "ro": True}
    rep.data["addresses"] = table
    need = ("pc_read", "pc_write", "lua_sees_pc", "pc_sees_lua", "restored")
    for key, row in table.items():
        state = (
            "только чтение"
            if row.get("ro")
            else ("полный доступ" if all(row.get(k) for k in need) else f"НЕ ГОДЕН {row}")
        )
        print(f"    {key}: {'читается' if row['pc_read'] else 'исключение'}; {state}")
    bad = [k for k, r in table.items() if not r.get("ro") and not all(r.get(x) for x in need)]
    rep.note(
        "все адреса будущих блоков v2 доступны в обе стороны"
        if not bad
        else f"недоступны или не восстановились: {', '.join(bad)} — сдвинуть базы блоков в YAML"
    )


def check_blocks(p: Probe, rep: Report) -> None:
    print("\n[блоки] пределы FC16/FC3 и MultiRead/Write из Lua")
    fc16 = {
        n: p.write_many(SCRATCH, list(range(1, n + 1))) and p.read(SCRATCH, n) == list(range(1, n + 1))
        for n in (30, 60, 100, 123)
    }
    fc3 = {n: p.read(0x1400, n) is not None for n in (60, 125)}
    lua = {}
    for n in (30, 60, 125):
        res = p.run(9, [SCRATCH, n, 100], text=True)
        lua[n] = bool(res.ok and res.vals[:3] == [1, n, 1])
    rep.data["blocks"] = {"pc_fc16": fc16, "pc_fc3": fc3, "lua_multi": lua}
    rep.note(f"ПК FC16 (длина → ок): {fc16}; FC3: {fc3}; Lua MultiRead/Write: {lua}")


def check_dw(p: Probe, rep: Report) -> None:
    res = p.run(10, [SCRATCH])
    regs = p.read(SCRATCH, 2) or [0, 0]
    order = (
        "little [lo, hi]" if regs == [0x5678, 0x1234] else "big [hi, lo]" if regs == [0x1234, 0x5678] else f"?? {regs}"
    )
    rep.data["dw_order"] = order if res.ok else f"ошибка: {res.status}"
    rep.note(f"порядок слов DW из Lua: {rep.data['dw_order']}")


def _prefill(p: Probe, n: int) -> None:
    """Однородный блок перед тестом: иначе остатки прошлых тестов считаются «рваными»."""
    if not (p.write_many(SCRATCH, [0] * n) and p.read(SCRATCH, n) == [0] * n):
        raise ProbeError("не удалось подготовить однородный блок SCRATCH")


def check_atomic(p: Probe, rep: Report) -> None:
    print("\n[атомарность] рвутся ли блочные записи при параллельном чтении")
    n, cycles = 30, 1500
    _prefill(p, n)
    seq = p.send(11, [n, cycles])
    reads = torn = 0
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        block = p.read(SCRATCH, n)
        if block is not None:
            reads += 1
            torn += any(v != block[0] for v in block)
        if p.poll(seq) is not None:
            break
    rep.data["atomic_lua_write"] = {"pc_reads": reads, "torn": torn}
    rep.note(
        f"Lua MultiWrite ↔ чтение ПК: {torn} рваных из {reads} — "
        + ("блок виден атомарно" if torn == 0 else "НЕ атомарно: телеметрии нужен порядок записи с маркером")
    )

    _prefill(p, n)
    second = ModbusTcpClient(p.host, port=p.port, timeout=2)
    stats = {"ok": 0, "err": 0, "exc": ""}
    if not second.connect():
        rep.data["second_connection"] = False
        rep.note("контроллер НЕ принимает второе TCP-соединение — драйвер обязан держать одно")
        return
    stop = threading.Event()

    def writer() -> None:
        k = 0
        while not stop.is_set():
            k = k % 30000 + 1
            try:
                rr = second.write_registers(SCRATCH, [k] * n, device_id=p.unit)
                stats["ok" if not rr.isError() else "err"] += 1
            except Exception as exc:  # noqa: BLE001 - любой сбой второго канала = факт для отчёта
                stats["err"] += 1
                stats["exc"] = f"{type(exc).__name__}: {exc}"
                return

    th = threading.Thread(target=writer, daemon=True)
    th.start()
    try:
        res = p.run(12, [n, cycles], timeout=60)
    finally:
        stop.set()
        th.join(timeout=5)
        second.close()
    accepted = stats["ok"] > 0 and stats["err"] == 0
    rep.data["second_connection"] = {"accepted": accepted, **stats}
    rep.data["atomic_pc_write"] = {
        "lua_reads": res.vals[0] if res.vals else 0,
        "torn": res.vals[1] if len(res.vals) > 1 else -1,
    }
    if accepted:
        rep.note(
            f"второе TCP-соединение работает ({stats['ok']} записей);"
            f" FC16 ПК ↔ MultiRead Lua: {rep.data['atomic_pc_write']}"
        )
    else:
        rep.note(f"второе TCP-соединение НЕ работает: {stats} — драйвер обязан держать одно соединение")


def check_robot(p: Probe, rep: Report) -> None:
    print("\n[робот] оси WritePoint, рука, лента, входы, сеттеры")
    axes = p.run(13, text=True)
    rep.data["axes"] = axes.text
    rep.note("WritePoint → ReadPoint: " + (axes.text or "").replace("\n", "; "))
    sg = p.run(23, text=True)
    rep.data["setglobal_runtime"] = {
        "status": STATUS_TEXT.get(sg.status),
        "all_match": sg.vals[:1] == [1],
        "text": sg.text,
    }
    rep.note(
        f"SetGlobalPoint на ходу программы + ReadPoint: {'совпало' if sg.vals[:1] == [1] else 'НЕ совпало'}"
        f" ({STATUS_TEXT.get(sg.status)}) {sg.text or ''}"
    )
    lp = p.run(24, text=True)
    rep.data["local_point"] = {"status": STATUS_TEXT.get(lp.status), "ok": lp.vals[:1] == [1], "text": lp.text}
    rep.note(f"локальная точка 1001: {lp.text or STATUS_TEXT.get(lp.status)}")
    hand = p.run(14, text=True)
    rep.data["hand"] = {"text": hand.text, "pose_x10": [s16(v) for v in hand.vals]}
    rep.note((hand.text or "").replace("\n", "; ") + f"; поза ×0.1: {rep.data['hand']['pose_x10']}")
    di = p.run(19, text=True)
    rep.data["di"] = {"status": STATUS_TEXT.get(di.status), "text": di.text}
    rep.note(f"DI: {STATUS_TEXT.get(di.status)} {di.text or ''}")
    setters = p.run(21, text=True)
    rep.data["setters"] = setters.text
    rep.note("сеттеры режимов: " + (setters.text or "").replace("\n", ", "))
    rs = p.run(22, timeout=15, text=True)
    rep.data["rsmaster"] = {"status": STATUS_TEXT.get(rs.status), "vals": [u16(v) for v in rs.vals], "text": rs.text}
    rep.note(
        f"встроенный мастер RS-485 (RSmasterRead к ПЧ): {STATUS_TEXT.get(rs.status)} {rs.text or ''}"
        " — если работает, мост к ПЧ в v2 обходится без своего CRC и SCM_FreePort"
    )


def check_reinit(p: Probe, rep: Report) -> None:
    print("\n[переинициализация] CVT и порт RS-485 на ходу программы")
    cvt = p.run(15, timeout=15, text=True)
    ok = bool(cvt.vals) and cvt.vals[0] == 1
    e0, e1 = (i32(cvt.vals[1], cvt.vals[2]), i32(cvt.vals[3], cvt.vals[4])) if len(cvt.vals) >= 5 else (0, 0)
    rep.data["cvt_reinit"] = {"ok": ok, "enc_before": e0, "enc_after": e1, "err": cvt.text}
    rep.note(
        f"повторная initCVT: {'прошла' if ok else 'ОШИБКА ' + str(cvt.text)}; энкодер {e0} → {e1}"
        " (сброс в 0 = параметры CVT применять только перезапуском программы)"
    )
    port = p.run(16, timeout=15, text=True)
    v = port.vals + [0] * 7
    state = {1: "РАБОТА вперёд", 2: "РАБОТА назад"}.get(v[3], f"код {v[3]} (не работа по v1)") if v[2] == 1 else "—"
    rep.data["port_reopen"] = {
        "ok": v[0] == 1,
        "rtn": s16(v[1]),
        "vfd_answers": v[2] == 1,
        "vfd_status": v[3:7] if v[2] == 1 else None,
        "err": port.text,
    }
    rep.note(
        f"повторный SCM_FreePort: rtn={s16(v[1])}, ПЧ после него {'отвечает' if v[2] == 1 else 'НЕ отвечает'};"
        f" состояние ПЧ: {state}"
    )


def check_vfd(p: Probe, rep: Report) -> None:
    print("\n[ПЧ] время транзакции RS-485 и группа параметров связи")
    n = 20
    res = p.run(18, [n], timeout=30)
    okn, failn = (res.vals + [0, 0])[:2]
    per_ms = res.wall_s * 1000 / n
    rep.data["vfd_timing"] = {"ok": okn, "fail": failn, "per_read_ms": round(per_ms, 1)}
    rep.note(f"чтение статуса ПЧ: {okn} ок / {failn} без ответа, ≈ {per_ms:.0f} мс на транзакцию")
    grp = p.run(17, [0x0E00, 6], timeout=10, text=True)
    rep.data["vfd_p14"] = [u16(x) for x in grp.vals] if grp.ok else f"{STATUS_TEXT.get(grp.status)} {grp.text}"
    rep.note(f"ПЧ, адреса 0x0E00..0x0E05 (у INVT GD20 — группа P14, сверить по мануалу): {rep.data['vfd_p14']}")


def run_safe(p: Probe, rep: Report | None = None) -> Report:
    rep = rep or Report()
    step(rep, "цикл", lambda: check_loop(p, rep))
    names = step(rep, "api", lambda: check_api(p, rep)) or []
    step(rep, "часы", lambda: check_clocks(p, rep, names))
    step(rep, "адреса", lambda: check_addresses(p, rep))
    step(rep, "блоки", lambda: check_blocks(p, rep))
    step(rep, "dw", lambda: check_dw(p, rep))
    step(rep, "атомарность", lambda: check_atomic(p, rep))
    step(rep, "робот", lambda: check_robot(p, rep))
    step(rep, "переинициализация", lambda: check_reinit(p, rep))
    step(rep, "пч", lambda: check_vfd(p, rep))
    rep.data["live"] = step(rep, "снимок", p.live)
    return rep


# =====================  ДВИЖЕНИЕ  ===================================
class MotionAbort(ProbeError):
    pass


def move_rel(p: Probe, dx: int, dy: int = 0, dz: int = 0, spd: int = 5, timeout: float = 30) -> Result:
    return p.run(30, [u16(dx), u16(dy), u16(dz), spd], timeout=timeout, text=True)


def go_back(p: Probe, start: dict[str, int]) -> None:
    """Вернуться в исходную позу и УБЕДИТЬСЯ в этом; иначе набор прерывается."""
    now = p.live_fresh()
    dx, dy, dz = start["x"] - now["x"], start["y"] - now["y"], start["z"] - now["z"]
    if abs(dx) + abs(dy) + abs(dz) > POSE_TOL // 2:
        res = move_rel(p, dx, dy, dz, spd=10)
        if not (res.ok and res.vals[:1] == [1]):
            raise MotionAbort(f"возврат в исходную позу не выполнен: {STATUS_TEXT.get(res.status)} {res.text}")
    now = p.live_fresh()
    off = max(abs(now["x"] - start["x"]), abs(now["y"] - start["y"]), abs(now["z"] - start["z"]))
    if off > POSE_TOL or abs(now["rz"] - start["rz"]) > POSE_TOL:
        raise MotionAbort(f"робот не в исходной позе: отклонение {off / 10} мм, RZ {now['rz']} против {start['rz']}")


def watch_move(
    p: Probe, seq: int, action_at: float | None = None, action=None
) -> tuple[Result, list[tuple[float, dict]]]:
    """Сэмплы LIVE во время хода; action() — один раз, когда ход идёт action_at секунд."""
    samples: list[tuple[float, dict]] = []
    t0 = time.monotonic()
    fired = False
    while True:
        t = time.monotonic() - t0
        samples.append((t, p.live()))
        if action and not fired and action_at is not None and t >= action_at and samples[-1][1]["moving"]:
            action()
            fired = True
            samples.append((time.monotonic() - t0, {"event": "action"}))
        res = p.poll(seq)
        if res is not None:
            res.wall_s = time.monotonic() - t0
            if res.status != 1:
                res.text = p.fetch_text()
            return res, samples
        if t > 60:
            raise MotionAbort("ход не закончился за 60 с")


def _moving(samples: list[tuple[float, dict]]) -> list[tuple[float, dict]]:
    return [(t, s) for t, s in samples if s.get("moving") and "x" in s]


def _freeze_time(samples: list[tuple[float, dict]], after: float) -> float | None:
    """Первый момент после `after`, с которого X не меняется в трёх сэмплах подряд."""
    pts = [(t, s["x"]) for t, s in samples if "x" in s and t >= after]
    for i in range(len(pts) - 2):
        if pts[i][1] == pts[i + 1][1] == pts[i + 2][1]:
            return pts[i][0]
    return None


def _check_ok(res: Result, what: str) -> None:
    if res.status == 5:
        raise MotionAbort(f"{what}: отказ пробы — {res.text}")


def _stop_test(p: Probe, rep: Report, key: str, fast: bool) -> None:
    """Стоп посреди хода 45 мм: сколько проехал, когда замер, когда вернулся MovL."""
    start = p.live_fresh()
    p.write(CTRL + 7, 1 if fast else 0)
    t_stop: dict[str, float] = {}
    t0 = time.monotonic()
    seq = p.send(30, [450, 0, 0, 3])

    def do_stop() -> None:
        t_stop["t"] = time.monotonic() - t0
        p.write(CTRL + 0, (p.read(CTRL) or [0])[0] + 1)

    try:
        res, samples = watch_move(p, seq, action_at=0.3, action=do_stop)
    finally:
        p.write(CTRL + 7, 0)
    _check_ok(res, key)
    label = "быстрый стоп (DecL max)" if fast else "стоп"
    if "t" not in t_stop:
        rep.note(f"{label}: ход закончился раньше стопа — уменьши скорость в коде теста")
        go_back(p, start)
        return
    stopped = len(res.vals) > 1 and res.vals[1] == 1
    moved = (s16(res.vals[2]) - start["x"]) / 10 if len(res.vals) > 2 else None
    freeze = _freeze_time(samples, t_stop["t"])
    fast_res = {0: "не вызывался", 1: "DecL из Mirror ок", 2: "DecL из Mirror — ошибка"}.get(
        res.vals[6] if len(res.vals) > 6 else 0, "?"
    )
    rep.data[key] = {
        "mirror_saw_stop": stopped,
        "moved_mm_of_45": moved,
        "stop_to_freeze_s": None if freeze is None else round(freeze - t_stop["t"], 3),
        "stop_to_return_s": round(res.wall_s - t_stop["t"], 3),
        "movl_ok": res.vals[:1],
        "decl_in_mirror": fast_res,
        "err": res.text,
    }
    rep.note(
        f"{label}: MotionStop из Mirror {'сработал' if stopped else 'НЕ сработал'}, робот прошёл {moved} мм из 45;"
        f" до замирания позы ≈ {rep.data[key]['stop_to_freeze_s']} с, до возврата MovL"
        f" ≈ {rep.data[key]['stop_to_return_s']} с (включая опрос ПК ~10–20 мс); {fast_res};"
        " MovL после стопа вернул " + ("норму" if res.vals[:1] == [1] else "ошибку: " + str(res.text))
    )
    go_back(p, start)


def run_motion(p: Probe, rep: Report | None = None) -> Report:
    rep = rep or Report()
    print("\n⚠️  Тесты с ДВИЖЕНИЕМ: цели в пределах ±50 мм от текущей позы, скорость ≤ 30 %,")
    print("   поворот RZ на +5° и обратно. Серво должно быть включено (pc_probe.py servo on),")
    print("   зона ±50 мм вокруг инструмента — свободна, рука оператора — на аварийной кнопке.")
    if input("   Продолжить? Напиши yes: ").strip().lower() != "yes":
        rep.note("движение отменено оператором")
        return rep
    try:
        _motion_suite(p, rep)
    except MotionAbort as exc:
        rep.errors["движение"] = str(exc)
        rep.note(f"НАБОР С ДВИЖЕНИЕМ ПРЕРВАН: {exc}")
    finally:
        p.write(CTRL + 2, 0)
    return rep


def _motion_suite(p: Probe, rep: Report) -> None:
    anchor = p.run(29, text=True)
    _check_ok(anchor, "якорь")
    rep.note(f"якорь (центр оболочки ±50 мм), поза ×0.1: {[s16(v) for v in anchor.vals]}")
    p.write(CTRL + 2, 1)  # Mirror публикует позу во время хода

    # 1. ход 20 мм: частота Mirror и общее состояние Motion ↔ Mirror
    start = p.live_fresh()
    seq = p.send(30, [200, 0, 0, 5])
    token = seq % 30000 + 1
    res, samples = watch_move(p, seq)
    _check_ok(res, "ход 20 мм")
    mv = _moving(samples)
    if len(mv) >= 2 and mv[-1][0] > mv[0][0]:
        hz = ((mv[-1][1]["hb_mirror"] - mv[0][1]["hb_mirror"]) % 32768) / (mv[-1][0] - mv[0][0])
        rep.data["mirror_moving_hz"] = round(hz, 1)
        rep.note(f"Mirror во время хода: ≈ {hz:.0f} Гц")
    shared = p.read(CTRL + 5, 2) or [0, 0]
    rep.data["shared_state"] = {"local_seen": shared[0] == token, "global_seen": shared[1] == token}
    rep.note(
        f"Mirror видит состояние Motion: через local — {'да' if shared[0] == token else 'НЕТ'},"
        f" через глобал — {'да' if shared[1] == token else 'НЕТ'}"
    )
    rep.data["move_20mm"] = {"vals": res.vals, "wall_s": round(res.wall_s, 3), "err": res.text}
    go_back(p, start)

    # 2. стоп: обычный и «быстрый» (DecL на максимум из Mirror перед MotionStop, RL 1-51)
    _stop_test(p, rep, "stop", fast=False)
    _stop_test(p, rep, "stop_fast", fast=True)

    # 3. Override из Mirror (function2): 3 % → 20 %
    start = p.live_fresh()
    seq = p.send(30, [450, 0, 0, 3])
    res, samples = watch_move(p, seq, action_at=0.3, action=lambda: p.write(CTRL + 1, 20))
    _check_ok(res, "override")
    ovr = (p.read(CTRL + 4) or [0])[0]
    mark = next((t for t, s in samples if s.get("event") == "action"), None)
    pts = [(t, s["x"]) for t, s in _moving(samples)]
    speeds = {}
    if mark is not None:
        for label, sel in (("до", [q for q in pts if q[0] < mark]), ("после", [q for q in pts if q[0] > mark + 0.2])):
            if len(sel) >= 2 and sel[-1][0] > sel[0][0]:
                speeds[label] = round((sel[-1][1] - sel[0][1]) / 10 / (sel[-1][0] - sel[0][0]), 1)
    rep.data["override_in_mirror"] = {
        "result": {0: "не вызван", 1: "ок", 2: "ошибка", 3: "выше лимита"}.get(ovr, ovr),
        "speed_mm_s": speeds,
    }
    rep.note(
        f"Override из function2: {rep.data['override_in_mirror']['result']}; скорость мм/с {speeds}"
        " (рост после 3 % → 20 % = Override на ходу работает)"
    )
    go_back(p, start)

    # 4. error(таблица) после хода внутри pcall
    res = p.run(32, timeout=30, text=True)
    _check_ok(res, "unwind")
    caught, back = (res.vals + [0, 0])[:2]
    rep.data["unwind"] = {"caught": caught == 1, "move_after": back == 1, "err": res.text or ""}
    rep.note(
        f"error(таблица) после MovL внутри pcall: {'пойман' if caught == 1 else 'НЕ пойман'};"
        f" следующий MovL {'работает' if back == 1 else 'НЕ работает: ' + str(res.text)}"
    )

    # 5. PASS-цепочка: без записей / Mirror пишет / Motion пишет между точками; затем — со стопом
    times: dict[str, Any] = {}
    for mode, label in ((0, "без записей"), (1, "Mirror пишет позу"), (2, "Motion пишет между точками")):
        start = p.live_fresh()
        res = p.run(31, [20, 20, 10, mode], timeout=60, text=True)
        _check_ok(res, f"PASS {label}")
        times[label] = round(res.wall_s, 2) if res.vals[:1] == [1] else f"ошибка {res.status} {res.text}"
        go_back(p, start)
    rep.data["pass_chain_s"] = times
    rep.note(f"PASS-цепочка 20 точек × 2 мм, время: {times} (рост = запись рвёт упреждение)")
    start = p.live_fresh()
    seq = p.send(31, [20, 20, 10, 0])
    res, _ = watch_move(p, seq, action_at=0.2, action=lambda: p.write(CTRL + 0, (p.read(CTRL) or [0])[0] + 1))
    _check_ok(res, "PASS со стопом")
    off_mm = s16(res.vals[3]) / 10 if len(res.vals) > 3 else None
    full_s = times.get("без записей")
    interrupted = off_mm is not None and abs(off_mm) > 0.5
    rep.data["pass_stop"] = {
        "stop_seen": len(res.vals) > 1 and res.vals[1] == 1,
        "stopped_off_start_mm": off_mm,
        "interrupted": interrupted,
        "wall_s": round(res.wall_s, 2),
        "full_chain_s": full_s,
        "issued_points": res.vals[2] if len(res.vals) > 2 else -1,  # MovL+PASS возвращается до конца хода
    }
    rep.note(
        f"стоп посреди PASS-цепочки (туда-обратно, кончается в старте): робот встал в {off_mm} мм от старта"
        f" за {res.wall_s:.2f} с (полная цепочка {full_s} с) → "
        + (
            "стоп ПРЕРЫВАЕТ очередь PASS-ходов"
            if interrupted
            else "робот вернулся в старт: MotionStop НЕ сбросил очередь PASS-ходов — v2 обязан это учесть"
        )
    )
    go_back(p, start)

    # 6. 4-я ось: поворот RZ на +5° и обратно — каким способом задаётся ось
    rot: dict[str, Any] = {}
    for label, test, args in (
        ("SetGlobalPoint", 33, []),
        ("WritePoint RZ", 34, text_regs("RZ")),  # по мануалу RL 5-10
        ("WritePoint R", 34, text_regs("R")),  # так пишет v1 (main_actual.lua) — проверка бага
    ):
        start = p.live_fresh()
        res = p.run(test, args, timeout=30, text=True)
        v = res.vals + [0] * 7
        rot[label] = {
            "status": STATUS_TEXT.get(res.status),
            "moved": v[0] == 1,
            "d_rz_deg": s16(v[1]) / 10,
            "d_xyz_mm": [s16(v[2]) / 10, s16(v[3]) / 10, s16(v[4]) / 10],
            "back_ok": v[5] == 1,
            "rz_after_deg": s16(v[6]) / 10,
            "err": res.text,
        }
        rep.note(
            f"RZ через {label}: {rot[label]['status']}, ΔRZ {rot[label]['d_rz_deg']}°,"
            f" ΔXYZ {rot[label]['d_xyz_mm']} мм, возврат {'ок' if v[5] == 1 else 'НЕТ'}"
        )
        go_back(p, start)
    rep.data["axis4"] = rot


# =====================  СОХРАНЕНИЕ И CLI  ===========================
def save(rep: Report, kind: str, p: Probe) -> Path:
    out = REPORTS / time.strftime(f"%Y-%m-%d_%H%M%S_{kind}")
    out.mkdir(parents=True, exist_ok=True)
    meta = {"host": p.host, "port": p.port, "unit": p.unit, "time": time.strftime("%Y-%m-%d %H:%M:%S")}
    payload = {"meta": meta, "errors": rep.errors, **rep.data}
    (out / "report.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    md = [f"# Проба платформы — {kind}", "", f"{meta}", "", "## Выводы", ""] + [f"- {f}" for f in rep.findings]
    if rep.errors:
        md += ["", "## Незавершённые проверки", ""] + [f"- {k}: {v}" for k, v in rep.errors.items()]
    (out / "report.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    if rep.globals_text:
        (out / "globals.txt").write_text(rep.globals_text + "\n", encoding="utf-8")
    print(f"\nОтчёт: {out}")
    return out


def retain(p: Probe, cmd: str) -> int:
    """Сохраняется ли 0x3000..0x3FFF при выключении: метка до и после перезапуска питания."""
    marker_file = REPORTS / "retain_marker.json"
    if cmd == "retain-write":
        value = random.randint(1000, 30000)
        if not (p.write(RETAIN_ADDR, value) and p.read(RETAIN_ADDR) == [value]):
            print(f"запись метки в 0x{RETAIN_ADDR:04X} не прошла")
            return 1
        REPORTS.mkdir(parents=True, exist_ok=True)
        marker_file.write_text(json.dumps({"addr": RETAIN_ADDR, "value": value, "time": time.ctime()}))
        print(
            f"метка {value} записана в 0x{RETAIN_ADDR:04X}. Выключи и включи контроллер, запусти probe.lua,"
            " затем: pc_probe.py retain-check"
        )
        return 0
    saved = json.loads(marker_file.read_text())
    now = p.read(RETAIN_ADDR)
    kept = now == [saved["value"]]
    print(
        f"метка {saved['value']} (записана {saved['time']}); сейчас в 0x{RETAIN_ADDR:04X}: {now} →"
        f" {'СОХРАНИЛАСЬ — зеркало параметров v2 можно держать в 0x3000..' if kept else 'НЕ сохранилась'}"
    )
    return 0 if kept else 1


def call_allowed(name: str) -> str | None:
    """Текст отказа для `call`/`clock` или None. Опасные имена не вызываются никогда."""
    if DENY_RE.search(name):
        return f"«{name}» похоже на команду движения/выхода/записи — проба её не вызывает"
    if (
        not SAFE_CLOCK_RE.match(name)
        and input(f"   Вызвать {name}() на контроллере? Напиши yes: ").strip().lower() != "yes"
    ):
        return "отменено оператором"
    return None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Проба платформы Delta SCARA (пара к probe.lua)")
    ap.add_argument("--host", default=ROBOT_IP)
    ap.add_argument("--port", type=int, default=ROBOT_PORT)
    ap.add_argument("--unit", type=int, default=ROBOT_UNIT)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("all", "safe", "motion", "globals", "retain-write", "retain-check"):
        sub.add_parser(name)
    sub.add_parser("call").add_argument("name")
    sub.add_parser("clock").add_argument("name")
    vr = sub.add_parser("vfdread")
    vr.add_argument("addr", type=lambda s: int(s, 0))
    vr.add_argument("qty", type=int)
    sub.add_parser("servo").add_argument("state", choices=["on", "off"])
    a = ap.parse_args(argv)

    p = Probe(a.host, a.port, a.unit)
    rep = Report()
    kind = a.cmd
    try:
        p.connect()
        p.wait_alive()
        if a.cmd in ("all", "safe"):
            run_safe(p, rep)
        if a.cmd in ("all", "motion"):
            run_motion(p, rep)
        if a.cmd == "globals":
            check_api(p, rep)
        if a.cmd in ("call", "clock"):
            why = call_allowed(a.name)
            if why:
                print(why)
                return 1
            if a.cmd == "call":
                res = p.run(4, text_regs(a.name), text=True)
                print(STATUS_TEXT.get(res.status), res.text)
            else:
                res = p.run(5, [400] + text_regs(a.name), text=True)
                print(STATUS_TEXT.get(res.status), res.text, f"ПК: {res.wall_s:.3f} с")
                if res.ok:
                    t0, t1, _ = (res.text or "||").split("|")
                    print("вердикт:", clock_verdict(float(t1) - float(t0), res.wall_s))
            return 0
        if a.cmd == "vfdread":
            res = p.run(17, [a.addr, a.qty], text=True)
            print(STATUS_TEXT.get(res.status), [f"0x{u16(v):04X}" for v in res.vals], res.text or "")
            return 0
        if a.cmd in ("retain-write", "retain-check"):
            return retain(p, a.cmd)
        if a.cmd == "servo":
            print(STATUS_TEXT.get(p.run(20, [1 if a.state == "on" else 0]).status))
            return 0
        return 0 if not rep.errors else 3
    except (ProbeError, ModbusException, OSError) as exc:
        rep.errors["соединение"] = f"{type(exc).__name__}: {exc}"
        print(f"ОШИБКА: {exc}", file=sys.stderr)
        traceback.print_exc()
        return 2
    finally:
        if kind in ("all", "safe", "motion", "globals") and (rep.findings or rep.errors):
            save(rep, kind, p)
        p.close()


if __name__ == "__main__":
    sys.exit(main())
