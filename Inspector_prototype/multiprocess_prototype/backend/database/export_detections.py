#!/usr/bin/env python3
# multiprocess_prototype\database\export_detections.py
"""
Экспорт детекций из inspector.db в читаемый формат или таблицу.

Использует sql_module.export.TableExporter — методы работают с объектом (List[Dict]),
сохранение через save().

Использование:
  python -m multiprocess_prototype.backend.database.export_detections [--format FORMAT] [--output FILE] [--offset N] [--limit N]

  Форматы:
    txt         — читаемый формат (ID, Время, Кадр, Bbox, Центр, Площадь)
    txt_table   — обычная таблица с разделителем |
    csv         — CSV для Excel (;)
    xlsx        — Excel (.xlsx, требует openpyxl)

  Примеры:
    python -m multiprocess_prototype.backend.database.export_detections --format txt -o detections.txt
    python -m multiprocess_prototype.backend.database.export_detections --format txt_table --limit 100
    python -m multiprocess_prototype.backend.database.export_detections --format csv --offset 10 --limit 50
"""
import sys
from pathlib import Path

from multiprocess_prototype.backend.database.utils import (
    create_detection_exporter,
    read_from_sqlite,
)
from multiprocess_framework.refactored.modules.sql_module.export import ExportFormat

_DB_PATH = Path(__file__).resolve().parent / "inspector.db"
_FORMAT_MAP = {
    "txt": ExportFormat.TXT_READABLE,
    "txt_table": ExportFormat.TXT_TABLE,
    "csv": ExportFormat.CSV,
    "xlsx": ExportFormat.XLSX,
}


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Экспорт детекций из inspector.db")
    parser.add_argument(
        "--format", "-f",
        choices=list(_FORMAT_MAP),
        default="txt",
        help="Формат: txt (читаемый), txt_table (таблица), csv, xlsx",
    )
    parser.add_argument(
        "--output", "-o",
        type=Path,
        default=None,
        help="Путь к выходному файлу",
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=_DB_PATH,
        help="Путь к БД",
    )
    parser.add_argument(
        "--offset",
        type=int,
        default=0,
        help="Начало диапазона (строка)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Макс. количество строк (по умолчанию — все)",
    )
    args = parser.parse_args()

    if not args.db.exists():
        print(f"Ошибка: файл БД не найден: {args.db}", file=sys.stderr)
        return 1

    rows = read_from_sqlite(
        args.db,
        table="detections",
        order_by="id",
        offset=args.offset,
        limit=args.limit,
    )

    fmt = _FORMAT_MAP[args.format]
    ext = "txt" if fmt in (ExportFormat.TXT_READABLE, ExportFormat.TXT_TABLE) else args.format
    output = args.output or Path(f"detections.{ext}")
    output = output.resolve()

    exporter = create_detection_exporter()
    count = exporter.save(
        rows,
        output,
        format=fmt,
        title="Детекции из inspector.db",
        sheet_name="Detections",
    )

    print(f"Экспорт {fmt.value}: {output} ({count} записей)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
