# -*- coding: utf-8 -*-
"""
sql_module.export — экспорт результатов запросов в файлы.

TableExporter: List[Dict] -> txt (читаемый/таблица), csv, xlsx.
"""
from .table_exporter import TableExporter, ExportFormat

__all__ = ["TableExporter", "ExportFormat"]
