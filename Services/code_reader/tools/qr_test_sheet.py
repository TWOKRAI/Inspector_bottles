# -*- coding: utf-8 -*-
"""Лист тестовых QR-кодов для настройки считывателя — печать 1:1.

Габарит кода задаётся в миллиметрах, `segno` рисует SVG прямо в мм
(`unit="mm"`), поэтому браузер печатает символ в натуральную величину.
Под каждым кодом подписан размер модуля — это та величина, с которой
сверяется колонка PPM в History у IDMVS.

Запуск:
    .venv/Scripts/python.exe Services/code_reader/tools/qr_test_sheet.py
    .venv/Scripts/python.exe Services/code_reader/tools/qr_test_sheet.py "PART-42" --sizes 8,10,12,15
    .venv/Scripts/python.exe Services/code_reader/tools/qr_test_sheet.py --selfcheck

Печатать из браузера строго в масштабе 100% («Без масштабирования» /
«Actual size»). На листе есть контрольная линейка 50 мм — проверить её
обычной линейкой ДО того, как делать выводы о читаемости кода.
"""

from __future__ import annotations

import argparse
import sys
import webbrowser
from pathlib import Path

import segno

DEFAULT_SIZES_MM = (10, 15, 20, 25, 30, 40)
QUIET_ZONE_MODULES = 4  # требование стандарта QR


def qr_block(data: str, size_mm: float, error: str, quiet: int, version: int) -> str:
    """Один код заданного габарита + подпись. Габарит — сам символ, без quiet zone."""
    qr = segno.make(data, error=error, micro=False, version=version)
    modules = qr.symbol_size(scale=1, border=0)[0]
    module_mm = size_mm / modules
    svg = qr.svg_inline(scale=module_mm, border=0, unit="mm")
    pad_mm = round(module_mm * quiet, 3)
    return f"""
    <figure class="cell">
      <div class="frame" style="padding:{pad_mm}mm">{svg}</div>
      <figcaption>
        <b>{size_mm:g} × {size_mm:g} мм</b><br>
        модуль {module_mm:.3f} мм · версия {qr.version} · {modules}×{modules}<br>
        <span class="data">{data}</span>
      </figcaption>
    </figure>"""


def payload(prefix: str, size_mm: float) -> str:
    """Каждый код несёт свой размер — в History сразу видно, какой именно прочёлся."""
    if "{size}" in prefix:
        return prefix.format(size=f"{size_mm:g}")
    return f"{prefix}-{size_mm:g}MM"


def common_version(items: list[str], error: str) -> int:
    """Одна версия QR на весь лист.

    Строки разной длины дают разные версии, а версия задаёт число модулей.
    При одинаковом габарите это означает разный размер модуля — и лист
    сравнивал бы не размеры, а плотность сетки. Берём максимум из нужных
    и печатаем все коды по нему.
    """
    return max(segno.make(s, error=error, micro=False).version for s in items)


def build_sheet(prefixes: list[str], sizes: list[float], error: str, quiet: int) -> str:
    pairs = [(payload(prefix, size), size) for prefix in prefixes for size in sizes]
    version = common_version([data for data, _ in pairs], error)
    cells = "".join(qr_block(data, size, error, quiet, version) for data, size in pairs)
    return f"""<!doctype html>
<html lang="ru"><head><meta charset="utf-8">
<title>Тестовые QR — MV-ID3013PM</title>
<style>
  @page {{ size: A4; margin: 10mm; }}
  body {{ font: 9pt/1.35 system-ui, sans-serif; color: #000; background: #fff; margin: 0; }}
  h1 {{ font-size: 12pt; margin: 0 0 2mm; }}
  .warn {{ font-size: 9pt; margin: 0 0 3mm; }}
  .ruler {{ width: 50mm; height: 4mm; border: 0.3mm solid #000;
            border-top: none; margin-bottom: 4mm;
            background: repeating-linear-gradient(to right, #000 0 0.3mm, #fff 0.3mm 10mm); }}
  .grid {{ display: flex; flex-wrap: wrap; gap: 6mm; align-items: flex-start; }}
  .cell {{ margin: 0; text-align: center; page-break-inside: avoid; }}
  .frame {{ background: #fff; display: inline-block; line-height: 0; }}
  figcaption {{ font-size: 7.5pt; margin-top: 1.5mm; }}
  .data {{ font-family: ui-monospace, Consolas, monospace; }}
</style></head><body>
<h1>Тестовые QR — печать строго 100% («Без масштабирования»)</h1>
<p class="warn">Линейка ниже должна быть ровно 50 мм, деления по 10 мм.
Не сходится — печать масштабируется, и все выводы о читаемости будут ложными.<br>
Все коды одной версии QR — отличается только габарит, поэтому сравнение честное.
Каждый код несёт свой размер в содержимом: в колонке Barcode Content видно, какой прочёлся.</p>
<div class="ruler"></div>
<div class="grid">{cells}</div>
</body></html>"""


def selfcheck() -> int:
    """Три свойства, без которых лист врёт: габарит, единая сетка, различимость."""
    import re

    # Префикс в 15 знаков: "...-10MM" = 20 символов (версия 1), "...-100MM" = 21 (версия 2).
    # Граница найдена перебором, не угадана; на коротких префиксах разъезда нет вовсе.
    sizes = [10, 12.5, 25.5, 100]
    datas = [payload("SELFCHECKPREFIX", s) for s in sizes]
    assert len(set(datas)) == len(datas), f"коды неразличимы: {datas}"

    version = common_version(datas, "m")
    modules_seen = set()
    for data, size in zip(datas, sizes):
        qr = segno.make(data, error="m", micro=False, version=version)
        modules = qr.symbol_size(scale=1, border=0)[0]
        modules_seen.add(modules)
        svg = qr.svg_inline(scale=size / modules, border=0, unit="mm")
        got = float(re.search(r'width="([\d.]+)mm"', svg).group(1))
        assert abs(got - size) < 0.01, f"габарит {got} мм вместо {size} мм"
        assert not qr.is_micro, "Micro QR — промышленные считыватели его часто не читают"

    assert len(modules_seen) == 1, f"сетка разъехалась: {modules_seen} модулей на одном листе"
    # Без version= строка "SELFCHECK-100MM" длиннее "SELFCHECK-10MM" и даёт другую сетку.
    free = {segno.make(d, error="m", micro=False).symbol_size(scale=1, border=0)[0] for d in datas}
    assert len(free) > 1, (
        "тест вырожден: на этих данных сетка не разъезжается и без фиксации версии — "
        "подбери датасет, пересекающий границу версии"
    )

    print(
        f"selfcheck ok: габариты точны, сетка одна ({modules_seen.pop()} модулей, "
        f"версия {version}), содержимое различимо; без фиксации версии было бы {sorted(free)}"
    )
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument(
        "data",
        nargs="*",
        default=["QR"],
        help="префикс содержимого; размер дописывается сам (QR -> QR-10MM). "
        "Плейсхолдер {size} задаёт позицию явно: 'LINE1-{size}mm-A'",
    )
    p.add_argument(
        "--sizes",
        default=",".join(str(s) for s in DEFAULT_SIZES_MM),
        help="габариты в мм через запятую (по умолчанию %(default)s)",
    )
    p.add_argument("--error", default="m", choices=list("lmqhLMQH"), help="уровень коррекции")
    p.add_argument("--quiet", type=int, default=QUIET_ZONE_MODULES, help="quiet zone в модулях")
    p.add_argument("--out", default="qr_test_sheet.html", help="куда сохранить")
    p.add_argument("--open", action="store_true", help="открыть в браузере после генерации")
    p.add_argument("--selfcheck", action="store_true", help="проверить геометрию и выйти")
    args = p.parse_args()

    if args.selfcheck:
        return selfcheck()

    sizes = [float(s) for s in args.sizes.split(",") if s.strip()]
    out = Path(args.out)
    out.write_text(build_sheet(args.data, sizes, args.error.lower(), args.quiet), encoding="utf-8")
    print(f"{out.resolve()}  —  {len(args.data)} × {len(sizes)} = {len(args.data) * len(sizes)} кодов")
    print("Содержимое: " + ", ".join(payload(args.data[0], s) for s in sizes[:3]) + (", …" if len(sizes) > 3 else ""))
    print("Печатать в масштабе 100%, сверить линейку 50 мм обычной линейкой.")
    if args.open:
        webbrowser.open(out.resolve().as_uri())
    return 0


if __name__ == "__main__":
    sys.exit(main())
