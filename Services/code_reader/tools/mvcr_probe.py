# -*- coding: utf-8 -*-
"""Зонд MvCodeReader SDK поверх ``Services.code_reader.sdk``: кадр + коды + качество.

Настройки прибора НЕ меняет. Открывает первый GigE-прибор, StartGrabbing, ждёт
срабатываний (кнопка), на каждое — строка JSON с полями результата и ``len_ok``
по каждому коду (``nLen`` совпал с длиной текста до нуля — проверка раскладки
``BCR_INFO_EX2`` на живом приборе). С ``--out DIR`` — ещё PNG с обведённым кодом.

Запуск:
    python Services/code_reader/tools/mvcr_probe.py [секунд] [--out DIR] [--sdk-dir DIR]
    python Services/code_reader/tools/mvcr_probe.py --selfcheck   # без прибора и без DLL

Доступ к прибору эксклюзивный: пока открыт IDMVS, будет 0x80020203. VPN (WireGuard)
прячет прибор от EnumDevices — 0 устройств при живом линке.
"""

from __future__ import annotations

import argparse
import ctypes as C
import json
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


def run_live(wait_s: float, out: Path | None, sdk_dir: str | None) -> int:
    lib = None
    if sdk_dir:
        from Services.code_reader.sdk.loader import load_library

        lib = load_library(sdk_dir)
    api = MvCodeReaderApi(lib=lib)
    devices = api.enum_devices()
    print("EnumDevices n=", len(devices), flush=True)
    if not devices:
        return 1
    dev = devices[0]
    print("  ", dev.ip, dev.model, "S/N", dev.serial, flush=True)
    h = api.open(dev)
    got = 0
    try:
        api.start_grabbing(h)
        print(f">>> ЖДУ {wait_s:.0f} c — жми кнопку", flush=True)
        end = time.perf_counter() + wait_s
        while time.perf_counter() < end:
            try:
                fr = api.get_frame(h, 1000)
            except SdkError as exc:
                print(exc, flush=True)
                time.sleep(0.2)
                continue
            if fr is None:
                continue
            got += 1
            rec = frame_record(fr)
            rec["frame"] = got
            if out is not None:
                out.mkdir(parents=True, exist_ok=True)
                rec["file"] = save_png(fr, rec["codes"], out / f"mvcr_frame_{got}.png")
            print(json.dumps(rec, ensure_ascii=False), flush=True)
    finally:
        try:
            api.stop_grabbing(h)
        except SdkError as exc:
            print(exc, flush=True)
        api.close(h)
        print("ИТОГ кадров:", got, flush=True)
    return 0


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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("seconds", nargs="?", type=float, default=60.0, help="сколько ждать срабатываний")
    parser.add_argument("--out", type=Path, default=None, help="каталог для PNG кадров (по умолчанию не пишем)")
    parser.add_argument("--sdk-dir", default=None, help="каталог с MvCodeReaderCtrl.dll (иначе env / IDMVS)")
    parser.add_argument("--selfcheck", action="store_true", help="разбор синтетического кадра без прибора")
    args = parser.parse_args(argv)
    if args.selfcheck:
        return selfcheck()
    return run_live(args.seconds, args.out, args.sdk_dir)


if __name__ == "__main__":
    sys.exit(main())
