"""Сквозная проверка цепочки рецепта ``letter_robot_sim`` (Task 4a): один запуск от старта сима до вердикта.

Запуск (из любого каталога; папка НЕ пакет)::

    python multiprocess_prototype/recipes/chain_checks/letter_robot_sim/run_chain_check.py \\
        [--config chain_check.yaml] [--tree <корень>] [--runs N] [--gui] [--out-root <каталог>]

Один прогон — холодный старт: сим, прототип, команды сима из конфига, сборщик, α, остановка, аудит, вердикт.
Все команды и порты — в ``chain_check.yaml``; скрипт знает только имена шагов. Коды возврата: 0 — МЕХАНИЗМ PASS
во всех прогонах; 1 — в каком-либо прогоне FAIL (сценарий дошёл, проверка красная); 2 — ошибка аргументов или
конфига; 3 — предусловие или запуск сорвался (порт занят, сим или прототип не поднялся, команда сима не принята) либо
МЕХАНИЗМ НЕ ПРОВЕРЕН (сценарий не дошёл: α вышла по предусловию с кодом 3, аудит отказал по входу с кодом 2 или в
прогоне нет ни одной строки диска); код 3 сильнее кода 1. α запускается ТОЛЬКО внешним
процессом; живой прогон на общей машине берёт окно снаружи (см. README).

Замков и окон машины скрипт не берёт. Процессы, которые он запустил, он же и убирает: SIGTERM всей группе
процесса, через ``stop`` секунд SIGKILL; чужие процессы (в том числе на портах ``free_after``) не трогаются.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from itertools import count
from pathlib import Path
from typing import Any

import yaml

_POSIX = os.name == "posix"
_LOOPBACK = "127.0.0.1"
_POLL_S = 0.2
_PORT_PROBE_S = 0.5
_PORTS_GRACE_S = 1.0  # после остановки порт может освободиться не мгновенно
_KILL_GRACE_S = 3.0  # после SIGKILL ждём, пока группа исчезнет
_STOP_RETOUCH_S = 0.5  # STOP пересоздаётся: сборщик при старте стирает «старый» STOP
_AUDIT_TIMEOUT_S = 300.0
_SIM_COMMAND_TIMEOUT_S = 10.0
_SIM_CONNECT_TIMEOUT_S = 10.0

_TOP_KEYS = (
    "recipe",
    "words",
    "zone_max_mm",
    "ports",
    "timeouts_s",
    "sim_cmd",
    "sim_env",
    "proto_cmd",
    "proto_env",
    "sim_commands",
    "collect_cmd",
    "alpha_cmd",
    "audit_cmd",
)
_PORT_KEYS = ("sim", "proto", "free_after")
_TIMEOUT_KEYS = ("backends_up", "alpha", "stop")
_COMMAND_KEYS = ("target", "command", "args")

_MECHANISM_PASS = re.compile(r"МЕХАНИЗМ:\s*PASS\b")
_MECHANISM_FAIL = re.compile(r"МЕХАНИЗМ:\s*FAIL\b")
_ITOG_COUNTS = re.compile(r"взятий\s+(\d+).*?пропусков\s+(\d+)")  # строка ИТОГ аудита: взятий N, …, пропусков S
_ALPHA_PRECONDITION_CODE = 3  # α вышла по предусловию (нет ни одной строки диска и т. п.)
_AUDIT_INPUT_CODE = 2  # аудит отказал по входу (число слов не равно числу строк слова и т. п.)
_NOT_CHECKED = "НЕ ПРОВЕРЕН"
# Узкий случай «две мягкие STOP_REQ при остановке из running» (docs/reports/2026-11-22_sim-audit-stop-req-diagnosis.md):
# единственный красный пункт α — «СТОП stop» с «STOP_REQ строк 2 ≠ 1»; критерий α «ровно одна» устарел.
_ALPHA_ONLY_STOP = re.compile(r"^МЕХАНИЗМ:\s*FAIL\s*\(СТОП stop\)\s*$", re.MULTILINE)
_ALPHA_MECH_CLASS = re.compile(r"^класс .*: МЕХАНИЗМ\s*$", re.MULTILINE)
_ALPHA_STOP_LINE = re.compile(r"^СТОП stop: STOP_REQ \[(\d+), (\d+)\].*→ FAIL: STOP_REQ строк 2 ≠ 1\s*$", re.MULTILINE)
_EXCHANGE_STOP = re.compile(r"\bin W\*? STOP_REQ = (\d+)")
_EXCHANGE_LOG = ("devices", "robot_exchange.log")  # относительно каталога логов прототипа
_SOFT_LEVEL = 1  # STOP_REQ = seq*4 + уровень; SOFT = 1 (client_v2._issue_stop_locked)
_STOP_INFO = (
    "СТОП α: информативно (2 мягких STOP_REQ: пауза + выключение; критерий α «ровно одна» устарел, "
    "см. sim-audit-stop-req-diagnosis.md)"
)
_PASS_SOFT = "PASS~"
_REASON_LIMIT = 200

type ClientFactory = Callable[[int], Any]  # port -> клиент backend_ctl (BackendDriver или фейк)


class ConfigError(Exception):
    """Ошибка аргументов или конфига: текст содержит имена ключей, но не их значения."""


class StartError(Exception):
    """Предусловие или запуск сорвался (код 3)."""


# --- конфиг -----------------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class Config:
    recipe: str
    words: list[str]
    zone_max_mm: int | float
    port_sim: int
    port_proto: int
    free_after: list[int]
    backends_up_s: float
    alpha_s: float
    stop_s: float
    sim_cmd: list[str]
    sim_env: dict[str, str]
    proto_cmd: list[str]
    proto_env: dict[str, str]
    sim_commands: list[dict[str, Any]]
    collect_cmd: list[str]
    alpha_cmd: list[str]
    audit_cmd: list[str]


def _is_number(value: Any) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


def _is_port(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and 0 < value < 65536


def _check_keys(section: str, data: Any, expected: tuple[str, ...]) -> dict:
    if not isinstance(data, dict):
        raise ConfigError(f"{section}: ожидается словарь")
    unknown = sorted(str(key) for key in data if key not in expected)
    if unknown:
        raise ConfigError(f"{section}: неизвестные ключи: {', '.join(unknown)}")
    missing = [key for key in expected if key not in data]
    if missing:
        raise ConfigError(f"{section}: нет обязательных ключей: {', '.join(missing)}")
    return data


def _str_list(name: str, value: Any) -> list[str]:
    if not isinstance(value, list) or not value or not all(isinstance(item, str) and item for item in value):
        raise ConfigError(f"{name}: ожидается непустой список непустых строк")
    return list(value)


def _env_dict(name: str, value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        raise ConfigError(f"{name}: ожидается словарь")
    result: dict[str, str] = {}
    for key, item in value.items():
        if not isinstance(key, str) or not (isinstance(item, str) or _is_number(item)):
            raise ConfigError(f"{name}: ключи и значения окружения — строки или числа")
        result[key] = str(item)
    return result


def _sim_commands(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise ConfigError("sim_commands: ожидается список")
    commands: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict) or not {"target", "command"} <= set(item) or set(item) - set(_COMMAND_KEYS):
            raise ConfigError("sim_commands: элемент — словарь с ключами target, command и необязательным args")
        if not isinstance(item["target"], str) or not isinstance(item["command"], str):
            raise ConfigError("sim_commands: target и command — строки")
        if not isinstance(item.get("args", {}), dict):
            raise ConfigError("sim_commands: args — словарь")
        commands.append({"target": item["target"], "command": item["command"], "args": dict(item.get("args", {}))})
    return commands


def parse_config(data: Any) -> Config:
    """Проверить структуру конфига. Неизвестный или недостающий ключ — ``ConfigError`` (код 2)."""
    top = _check_keys("конфиг", data, _TOP_KEYS)
    if not isinstance(top["recipe"], str) or not top["recipe"]:
        raise ConfigError("recipe: ожидается непустая строка")
    words = _str_list("words", top["words"])
    if not _is_number(top["zone_max_mm"]):
        raise ConfigError("zone_max_mm: ожидается число")
    ports = _check_keys("ports", top["ports"], _PORT_KEYS)
    if not _is_port(ports["sim"]) or not _is_port(ports["proto"]):
        raise ConfigError("ports.sim и ports.proto: ожидается номер порта")
    if not isinstance(ports["free_after"], list) or not all(_is_port(item) for item in ports["free_after"]):
        raise ConfigError("ports.free_after: ожидается список номеров портов")
    timeouts = _check_keys("timeouts_s", top["timeouts_s"], _TIMEOUT_KEYS)
    if not all(_is_number(timeouts[key]) and timeouts[key] > 0 for key in _TIMEOUT_KEYS):
        raise ConfigError("timeouts_s: ожидаются положительные числа")
    return Config(
        recipe=top["recipe"],
        words=words,
        zone_max_mm=top["zone_max_mm"],
        port_sim=ports["sim"],
        port_proto=ports["proto"],
        free_after=list(ports["free_after"]),
        backends_up_s=float(timeouts["backends_up"]),
        alpha_s=float(timeouts["alpha"]),
        stop_s=float(timeouts["stop"]),
        sim_cmd=_str_list("sim_cmd", top["sim_cmd"]),
        sim_env=_env_dict("sim_env", top["sim_env"]),
        proto_cmd=_str_list("proto_cmd", top["proto_cmd"]),
        proto_env=_env_dict("proto_env", top["proto_env"]),
        sim_commands=_sim_commands(top["sim_commands"]),
        collect_cmd=_str_list("collect_cmd", top["collect_cmd"]),
        alpha_cmd=_str_list("alpha_cmd", top["alpha_cmd"]),
        audit_cmd=_str_list("audit_cmd", top["audit_cmd"]),
    )


def load_config(path: Path) -> Config:
    """Прочитать и проверить конфиг; в тексте ошибок нет ни пути, ни значений."""
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError(f"файл конфига не прочитан ({type(exc).__name__})") from exc
    try:
        data = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        raise ConfigError("конфиг не разбирается как YAML") from exc
    return parse_config(data)


# --- порты ------------------------------------------------------------------------------------------------------------
def port_open(port: int) -> bool:
    """Порт отвечает на TCP-соединение (loopback)."""
    import socket

    try:
        with socket.create_connection((_LOOPBACK, port), timeout=_PORT_PROBE_S):
            return True
    except OSError:
        return False


def _who_holds(port: int) -> str:
    """Кто слушает порт (``lsof``, если есть); сбой определения — в тексте, не молчание."""
    lsof = shutil.which("lsof") or ("/usr/sbin/lsof" if Path("/usr/sbin/lsof").exists() else None)
    if lsof is None:
        return "владелец не определён (нет lsof)"
    try:
        found = subprocess.run(
            [lsof, "-nP", f"-iTCP:{port}", "-sTCP:LISTEN"], capture_output=True, text=True, timeout=5, check=False
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return f"владелец не определён ({type(exc).__name__})"
    owners = ["/".join(line.split()[:2]) for line in found.stdout.splitlines()[1:] if line.strip()]
    return ", ".join(owners) or "владелец не определён"


def _busy_ports(ports: list[int], grace_s: float = 0.0) -> list[int]:
    """Порты из списка, которые отвечают; ``grace_s`` — сколько ждать, пока они освободятся."""
    deadline = time.monotonic() + grace_s
    while True:
        busy = [port for port in ports if port_open(port)]
        if not busy or time.monotonic() >= deadline:
            return busy
        time.sleep(_POLL_S)


# --- процессы ---------------------------------------------------------------------------------------------------------
@dataclass
class Launched:
    """Процесс, запущенный скриптом (в своей группе: уборка по группе, чужие процессы не задеваются)."""

    name: str
    proc: subprocess.Popen


def _launch(name: str, argv: list[str], env: dict[str, str], cwd: Path, out_file: Path) -> Launched:
    group: dict[str, Any] = (
        {"start_new_session": True} if _POSIX else {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    )
    with out_file.open("wb") as sink:  # дочерний процесс держит свой дубликат дескриптора
        proc = subprocess.Popen(
            argv, cwd=cwd, env=env, stdin=subprocess.DEVNULL, stdout=sink, stderr=subprocess.STDOUT, **group
        )
    return Launched(name, proc)


def _group_alive(item: Launched) -> bool:
    if item.proc.poll() is None:
        return True
    if not _POSIX:
        return False
    try:
        os.killpg(item.proc.pid, 0)  # ведущий умер, но в группе остались члены
    except (ProcessLookupError, PermissionError):  # PermissionError: зомби на BSD/macOS
        return False
    return True


def _send(item: Launched, *, kill: bool) -> None:
    try:
        if _POSIX:
            import signal

            os.killpg(item.proc.pid, signal.SIGKILL if kill else signal.SIGTERM)
        elif kill:
            item.proc.kill()
        else:
            item.proc.terminate()
    except (ProcessLookupError, PermissionError):
        pass  # уже ушёл


def stop_items(items: list[Launched], stop_s: float) -> list[str]:
    """SIGTERM всем живым, через ``stop_s`` SIGKILL оставшимся; возвращает имена убитых принудительно."""
    for item in items:
        if _group_alive(item):
            _send(item, kill=False)
    deadline = time.monotonic() + stop_s
    while time.monotonic() < deadline and any(_group_alive(item) for item in items):
        time.sleep(0.1)
    forced: list[str] = []
    for item in items:
        if _group_alive(item):
            _send(item, kill=True)
            forced.append(item.name)
    deadline = time.monotonic() + _KILL_GRACE_S
    while time.monotonic() < deadline and any(_group_alive(item) for item in items):
        time.sleep(0.1)
    return forced


# --- подстановки и среда ----------------------------------------------------------------------------------------------
def _substitute(text: str, values: dict[str, str]) -> str:
    for key, value in values.items():
        text = text.replace("{" + key + "}", value)
    return text


def _argv(cmd: list[str], values: dict[str, str]) -> list[str]:
    argv = [_substitute(item, values) for item in cmd]
    if argv[0] in ("python", "python3"):
        argv[0] = sys.executable
    return argv


def _child_env(extra: dict[str, str], values: dict[str, str]) -> dict[str, str]:
    env = dict(os.environ)
    env.update({"PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"})  # вывод шагов читается как UTF-8
    env.update({key: _substitute(value, values) for key, value in extra.items()})
    return env


# --- клиент сима ------------------------------------------------------------------------------------------------------
def _default_client_factory(tree: Path) -> ClientFactory:
    def make(port: int) -> Any:
        if str(tree) not in sys.path:
            sys.path.insert(0, str(tree))
        from backend_ctl.driver import BackendDriver

        return BackendDriver(port=port)

    return make


def _reply_ok(reply: Any) -> bool:
    """Ответ команды лежит в ``result`` (как у collect.py); успех — ``success``/``status: ok``/``ok``."""
    inner = reply.get("result") if isinstance(reply, dict) else None
    body = inner if isinstance(inner, dict) else reply
    if not isinstance(body, dict):
        return False
    return body.get("success") is True or body.get("status") == "ok" or body.get("ok") is True


def _send_sim_commands(cfg: Config, client_factory: ClientFactory) -> None:
    """Единственная запись скрипта в сим: команды из конфига; ответ без успеха — ``StartError``."""
    if not cfg.sim_commands:
        return
    client = None
    try:
        client = client_factory(cfg.port_sim)
        client.connect(timeout=_SIM_CONNECT_TIMEOUT_S)
        for item in cfg.sim_commands:
            reply = client.send_command(item["target"], item["command"], item["args"], timeout=_SIM_COMMAND_TIMEOUT_S)
            if not _reply_ok(reply):
                raise StartError(f"команда сима {item['command']} не принята (ответ без success)")
    except StartError:
        raise
    except Exception as exc:  # noqa: BLE001 — любой отказ клиента = срыв запуска (код 3)
        raise StartError(f"команда сима не отправлена ({type(exc).__name__})") from exc
    finally:
        close = getattr(client, "close", None)
        if close is not None:
            try:
                close()
            except Exception as exc:  # noqa: BLE001 — закрытие не маскирует исход, но не молчит
                print(f"закрытие клиента сима: {type(exc).__name__}", file=sys.stderr)


def _sim_changes(cfg: Config) -> str:
    """Что скрипт изменил в симе (строка для вердикта)."""
    if not cfg.sim_commands:
        return "не менялись"
    parts = []
    for item in cfg.sim_commands:
        args = item["args"]
        if item["command"] == "scene.defect_rate" and _is_number(args.get("probability")):
            parts.append(f"defect_rate {float(args['probability'])}")
        else:
            parts.append(f"{item['command']} {args}")
    return ", ".join(parts)


# --- шаги прогона -----------------------------------------------------------------------------------------------------
def _wait_backends(cfg: Config, sim: Launched, proto: Launched) -> None:
    deadline = time.monotonic() + cfg.backends_up_s
    while True:
        for item in (sim, proto):
            code = item.proc.poll()
            if code is not None:
                raise StartError(f"{item.name} завершился до открытия порта (код {code})")
        if port_open(cfg.port_sim) and port_open(cfg.port_proto):
            return
        if time.monotonic() >= deadline:
            raise StartError(f"сим или прототип не открыл порт за {cfg.backends_up_s:g} с")
        time.sleep(_POLL_S)


def _stop_collector(collector: Launched, collect_dir: Path, stop_s: float) -> bool:
    """STOP-файл сборщику (после α); ``True`` — сборщик вышел за ``stop_s``."""
    stop_file = collect_dir / "STOP"
    deadline = time.monotonic() + stop_s
    while True:
        if not stop_file.exists():
            collect_dir.mkdir(parents=True, exist_ok=True)
            stop_file.touch()
        try:
            collector.proc.wait(timeout=_STOP_RETOUCH_S)
            return True
        except subprocess.TimeoutExpired:
            if time.monotonic() >= deadline:
                return False


def _run_audit(cfg: Config, argv: list[str], env: dict[str, str], tree: Path, out: Path) -> int | None:
    """Код аудита; ``None`` — не запустился или завис дольше ``_AUDIT_TIMEOUT_S``."""
    try:
        audit = _launch("audit", argv, env, tree, out / "audit.out")
    except OSError as exc:
        print(f"аудит не запущен ({type(exc).__name__})", file=sys.stderr)
        return None
    try:
        return audit.proc.wait(timeout=_AUDIT_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        stop_items([audit], cfg.stop_s)
        return None
    finally:
        if _group_alive(audit):
            stop_items([audit], cfg.stop_s)


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _last_line(text: str, prefix: str) -> str | None:
    lines = [line.strip() for line in text.splitlines() if line.strip().startswith(prefix)]
    return lines[-1] if lines else None


@dataclass
class RunOutcome:
    k: int
    run_dir: Path
    status: str  # PASS | PASS~ | FAIL | НЕ ПРОВЕРЕН | СРЫВ
    accuracy: str | None = None


def _soft_stop_pair(alpha_text: str, exchange_text: str) -> bool:
    """Узкий случай: красен ровно один пункт α — «СТОП stop: STOP_REQ строк 2 ≠ 1», обе записи мягкие.

    Условия (все): строка ``МЕХАНИЗМ: FAIL (СТОП stop)`` без других пунктов; ровно одна строка ``класс … : МЕХАНИЗМ``;
    ровно одна строка ``СТОП stop: STOP_REQ [a, b] … → FAIL: STOP_REQ строк 2 ≠ 1``, ``a % 4 == b % 4 == 1`` (SOFT);
    в журнале обмена последней инкарнации ровно эти две записи ``STOP_REQ`` и после них строка ``disconnect``.
    Любое иное сочетание — ``False`` (остаётся FAIL).
    """
    if len(_ALPHA_ONLY_STOP.findall(alpha_text)) != 1 or len(_ALPHA_MECH_CLASS.findall(alpha_text)) != 1:
        return False
    lines = _ALPHA_STOP_LINE.findall(alpha_text)
    if len(lines) != 1:
        return False
    first, second = (int(n) for n in lines[0])
    if first % 4 != _SOFT_LEVEL or second % 4 != _SOFT_LEVEL:
        return False
    incarnation = (
        exchange_text[exchange_text.rfind("connect ok") + 1 :] if "connect ok" in exchange_text else exchange_text
    )
    found = list(_EXCHANGE_STOP.finditer(incarnation))
    if [int(m.group(1)) for m in found] != [first, second]:
        return False
    return "disconnect" in incarnation[found[-1].end() :]


def _not_checked_reason(alpha_code: int | None, audit_code: int | None, audit_text: str) -> str | None:
    """Почему сценарий не дошёл до проверки провода (одной строкой), иначе ``None``.

    Не дошёл: α вышла по предусловию (код 3), аудит отказал по входу (код 2) или аудит прошёл, а в прогоне нет ни
    одной строки диска (``ИТОГ: … взятий 0 … пропусков 0``). Это не FAIL провода: проверять было нечего.
    """
    if alpha_code == _ALPHA_PRECONDITION_CODE:
        return f"α вышла по предусловию, код {_ALPHA_PRECONDITION_CODE}"
    if audit_code == _AUDIT_INPUT_CODE:
        lines = [line.strip() for line in audit_text.splitlines() if line.strip()]
        detail = f": {lines[-1][:_REASON_LIMIT]}" if lines else ""
        return f"аудит отказал по входу, код {_AUDIT_INPUT_CODE}{detail}"
    counts = _ITOG_COUNTS.search(_last_line(audit_text, "ИТОГ:") or "")
    if counts and counts.group(1) == counts.group(2) == "0":
        return "в прогоне нет ни одной строки диска (взятий 0, пропусков 0)"
    return None


def _verdict_text(
    cfg: Config,
    k: int,
    run_dir: Path,
    gui: bool,
    failed: list[str],
    codes: dict[str, Any],
    forced: list[str],
    accuracy: str | None,
    itog: str | None,
    not_checked: str | None = None,
    stop_info: bool = False,
) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    lines = [f"# Вердикт сквозной проверки {cfg.recipe}, прогон {k}", ""]
    if not_checked:
        lines.append(f"МЕХАНИЗМ: {_NOT_CHECKED} (сценарий не дошёл: {not_checked})")
    else:
        lines.append(f"МЕХАНИЗМ: {'FAIL' if failed else (_PASS_SOFT if stop_info else 'PASS')}")
    lines.extend(f"причина: {key}" for key in failed)
    if stop_info:
        lines.append(_STOP_INFO)
    lines += ["", accuracy or "ТОЧНОСТЬ: строки нет в alpha.out", itog or "ИТОГ: строки нет в audit.out", ""]
    lines += [f"- метка времени: {stamp}", f"- режим: {'gui' if gui else 'headless'}", f"- каталог прогона: {run_dir}"]
    lines += [f"- файл: {run_dir / name}" for name in ("sim.out", "proto.out", "collect.out", "alpha.out", "audit.out")]
    lines += [f"- файл: {run_dir / 'audit.md'}", f"- файл: {run_dir / 'verdict.md'}"]
    lines += [f"- код {label}: {codes.get(key)}" for key, label in (("alpha", "α"), ("audit", "аудита"))]
    lines.append(f"- код сборщика: {codes.get('collect')}")
    if forced:
        lines.append(f"- остановлены принудительно (SIGKILL): {', '.join(forced)}")
    lines += ["", f"# дефекты сима: {_sim_changes(cfg)}", ""]
    return "\n".join(lines)


_STAGES = (
    ("ports_free_before", "Порты свободны до старта"),
    ("sim_start", "Запуск сима"),
    ("proto_start", "Запуск прототипа"),
    ("backends_up", "Порты сима и прототипа отвечают"),
    ("sim_commands", "Команды сима"),
    ("collector_start", "Запуск сборщика"),
    ("alpha", "Сценарий α"),
    ("collector_stop", "Остановка сборщика"),
    ("stop_processes", "Остановка процессов"),
    ("ports_free_after", "Порты свободны после остановки"),
    ("audit", "Аудит провода"),
    ("verdict", "Вердикт"),
)


def _stamp() -> str:
    moment = datetime.now()
    return f"{moment:%Y-%m-%d %H:%M:%S},{moment.microsecond // 1000:03d}"


def _exc_note(exc: BaseException) -> str:
    """Краткая причина без значений аргументов: текст ``StartError`` (порты, имена команд) или имя исключения."""
    if isinstance(exc, StartError):
        return str(exc)
    return "прервано" if isinstance(exc, KeyboardInterrupt) else type(exc).__name__


class _Step:
    def __init__(self, log: StageLog, stage_id: str) -> None:
        self._log, self._id = log, stage_id
        self.ok, self.note = True, ""

    def set(self, ok: bool, note: str = "") -> None:
        self.ok, self.note = ok, note

    def __enter__(self) -> _Step:
        self._log.update(self._id, "running")
        return self

    def __exit__(self, exc_type: Any, exc: BaseException | None, tb: Any) -> None:
        if exc is not None:
            self._log.update(self._id, "fail", _exc_note(exc))
        else:
            self._log.update(self._id, "pass" if self.ok else "fail", self.note)


class StageLog:
    """``<out>/stages.json``: этапы прогона и их статусы для читателя снаружи; каждая запись атомарна."""

    def __init__(self, run_dir: Path, recipe: str, k: int, gui: bool) -> None:
        self._path = run_dir / "stages.json"
        self._doc: dict[str, Any] = {
            "recipe": recipe,
            "run": k,
            "mode": "gui" if gui else "headless",
            "stages": [
                {"id": sid, "title": title, "status": "pending", "started": None, "finished": None, "note": ""}
                for sid, title in _STAGES
            ],
        }
        self._flush()

    def _flush(self) -> None:
        tmp = self._path.with_name("stages.json.tmp")
        tmp.write_text(json.dumps(self._doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, self._path)

    def update(self, stage_id: str, status: str, note: str = "") -> None:
        stage = next(item for item in self._doc["stages"] if item["id"] == stage_id)
        stage["status"] = status
        if status == "running":
            stage["started"] = _stamp()
        else:
            stage["finished"] = _stamp()
            stage["note"] = note
        self._flush()

    def step(self, stage_id: str) -> _Step:
        return _Step(self, stage_id)

    def skip_pending(self, keep: tuple[str, ...] = ()) -> None:
        """Шаг упал: не начатые этапы (кроме ``keep``) становятся ``skipped``."""
        for stage in self._doc["stages"]:
            if stage["status"] == "pending" and stage["id"] not in keep:
                stage["status"] = "skipped"
        self._flush()


def run_once(cfg: Config, k: int, label_dir: Path, tree: Path, gui: bool, client_factory: ClientFactory) -> RunOutcome:
    """Шаги а–м одного прогона. ``StartError`` — код 3; остальное попадает в вердикт."""
    run_dir = label_dir / f"run{k}"
    log_dir = run_dir / "logs_prototype"
    log_dir.mkdir(parents=True)
    stages = StageLog(run_dir, cfg.recipe, k, gui)
    try:
        with stages.step("ports_free_before"):
            busy = _busy_ports(cfg.free_after)
            if busy:
                owners = "; ".join(f"{port}: {_who_holds(port)}" for port in busy)
                raise StartError(f"занят порт до старта ({owners})")
    except BaseException:
        stages.skip_pending()
        raise
    values = {
        "tree": str(tree),
        "out": str(run_dir),
        "log_dir": str(log_dir),
        "words": ",".join(cfg.words),
        "zone_max_mm": str(cfg.zone_max_mm),
        "proto_port": str(cfg.port_proto),
        "sim_port": str(cfg.port_sim),
    }
    proto_argv = _argv(cfg.proto_cmd, values) + ([] if gui else ["--headless"])
    launched: list[Launched] = []
    alpha_problem: str | None = None
    alpha_code: int | None = None
    alpha_ok = False
    stop_info = False
    collector_ok = False
    collector: Launched | None = None
    forced: list[str] = []
    processes_ok = False
    try:
        print(f"[run{k}] старт сима и прототипа", flush=True)
        with stages.step("sim_start"):
            sim = _launch("sim", _argv(cfg.sim_cmd, values), _child_env(cfg.sim_env, values), tree, run_dir / "sim.out")
            launched.append(sim)
        with stages.step("proto_start"):
            proto = _launch("proto", proto_argv, _child_env(cfg.proto_env, values), tree, run_dir / "proto.out")
            launched.append(proto)
        with stages.step("backends_up"):
            _wait_backends(cfg, sim, proto)
        with stages.step("sim_commands") as step:
            _send_sim_commands(cfg, client_factory)  # до сборщика и α
            step.set(True, "" if cfg.sim_commands else "команд нет")
        with stages.step("collector_start"):
            collector = _launch(
                "collect", _argv(cfg.collect_cmd, values), _child_env({}, values), tree, run_dir / "collect.out"
            )
            launched.append(collector)
        print(f"[run{k}] запуск α (до {cfg.alpha_s:g} с)", flush=True)
        with stages.step("alpha") as step:
            try:
                alpha = _launch(
                    "alpha", _argv(cfg.alpha_cmd, values), _child_env({}, values), tree, run_dir / "alpha.out"
                )
                launched.append(alpha)
                try:
                    alpha_code = alpha.proc.wait(timeout=cfg.alpha_s)
                except subprocess.TimeoutExpired:
                    alpha_problem = "таймаут"
                    stop_items([alpha], cfg.stop_s)  # α кончилась до STOP сборщику
            except Exception as exc:  # noqa: BLE001 — падение α = FAIL с причиной, уборка и аудит идут дальше
                alpha_problem = type(exc).__name__
                print(f"[run{k}] α сорвалась: {alpha_problem}", file=sys.stderr)
            alpha_text = _read(run_dir / "alpha.out")
            alpha_clean = bool(_MECHANISM_PASS.search(alpha_text)) and not _MECHANISM_FAIL.search(alpha_text)
            stop_info = (
                alpha_problem is None
                and not alpha_clean
                and _soft_stop_pair(alpha_text, _read(log_dir.joinpath(*_EXCHANGE_LOG)))
            )
            alpha_ok = alpha_problem is None and (alpha_clean or stop_info)
            accuracy = _last_line(alpha_text, "ТОЧНОСТЬ:")
            reason = "" if alpha_ok else (alpha_problem or "МЕХАНИЗМ не PASS")
            step.set(alpha_ok, "; ".join(part for part in (reason, _STOP_INFO if stop_info else "", accuracy) if part))
        with stages.step("collector_stop") as step:
            try:
                collector_ok = _stop_collector(collector, run_dir / "collect", cfg.stop_s)
            except Exception as exc:  # noqa: BLE001 — сборщик не остановлен: причина сборщик, уборка добьёт
                print(f"[run{k}] STOP сборщику не создан: {type(exc).__name__}", file=sys.stderr)
            step.set(collector_ok, "" if collector_ok else f"не вышел за {cfg.stop_s:g} с")
    except BaseException:
        stages.skip_pending(keep=("stop_processes",))
        raise
    finally:
        with stages.step("stop_processes") as step:
            forced = stop_items(launched, cfg.stop_s)
            processes_ok = not any(_group_alive(item) for item in launched)
            step.set(processes_ok, f"SIGKILL: {', '.join(forced)}" if forced else "")
    with stages.step("ports_free_after") as step:
        ports_busy = _busy_ports(cfg.free_after, _PORTS_GRACE_S)
        step.set(not ports_busy, f"заняты: {', '.join(map(str, ports_busy))}" if ports_busy else "")
    with stages.step("audit") as step:
        audit_code = _run_audit(cfg, _argv(cfg.audit_cmd, values), _child_env({}, values), tree, run_dir)
        step.set(audit_code == 0, "" if audit_code == 0 else f"код {audit_code}")

    with stages.step("verdict") as step:
        checks = (
            ("alpha", alpha_ok),
            ("audit", audit_code == 0),
            ("порты", not ports_busy),
            ("процессы", processes_ok),
            ("сборщик", collector_ok),
        )
        failed = [key for key, ok in checks if not ok]
        codes = {"alpha": alpha_problem or alpha_code, "audit": audit_code, "collect": collector.proc.returncode}
        audit_text = _read(run_dir / "audit.out")
        not_checked = _not_checked_reason(alpha_code, audit_code, audit_text)
        if set(failed) - {"alpha", "audit"}:
            not_checked = None  # порты, процессы, сборщик: сбой уборки — настоящий FAIL, а не «не дошёл»
        text = _verdict_text(
            cfg,
            k,
            run_dir,
            gui,
            failed,
            codes,
            forced,
            accuracy,
            _last_line(audit_text, "ИТОГ:"),
            not_checked,
            stop_info,
        )
        (run_dir / "verdict.md").write_text(text, encoding="utf-8")
        print(text, flush=True)
        step.set(not failed and not not_checked, f"{_NOT_CHECKED}: {not_checked}" if not_checked else ", ".join(failed))
    if not_checked:
        return RunOutcome(k, run_dir, _NOT_CHECKED, accuracy)
    return RunOutcome(k, run_dir, "FAIL" if failed else (_PASS_SOFT if stop_info else "PASS"), accuracy)


def _summary_text(cfg: Config, rows: list[RunOutcome], runs: int) -> str:
    def cell(text: str) -> str:
        return text.replace("|", "\\|")

    lines = [f"# Сводка сквозной проверки {cfg.recipe}: {len(rows)} из {runs} прогонов", ""]
    lines += ["| прогон | МЕХАНИЗМ | ТОЧНОСТЬ (информативно) | путь |", "|---|---|---|---|"]
    for row in rows:
        lines.append(
            f"| run{row.k} | {row.status} | {cell(row.accuracy or '—')} | {cell(str(row.run_dir / 'verdict.md'))} |"
        )
    return "\n".join(lines) + "\n"


# --- вход -------------------------------------------------------------------------------------------------------------
class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        self.exit(2, "ошибка аргументов командной строки (подробности: --help)\n")  # значения аргументов не печатаем


def _positive_int(text: str) -> int:
    value = int(text)
    if value < 1:
        raise argparse.ArgumentTypeError("значение должно быть >= 1")
    return value


def _parser(default_config: Path) -> argparse.ArgumentParser:
    parser = _Parser(prog="run_chain_check.py", description=__doc__.split("\n")[0], allow_abbrev=False)
    parser.add_argument("--config", type=Path, default=default_config, help="конфиг цепочки (chain_check.yaml рядом)")
    parser.add_argument("--tree", type=Path, help="корень дерева (умолчание: git rev-parse --show-toplevel)")
    parser.add_argument("--runs", type=_positive_int, default=1, help="число прогонов подряд (1)")
    parser.add_argument("--gui", action="store_true", help="прототип с окном (без --headless)")
    parser.add_argument("--out-root", type=Path, help="каталог вывода (умолчание <tree>/data/chain_check/<рецепт>)")
    return parser


def _git_toplevel(start: Path) -> Path:
    try:
        found = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"], cwd=start, capture_output=True, text=True, timeout=10, check=False
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ConfigError(f"корень дерева не определён ({type(exc).__name__}): задайте --tree") from exc
    top = found.stdout.strip()
    if found.returncode != 0 or not top:
        raise ConfigError("корень дерева не определён: задайте --tree")
    return Path(top)


def _new_label_dir(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    label = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    for n in count():
        candidate = root / (label if n == 0 else f"{label}-{n}")
        try:
            candidate.mkdir()
        except FileExistsError:
            continue
        return candidate
    raise AssertionError("unreachable")


def main(argv: list[str] | None = None, *, client_factory: ClientFactory | None = None) -> int:
    """Точка входа; ``client_factory`` — шов для тестов (по умолчанию ``BackendDriver`` из дерева)."""
    script_dir = Path(__file__).resolve().parent
    try:
        args = _parser(script_dir / "chain_check.yaml").parse_args(argv)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 2
    try:
        cfg = load_config(args.config)
        tree = (args.tree if args.tree is not None else _git_toplevel(script_dir)).resolve()
        if not tree.is_dir():
            raise ConfigError("--tree: каталог не найден")
    except ConfigError as exc:
        print(f"ошибка: {exc}", file=sys.stderr)
        return 2
    out_root = args.out_root or tree / "data" / "chain_check" / re.sub(r"[^\w.-]", "_", cfg.recipe)
    label_dir = _new_label_dir(out_root.resolve())
    factory = client_factory or _default_client_factory(tree)
    print(f"каталог прогонов: {label_dir}", flush=True)

    rows: list[RunOutcome] = []
    code = 0
    try:
        for k in range(1, args.runs + 1):
            try:
                outcome = run_once(cfg, k, label_dir, tree, args.gui, factory)
            except StartError as exc:
                print(f"[run{k}] запуск сорван: {exc}", file=sys.stderr)
                rows.append(RunOutcome(k, label_dir / f"run{k}", "СРЫВ"))
                code = 3
                break
            except Exception as exc:  # noqa: BLE001 — непредвиденный сбой шага: уборка уже сделана, код 3
                print(f"[run{k}] непредвиденный сбой: {type(exc).__name__}: {exc}", file=sys.stderr)
                rows.append(RunOutcome(k, label_dir / f"run{k}", "СРЫВ"))
                code = 3
                break
            rows.append(outcome)
            if outcome.status == _NOT_CHECKED:
                code = 3  # сильнее FAIL: механизм не проверен, серия не прерывается
            elif outcome.status not in ("PASS", _PASS_SOFT) and code != 3:
                code = 1
    except KeyboardInterrupt:
        print("прервано: процессы прогона убраны", file=sys.stderr)
        code = 3
    (label_dir / "summary.md").write_text(_summary_text(cfg, rows, args.runs), encoding="utf-8")
    return code


def _prepare_process() -> None:
    """Только для запуска как скрипта: вывод в UTF-8 и SIGTERM как Ctrl-C (уборка в ``finally`` выполняется)."""
    import signal

    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8")

    def handler(signum: int, frame: Any) -> None:
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, handler)


if __name__ == "__main__":
    _prepare_process()
    sys.exit(main())
