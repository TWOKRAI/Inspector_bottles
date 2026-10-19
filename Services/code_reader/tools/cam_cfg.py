"""Одноразовая настройка камер ID3013 (SelfTrigger, период, любые узлы). НЕ часть продукта.

  cam_cfg.py selftrigger <ip>     TriggerMode=On, TriggerSource=SelfTrigger; печатает узел периода (cur/min/max/inc)
  cam_cfg.py period <ip> <N>      TriggerSelfTriggerPeriod = N
  cam_cfg.py show <ip>            только читает
  cam_cfg.py get <ip> NODE:TYPE ...         прочитать узлы (только чтение): GET <node> = <значение>
  cam_cfg.py set <ip> NODE:TYPE=VALUE ...   записать узлы по порядку; исходное сохраняется ДО записи,
                                            первый отказ прибора — остановка и код 1
  cam_cfg.py revert <ip>          вернуть ВСЕ сохранённые значения из cam_orig.json в обратном порядке сохранения

TYPE: enum | int | float | bool. enum: целое -> set_enum, имя -> set_enum_str. bool: 1/0/true/false.
Команды-узлы (UserSetSave и т.п.) не выполняются.
Исходные значения пишутся в cam_orig.json ДО каждой записи; при сбое шага selftrigger уже сделанное откатывается.
Старый формат файла (плоские значения TriggerMode/TriggerSource/TriggerSelfTriggerPeriod) читается как enum/enum/int.
Запись в прибор — только при закрытом захвате (стенд остановлен, IDMVS закрыт).
Не запускать два экземпляра одновременно — файл исходных перезаписывается целиком.
revert: код 1, если хоть один узел НЕ ВОЗВРАЩЁН или для ip нет сохранённых исходных.
"""

import json
import math
import os
import pathlib
import re
import sys

from Services.code_reader.sdk.api import MvCodeReaderApi

ORIG = pathlib.Path(__file__).with_name("cam_orig.json")
TYPES = ("enum", "int", "float", "bool")
# в старом формате файла значения лежали без типа
LEGACY_TYPES = {"TriggerMode": "enum", "TriggerSource": "enum", "TriggerSelfTriggerPeriod": "int"}
# порядок возврата старых (плоских) записей: зависимые узлы первыми, пока TriggerMode ещё On
LEGACY_ORDER = ("TriggerSelfTriggerPeriod", "TriggerSource", "TriggerMode")
COMMANDS = ("get", "set", "show", "selftrigger", "period", "revert")
INT_RE = re.compile(r"-?[0-9]+")
FLOAT_RE = re.compile(r"[-+]?(?:[0-9]+\.?[0-9]*|\.[0-9]+)(?:[eE][-+]?[0-9]+)?")


def load(path: pathlib.Path) -> dict:
    """Файл исходных; битый или усечённый -> SystemExit (до открытия прибора), а не трассировка посреди записи."""
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or not all(isinstance(v, dict) for v in data.values()):
            raise ValueError("ожидался объект ip -> объект узлов")
    except (OSError, ValueError) as exc:
        raise SystemExit(f"файл исходных {path} повреждён или не читается: {exc}") from None
    return data


def save(data: dict, path: pathlib.Path) -> None:
    """Атомарно: временный файл рядом, затем os.replace — сбой записи не портит прежний файл."""
    tmp = path.with_name(path.name + ".tmp")
    try:
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def read_node(api, h, name: str, typ: str):
    val = getattr(api, f"get_{typ}")(h, name)
    return val["cur"] if isinstance(val, dict) else val


def write_node(api, h, name: str, typ: str, value) -> None:
    if typ == "enum" and isinstance(value, str):
        api.set_enum_str(h, name, value)
    else:
        getattr(api, f"set_{typ}")(h, name, value)


def parse_int(raw: str, lo: int, hi: int) -> int:
    text = raw.strip()
    if not INT_RE.fullmatch(text):
        raise ValueError(f"{raw!r} — не целое (только ASCII-цифры)")
    value = int(text)
    if not lo <= value <= hi:
        raise ValueError(f"{value} вне диапазона {lo}..{hi}")
    return value


def parse_value(typ: str, raw: str):
    if typ == "int":
        return parse_int(raw, -(2**63), 2**63 - 1)
    if typ == "float":
        value = float(raw) if FLOAT_RE.fullmatch(raw.strip()) else math.nan
        if not math.isfinite(value):
            raise ValueError(f"{raw!r} — не конечное число")
        return value
    if typ == "bool":
        if raw.lower() not in ("1", "0", "true", "false"):
            raise ValueError(f"{raw!r} — ожидалось 1/0/true/false")
        return raw.lower() in ("1", "true")
    text = raw.strip()
    if INT_RE.fullmatch(text):
        return parse_int(text, 0, 2**32 - 1)
    if not text or text[0] in "+-." or text[0].isdigit():
        raise ValueError(f"{raw!r} — не имя и не целое перечисления")
    return text  # имя перечисления -> set_enum_str


def parse_node(arg: str, with_value: bool) -> tuple[str, str, object]:
    spec, eq, raw = arg.partition("=")
    name, _, typ = spec.partition(":")
    if not name or typ not in TYPES or (with_value and not eq):
        raise SystemExit(f"неверный узел {arg!r}: нужен NODE:TYPE{'=VALUE' if with_value else ''}, TYPE из {TYPES}")
    if not with_value:
        return name, typ, None
    try:
        return name, typ, parse_value(typ, raw)
    except ValueError as exc:
        raise SystemExit(f"неверное значение в {arg!r} для типа {typ}: {exc}") from None


def cmd_get(api, h, nodes: list) -> int:
    for name, typ, _ in nodes:
        try:
            print(f"GET {name} = {read_node(api, h, name, typ)}", flush=True)
        except Exception as exc:  # noqa: BLE001 — один нечитаемый узел не мешает остальным
            print(f"GET {name} = ERR {exc}", flush=True)
    return 0


def cmd_set(api, h, ip: str, nodes: list, data: dict, path: pathlib.Path) -> int:
    orig = data.setdefault(ip, {})
    for name, typ, value in nodes:
        try:
            cur = read_node(api, h, name, typ)
            entry = {"value": cur, "type": typ}
        except Exception as exc:  # noqa: BLE001 — записать всё равно, но пометить, что исходное неизвестно
            cur = None
            entry = {"value": None, "type": typ, "err": str(exc)}
        if name not in orig:  # первое исходное не перезаписывается; файл — ДО setter
            orig[name] = entry
            save(data, path)
        refusal = None
        try:
            write_node(api, h, name, typ, value)
        except Exception as exc:  # noqa: BLE001 — отказ прибора: стоп, откат делает revert
            refusal = exc
        try:
            back = read_node(api, h, name, typ)
        except Exception as exc:  # noqa: BLE001
            back = f"ERR {exc}"
        verdict = "OK" if refusal is None else f"ОТКАЗ {refusal}"
        print(f"SET {name}: было={cur} записано={value} {verdict} прочитано={back}", flush=True)
        if refusal is not None:
            return 1
    return 0


def open_cam(api: MvCodeReaderApi, ip: str):
    dev = next((d for d in api.enum_devices() if d.ip == ip), None)
    if dev is None:
        raise SystemExit(f"прибор {ip} не найден")
    print("открыт", dev.ip, dev.model, flush=True)
    return api.open(dev)


def state(api, h) -> dict:
    out = {}
    for name, getter in (
        ("TriggerMode", api.get_enum),
        ("TriggerSource", api.get_enum),
        ("TriggerSelfTriggerPeriod", api.get_int),
    ):
        try:
            out[name] = getter(h, name)
        except Exception as exc:  # noqa: BLE001 — показать, что закрыто
            out[name] = f"недоступен: {exc}"
    return out


def saved_value(orig: dict, name: str):
    entry = orig[name]
    return entry.get("value") if isinstance(entry, dict) else entry


def revert(api, h, ip: str, data: dict, only: tuple[str, ...] | None = None) -> int:
    """Вернуть исходные; число узлов, которые НЕ удалось вернуть. ``only`` — ограничить список узлов."""
    items = [(n, e) for n, e in data.get(ip, {}).items() if only is None or n in only]
    # новые записи — в обратном порядке сохранения, затем старые плоские — всегда Period -> Source -> Mode
    modern = [(n, e) for n, e in reversed(items) if isinstance(e, dict)]
    legacy = [(n, e) for n, e in items if not isinstance(e, dict)]
    legacy.sort(key=lambda item: LEGACY_ORDER.index(item[0]) if item[0] in LEGACY_ORDER else len(LEGACY_ORDER))
    failed = 0
    for name, entry in modern + legacy:
        if not isinstance(entry, dict):  # старый формат: плоское значение
            entry = {"value": entry, "type": LEGACY_TYPES.get(name)}
        if "value" not in entry or entry.get("type") not in TYPES:
            print(f"SKIP {name} (битая запись)", flush=True)
            continue
        if entry["value"] is None:
            print("SKIP", name, "— исходное не прочитано:", entry.get("err"), flush=True)
            continue
        try:
            write_node(api, h, name, entry["type"], entry["value"])
            print("возвращён", name, "=", entry["value"], flush=True)
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print("НЕ ВОЗВРАЩЁН", name, "orig=", entry["value"], exc, flush=True)
    return failed


TRIGGER_NODES = ("TriggerMode", "TriggerSource", "TriggerSelfTriggerPeriod")


def main(argv: list[str] | None = None, *, api=None, orig_path: pathlib.Path | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    orig_path = ORIG if orig_path is None else orig_path
    if len(argv) < 2:
        raise SystemExit(__doc__)
    cmd, ip, rest = argv[0], argv[1], argv[2:]
    # всё, что можно проверить без прибора, — до его открытия
    if cmd not in COMMANDS:
        raise SystemExit(f"неизвестная команда {cmd!r}; допустимы: {', '.join(COMMANDS)}")
    if cmd in ("get", "set") and not rest:
        raise SystemExit(f"{cmd}: нужен хотя бы один узел NODE:TYPE{'=VALUE' if cmd == 'set' else ''}")
    nodes = [parse_node(a, cmd == "set") for a in rest] if cmd in ("get", "set") else []
    if cmd == "period":
        if len(rest) != 1:
            raise SystemExit("period: нужен ровно один аргумент N")
        try:
            period = parse_int(rest[0], -(2**63), 2**63 - 1)
        except ValueError as exc:
            raise SystemExit(f"period: неверное N: {exc}") from None
    data = load(orig_path) if cmd in ("set", "revert", "selftrigger", "period") else {}
    if cmd == "revert" and not data.get(ip):
        print(f"нет сохранённых исходных для {ip}", flush=True)
        return 1
    if api is None:
        api = MvCodeReaderApi()
    h = open_cam(api, ip)
    rc = 0
    try:
        if cmd == "get":
            return cmd_get(api, h, nodes)
        if cmd == "set":
            return cmd_set(api, h, ip, nodes, data, orig_path)
        if cmd == "show":
            print(json.dumps(state(api, h), ensure_ascii=False, indent=1))
        elif cmd == "revert":
            rc = 1 if revert(api, h, ip, data) else 0
            print(json.dumps(state(api, h), ensure_ascii=False, indent=1))
        elif cmd == "selftrigger":
            orig = data.setdefault(ip, {})
            try:
                if "TriggerMode" not in orig:
                    orig["TriggerMode"] = api.get_enum(h, "TriggerMode")["cur"]
                    save(data, orig_path)
                mode = saved_value(orig, "TriggerMode")
                print("ORIG TriggerMode =", mode, flush=True)
                if mode != 1:
                    api.set_enum(h, "TriggerMode", 1)
                if "TriggerSource" not in orig:
                    orig["TriggerSource"] = api.get_enum(h, "TriggerSource")["cur"]
                    save(data, orig_path)
                print("ORIG TriggerSource =", saved_value(orig, "TriggerSource"), flush=True)
                api.set_enum_str(h, "TriggerSource", "SelfTrigger")
                if "TriggerSelfTriggerPeriod" not in orig:
                    try:
                        orig["TriggerSelfTriggerPeriod"] = api.get_int(h, "TriggerSelfTriggerPeriod")["cur"]
                        save(data, orig_path)
                    except Exception as exc:  # noqa: BLE001
                        print("период не прочитан:", exc, flush=True)
            except BaseException:
                print("СБОЙ — откат", flush=True)
                revert(api, h, ip, data, only=TRIGGER_NODES)  # только свои три узла, чужие сохранённые не трогаем
                raise
            print(json.dumps(state(api, h), ensure_ascii=False, indent=1))
        elif cmd == "period":
            orig = data.setdefault(ip, {})
            orig.setdefault("TriggerSelfTriggerPeriod", api.get_int(h, "TriggerSelfTriggerPeriod")["cur"])
            save(data, orig_path)
            api.set_int(h, "TriggerSelfTriggerPeriod", period)
            print(json.dumps(state(api, h), ensure_ascii=False, indent=1))
    finally:
        api.close(h)
    return rc


if __name__ == "__main__":
    sys.exit(main())
