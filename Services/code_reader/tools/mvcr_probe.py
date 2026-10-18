# -*- coding: utf-8 -*-
"""Зонд MvCodeReader SDK поверх ``Services.code_reader.sdk``: кадр + коды + качество.

Без ``--set`` настройки прибора НЕ меняет. Открывает первый GigE-прибор, StartGrabbing, ждёт
срабатываний (кнопка), на каждое — строка JSON с полями результата и ``len_ok``
по каждому коду (``nLen`` совпал с длиной текста до нуля — проверка раскладки
``BCR_INFO_EX2`` на живом приборе). С ``--out DIR`` — ещё PNG с обведённым кодом.

Запуск:
    python Services/code_reader/tools/mvcr_probe.py [секунд] [--out DIR] [--sdk-dir DIR]
    python Services/code_reader/tools/mvcr_probe.py --selfcheck   # без прибора и без DLL
    python Services/code_reader/tools/mvcr_probe.py --params      # 7 узлов всеми getter'ами, ничего не пишет
    python Services/code_reader/tools/mvcr_probe.py 10 --set TriggerMode=enum:Off [--set УЗЕЛ=ТИП:ЗНАЧЕНИЕ ...]
        # записать узлы на время приёма (секунд в (0, 30], по умолчанию 10), затем вернуть исходные;
        # ТИП: enum|int|float|bool; строка ORIG — исходное значение на случай жёсткого убийства процесса

Доступ к прибору эксклюзивный: пока открыт IDMVS, будет 0x80020203. VPN (WireGuard)
прячет прибор от EnumDevices — 0 устройств при живом линке.
"""

from __future__ import annotations

import argparse
import ctypes as C
import json
import math
import sys
import time
from pathlib import Path
from typing import Any

# Запуск прямым путём кладёт в sys.path каталог скрипта, а не корень репозитория.
_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from Services.code_reader.sdk import (  # noqa: E402 — после правки sys.path
    BAR_TYPE_NOREAD,
    PIXEL_JPEG,
    PIXEL_MONO8,
    MvCodeReaderApi,
    RawFrame,
    SdkError,
)
from Services.code_reader.sdk import structures as S  # noqa: E402
from Services.code_reader.sdk.errors import E_NODATA  # noqa: E402


def code_record(b: S.BCR_INFO_EX2) -> dict[str, Any]:
    """Запись кода → dict для печати. ``len_ok``: nLen совпал с длиной текста до первого нуля."""
    raw = bytes(b.chCode)
    q = b.stCodeQuality
    return {
        "code": S.code_bytes(b).decode("utf-8", "replace"),
        "nLen": b.nLen,
        "len_ok": b.nLen == len(raw.split(b"\0", 1)[0]),
        "bar_type": b.nBarType,
        "noread": b.nBarType == BAR_TYPE_NOREAD,
        "pt": [[p.x, p.y] for p in b.pt],
        "angle_x10": b.nAngle,
        "ppm_x10": b.sPPM,
        "algo_ms": b.sAlgoCost,
        "sharpness": b.sSharpness,
        "has_quality": bool(b.bIsGetQuality),
        "idr_score": b.nIDRScore,
        "quality": {
            "over": q.nOverQuality,
            "decode": q.nDeCode,
            "sc": q.nSCGrade,
            "mod": q.nModGrade,
            "fpd": q.nFPDGrade,
            "an": q.nANGrade,
            "gn": q.nGNGrade,
            "uec": q.nUECGrade,
        },
        "total_proc_ms": b.nTotalProcCost,
    }


def frame_record(fr: RawFrame) -> dict[str, Any]:
    return {
        "trigger": fr.trigger_index,
        "frame_num": fr.frame_num,
        "size": [fr.width, fr.height],
        "pix": f"0x{fr.pixel_type:X}",
        "len": len(fr.image),
        "no_read_num": fr.no_read_num,
        "codes": [code_record(b) for b in fr.codes],
    }


def save_png(fr: RawFrame, codes: list[dict[str, Any]], path: Path) -> str:
    """PNG с обведёнными кодами; нераспознанный формат — сырые байты рядом."""
    import cv2
    import numpy as np

    img = None
    if fr.pixel_type == PIXEL_MONO8 and len(fr.image) >= fr.width * fr.height:
        img = np.frombuffer(fr.image[: fr.width * fr.height], np.uint8).reshape(fr.height, fr.width)
    elif fr.pixel_type == PIXEL_JPEG:
        img = cv2.imdecode(np.frombuffer(fr.image, np.uint8), cv2.IMREAD_GRAYSCALE)
    if img is None:
        raw_path = path.with_suffix(".raw")
        raw_path.write_bytes(fr.image)
        return raw_path.name
    color = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    for c in codes:
        pts = np.array(c["pt"], np.int32)
        cv2.polylines(color, [pts], True, (0, 0, 255), 3)
        cv2.putText(
            color,
            f"{c['code']} q={c['quality']['over']} s={c['idr_score']}",
            (int(pts[0][0]), int(pts[0][1]) - 10),
            cv2.FONT_HERSHEY_SIMPLEX,
            1.0,
            (0, 0, 255),
            2,
        )
    cv2.imwrite(str(path), color)
    return path.name


# Узлы, которые снимает --params (типы полей Task 2.2 зависят от ответа прибора).
PARAM_NODES = (
    "ExposureTime",
    "Gain",
    "TriggerMode",
    "TriggerSource",
    "QualityEnable",
    "LightBrightness",
    "RunningMode",
)
_SET_TYPES = ("enum", "int", "float", "bool")
_BOOL_WORDS = {"0": False, "1": True, "false": False, "true": True}
_UINT32_MAX = 2**32 - 1
_INT64_MIN, _INT64_MAX = -(2**63), 2**63 - 1
_FLOAT32_MAX = 3.4028235e38
_SET_MAX_SECONDS = 30.0  # защита от нагрева: свободный режим греет прибор
_SET_DEFAULT_SECONDS = 10.0
_LIVE_DEFAULT_SECONDS = 60.0

type NodeSet = tuple[str, str, Any]  # (узел, тип, значение)


def _parse_value(typ: str, raw: str) -> Any:
    if typ == "enum":
        if not raw:
            raise ValueError("пустое значение enum")
        try:
            number = int(raw)
        except ValueError:
            return raw  # имя значения: set_enum_str
        if not 0 <= number <= _UINT32_MAX:
            raise ValueError("enum вне [0, 2**32-1]")
        return number
    if typ == "int":
        number = int(raw)
        if not _INT64_MIN <= number <= _INT64_MAX:
            raise ValueError("int вне int64")
        return number
    if typ == "float":
        value = float(raw)
        if not math.isfinite(value) or abs(value) > _FLOAT32_MAX:
            raise ValueError("float должен быть конечным и умещаться в float32")
        return value
    if raw.lower() not in _BOOL_WORDS:
        raise ValueError("bool: 0|1|true|false")
    return _BOOL_WORDS[raw.lower()]


def parse_set(spec: str) -> NodeSet:
    """``УЗЕЛ=ТИП:ЗНАЧЕНИЕ`` → ``(узел, тип, значение)``; нарушение формата → ``ArgumentTypeError`` (код 2)."""
    name, eq, rest = spec.partition("=")
    typ, colon, raw = rest.partition(":")
    if not eq or not name or not colon:
        raise argparse.ArgumentTypeError(f"ожидается УЗЕЛ=ТИП:ЗНАЧЕНИЕ, получено {spec!r}")
    if typ not in _SET_TYPES:
        raise argparse.ArgumentTypeError(f"{spec!r}: ТИП должен быть один из {'|'.join(_SET_TYPES)}")
    if not (name.isascii() and raw.isascii()):
        raise argparse.ArgumentTypeError(f"{spec!r}: только ASCII")
    try:
        return name, typ, _parse_value(typ, raw)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"{spec!r}: {exc}") from None


def _read_node(api: Any, h: Any, name: str, typ: str) -> Any:
    """Текущее значение узла getter'ом заданного типа."""
    if typ == "enum":
        return api.get_enum(h, name)["cur"]
    if typ == "int":
        return api.get_int(h, name)["cur"]
    if typ == "float":
        return api.get_float(h, name)["cur"]
    return api.get_bool(h, name)


def _write_node(api: Any, h: Any, name: str, typ: str, value: Any) -> None:
    if typ == "enum":
        if isinstance(value, str):
            api.set_enum_str(h, name, value)
        else:
            api.set_enum(h, name, value)
    elif typ == "int":
        api.set_int(h, name, value)
    elif typ == "float":
        api.set_float(h, name, value)
    else:
        api.set_bool(h, name, value)


def _show(typ: str, value: Any) -> Any:
    return int(value) if typ == "bool" else value


def _open_first(api: Any, ip: str | None = None) -> Any:
    """Прибор → handle: первый, а с ``ip`` — с этим адресом; ``None``, если приборов нет или адреса среди них нет."""
    devices = api.enum_devices()
    print("EnumDevices n=", len(devices), flush=True)
    if not devices:
        return None
    if ip is None:
        dev = devices[0]
    else:
        matches = [d for d in devices if d.ip == ip]
        if not matches:
            print(f"ПРИБОР С IP {ip} НЕ НАЙДЕН (найдены: {', '.join(d.ip for d in devices)})", flush=True)
            return None
        dev = matches[0]
    print("  ", dev.ip, dev.model, "S/N", dev.serial, flush=True)
    return api.open(dev)


def _report(getter: Any, h: Any, name: str) -> str:
    try:
        value = getter(h, name)
    except SdkError as exc:
        return f"0x{exc.code:08X}"
    cur = value["cur"] if isinstance(value, dict) else value
    return f"OK(cur={cur})"


def run_params(api: Any, names: tuple[str, ...] = PARAM_NODES, ip: str | None = None) -> int:
    """Ничего не пишет: для каждого узла результат ВСЕХ четырёх getter'ов (тип узла = кто ответил OK)."""
    h = _open_first(api, ip)
    if h is None:
        return 1
    try:
        getters = (("enum", api.get_enum), ("int", api.get_int), ("float", api.get_float), ("bool", api.get_bool))
        for name in names:
            parts = " ".join(f"{label}={_report(getter, h, name)}" for label, getter in getters)
            print(f"NODE {name} {parts}", flush=True)
    finally:
        api.close(h)
    return 0


def _restore(api: Any, h: Any, written: list[tuple[str, str, Any]]) -> int:
    """Независимая запись оригинала каждого узла + чтение обратно; без повторов. Код 3 при любом сбое."""
    failed = 0
    interrupt: BaseException | None = None
    for name, typ, orig in written:
        try:
            _write_node(api, h, name, typ, orig)
            back = _read_node(api, h, name, typ)
        except SdkError as exc:
            print(f"RESTORE FAILED {name} orig={_show(typ, orig)} 0x{exc.code:08X}", flush=True)
            failed = 3
            continue
        except BaseException as exc:  # noqa: BLE001 — любой сбой одного узла не пропускает остальные
            print(f"RESTORE FAILED {name} orig={_show(typ, orig)} {type(exc).__name__}", flush=True)
            failed = 3
            if not isinstance(exc, Exception) and interrupt is None:
                interrupt = exc  # KeyboardInterrupt и др.: дойти до конца обхода, затем пробросить
            continue
        if back == orig:
            print(f"RESTORED {name} {_show(typ, back)}", flush=True)
        else:
            print(f"RESTORE MISMATCH {name} orig={_show(typ, orig)} now={_show(typ, back)}", flush=True)
            failed = 3
    if interrupt is not None:
        raise interrupt
    return failed


def run_session(api: Any, sets: list[NodeSet], seconds: float, out: Path | None, ip: str | None = None) -> int:
    """Приём кадров ``seconds`` секунд; ``sets`` записываются до захвата и ВСЕГДА восстанавливаются."""
    h = _open_first(api, ip)
    if h is None:
        return 1
    frames = with_code = read = noread = 0
    try:
        originals: list[tuple[str, str, Any]] = []
        for name, typ, _ in sets:
            try:
                originals.append((name, typ, _read_node(api, h, name, typ)))
            except SdkError as exc:
                print(f"НЕЧИТАЕМЫЙ УЗЕЛ {name} ({typ}): {exc}", flush=True)
                return 1
        for name, typ, orig in originals:
            print(
                f"ORIG {name}={typ}:{_show(typ, orig)}", flush=True
            )  # единственное, что остаётся при жёстком убийстве

        rc = 0
        attempted: list[tuple[str, str, Any]] = []
        grabbing = False
        try:
            for (name, typ, value), original in zip(sets, originals, strict=True):
                attempted.append(original)
                try:
                    _write_node(api, h, name, typ, value)
                except SdkError as exc:
                    print(f"ЗАПИСЬ ОТКАЗАНА {name}: {exc}", flush=True)
                    rc = 1
                    break
            if rc == 0:
                grabbing = True  # до вызова: если он начал захват и бросил, stop_grabbing всё равно нужен
                api.start_grabbing(h)
                print(f">>> ЖДУ {seconds:.0f} c — жми кнопку", flush=True)
                end = time.perf_counter() + seconds
                while time.perf_counter() < end:
                    try:
                        fr = api.get_frame(h, 1000)
                    except SdkError as exc:
                        print(exc, flush=True)
                        time.sleep(min(0.2, seconds / 4))
                        continue
                    if fr is None:
                        continue
                    frames += 1
                    if fr.codes:
                        with_code += 1
                    noread += sum(1 for c in fr.codes if c.nBarType == BAR_TYPE_NOREAD)
                    read += sum(1 for c in fr.codes if c.nBarType != BAR_TYPE_NOREAD)
                    rec = frame_record(fr)
                    rec["frame"] = frames
                    if out is not None:
                        out.mkdir(parents=True, exist_ok=True)
                        rec["file"] = save_png(fr, rec["codes"], out / f"mvcr_frame_{frames}.png")
                    print(json.dumps(rec, ensure_ascii=False), flush=True)
        finally:
            try:
                if grabbing:
                    try:
                        api.stop_grabbing(h)
                    except SdkError as exc:
                        print(exc, flush=True)
                    except Exception as exc:  # noqa: BLE001 — восстановление узлов важнее причины отказа stop
                        print(f"stop_grabbing: {type(exc).__name__}: {exc}", flush=True)
            finally:
                restore_rc = _restore(api, h, attempted)
        return restore_rc or rc
    finally:
        try:
            api.close(h)
        finally:
            fps = frames / seconds if seconds > 0 else 0.0
            print(
                f"ИТОГ кадров: {frames} с_кодом: {with_code} read: {read} noread: {noread} fps: {fps:.1f}", flush=True
            )


class _SynthLib:
    """Синтетическая DLL для ``--selfcheck``: отдаёт кадры через те же буферы, как SDK."""

    def __init__(self, frames: list[dict[str, Any] | None]) -> None:
        self.frames = list(frames)
        self.image = C.create_string_buffer(4096)
        self.result = S.RESULT_BCR_EX2()

    def MV_CODEREADER_GetOneFrameTimeoutEx2(self, h: Any, p_pdata: Any, p_info: Any, timeout: Any) -> int:
        spec = self.frames.pop(0)
        if spec is None:
            return E_NODATA
        C.memset(self.image, 0, len(self.image))
        C.memmove(self.image, spec["image"], len(spec["image"]))
        C.c_void_p.from_address(C.addressof(p_pdata._obj)).value = C.addressof(self.image)
        info = p_info._obj
        info.nWidth, info.nHeight = spec["size"]
        info.enPixelType = PIXEL_JPEG
        info.nTriggerIndex = spec["trigger"]
        info.nFrameNum = spec["trigger"]
        info.nFrameLen = len(spec["image"])
        C.memset(C.byref(self.result), 0, C.sizeof(self.result))
        self.result.nCodeNum = len(spec["codes"])
        self.result.nNoReadNum = sum(1 for text, _ in spec["codes"] if not text)
        for i, (text, bar_type) in enumerate(spec["codes"]):
            rec = self.result.stBcrInfoEx2[i]
            rec.chCode = text
            rec.nLen = len(text)
            rec.nBarType = bar_type
            for k, (x, y) in enumerate(((10, 20), (110, 20), (110, 120), (10, 120))):
                rec.pt[k].x, rec.pt[k].y = x, y
        info.UnparsedBcrList.pstCodeListEx2 = C.pointer(self.result)
        return 0


def selfcheck() -> int:
    """Разбор синтетического кадра без прибора и без DLL. Код выхода 0 — всё сошлось."""
    lib = _SynthLib(
        [
            {"image": b"\xff\xd8JPEG-1\xff\xd9", "size": (1280, 1024), "trigger": 1, "codes": [(b"QR-15MM", 2)]},
            None,  # E_NODATA
            {
                "image": b"\xff\xd8JPEG-2\xff\xd9",
                "size": (1280, 1024),
                "trigger": 2,
                "codes": [(b"", BAR_TYPE_NOREAD)],
            },
        ]
    )
    api = MvCodeReaderApi(lib=lib)
    first = api.get_frame(0x1, 1000)
    nodata = api.get_frame(0x1, 1000)
    second = api.get_frame(0x1, 1000)  # перезаписывает буферы, в которых лежал первый кадр

    checks = {
        "first_parsed": first is not None and frame_record(first)["codes"][0]["code"] == "QR-15MM",
        "len_ok": first is not None and all(c["len_ok"] for c in frame_record(first)["codes"]),
        "nodata_is_none": nodata is None,
        "first_survives_buffer_reuse": first is not None and first.image == b"\xff\xd8JPEG-1\xff\xd9",
        "noread_seen": second is not None and second.no_read_num == 1 and second.codes[0].nBarType == 1001,
    }
    for fr in (first, second):
        if fr is not None:
            print(json.dumps(frame_record(fr), ensure_ascii=False))
    print("SELFCHECK", "OK" if all(checks.values()) else "FAIL", json.dumps(checks))
    return 0 if all(checks.values()) else 1


def main(argv: list[str] | None = None, *, api: MvCodeReaderApi | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument(
        "seconds",
        nargs="?",
        type=float,
        default=None,
        help=f"сколько ждать срабатываний (по умолчанию {_LIVE_DEFAULT_SECONDS:.0f}; "
        f"с --set: {_SET_DEFAULT_SECONDS:.0f}, допустимо (0, {_SET_MAX_SECONDS:.0f}])",
    )
    parser.add_argument("--out", type=Path, default=None, help="каталог для PNG кадров (по умолчанию не пишем)")
    parser.add_argument("--sdk-dir", default=None, help="каталог с MvCodeReaderCtrl.dll (иначе env / IDMVS)")
    parser.add_argument(
        "--node",
        dest="nodes",
        action="append",
        default=[],
        metavar="ИМЯ",
        help="с --params: читать именно эти узлы вместо семи стандартных; повторяемый, только ASCII",
    )
    parser.add_argument("--ip", default=None, help="IP прибора (иначе первый из EnumDevices)")
    parser.add_argument("--selfcheck", action="store_true", help="разбор синтетического кадра без прибора")
    parser.add_argument(
        "--params", action="store_true", help="прочитать 7 узлов всеми четырьмя getter'ами, ничего не писать"
    )
    parser.add_argument(
        "--set",
        dest="sets",
        action="append",
        type=parse_set,
        default=[],
        metavar="УЗЕЛ=ТИП:ЗНАЧЕНИЕ",
        help="временно записать узел на время приёма и вернуть; ТИП: enum|int|float|bool; повторяемый",
    )
    args = parser.parse_args(argv)
    if args.params and args.sets:
        parser.error("--params ничего не пишет и несовместим с --set")
    if args.nodes and not args.params:
        parser.error("--node работает только вместе с --params")
    if args.nodes and args.sets:
        parser.error("--node только читает и несовместим с --set")
    if not all(n and n.isascii() for n in args.nodes):
        parser.error("--node: имя узла должно быть непустым и ASCII")
    seconds = args.seconds
    if args.sets:
        if seconds is None:
            seconds = _SET_DEFAULT_SECONDS
        elif not 0 < seconds <= _SET_MAX_SECONDS:
            parser.error(f"секунд с --set должно быть в (0, {_SET_MAX_SECONDS:.0f}], получено {seconds}")
    elif seconds is None:
        seconds = _LIVE_DEFAULT_SECONDS
    if args.selfcheck:
        return selfcheck()
    if api is None:
        lib = None
        if args.sdk_dir:
            from Services.code_reader.sdk.loader import load_library

            lib = load_library(args.sdk_dir)
        api = MvCodeReaderApi(lib=lib)
    if args.params:
        return run_params(api, tuple(args.nodes) or PARAM_NODES, ip=args.ip)
    return run_session(api, args.sets, seconds, args.out, args.ip)


if __name__ == "__main__":
    sys.exit(main())
