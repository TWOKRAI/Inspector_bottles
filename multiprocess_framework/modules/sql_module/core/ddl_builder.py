# -*- coding: utf-8 -*-
"""Генерация DDL из метаданных SchemaBase.

Генерирует CREATE TABLE, CREATE INDEX из вывода schema_to_table_meta().
Поддерживает диалекты SQLite, PostgreSQL, MySQL.
"""
from __future__ import annotations

from typing import Any, Dict, List, Type

from sqlalchemy import Integer, String, Float, Boolean, DateTime, Date


# ---------------------------------------------------------------------------
# Сопоставление SQLAlchemy type -> SQL type string по диалекту
# ---------------------------------------------------------------------------

_DIALECT_TYPE_MAP: Dict[str, Dict[type, str]] = {
    "sqlite": {
        Integer: "INTEGER",
        Float: "REAL",
        Boolean: "INTEGER",
        DateTime: "TIMESTAMP",
        Date: "DATE",
    },
    "postgresql": {
        Integer: "INTEGER",
        Float: "DOUBLE PRECISION",
        Boolean: "BOOLEAN",
        DateTime: "TIMESTAMP",
        Date: "DATE",
    },
    "mysql": {
        Integer: "INTEGER",
        Float: "DOUBLE",
        Boolean: "TINYINT(1)",
        DateTime: "DATETIME",
        Date: "DATE",
    },
}

# Поддерживаемые имена диалектов (для валидации)
_SUPPORTED_DIALECTS = frozenset(_DIALECT_TYPE_MAP.keys())


def _sql_type_string(sa_type: Any, dialect: str) -> str:
    """Преобразовать тип SQLAlchemy (класс или экземпляр) в SQL-строку.

    Обрабатывает ``String`` (класс без длины) и ``String(100)`` (экземпляр).
    """
    dialect_map = _DIALECT_TYPE_MAP[dialect]

    # String с длиной: String(100) -> VARCHAR(100)
    if isinstance(sa_type, String) and sa_type.length is not None:
        return f"VARCHAR({sa_type.length})"

    # String без длины (класс или экземпляр) -> TEXT
    if sa_type is String or (isinstance(sa_type, String) and sa_type.length is None):
        return "TEXT"

    # Ссылка на класс (Integer, Float, ...)
    if isinstance(sa_type, type) and sa_type in dialect_map:
        return dialect_map[sa_type]

    # Экземпляр типа (например Integer()) — сопоставить по классу
    sa_class = type(sa_type)
    if sa_class in dialect_map:
        return dialect_map[sa_class]

    return "TEXT"


def _format_default(value: Any, dialect: str) -> str:
    """Отформатировать Python default-значение как SQL-литерал."""
    if isinstance(value, bool):
        if dialect == "postgresql":
            return "TRUE" if value else "FALSE"
        return "1" if value else "0"

    if isinstance(value, int):
        return str(value)

    if isinstance(value, float):
        return repr(value)

    if isinstance(value, str):
        escaped = value.replace("'", "''")
        return f"'{escaped}'"

    return repr(value)


def _build_check(col_name: str, check_min: Any, check_max: Any) -> str:
    """Построить часть CHECK constraint (без пробела в начале)."""
    parts: List[str] = []
    if check_min is not None:
        if not isinstance(check_min, (int, float)):
            raise TypeError(f"check_min must be numeric, got {type(check_min)}")
        parts.append(f'"{col_name}" >= {check_min}')
    if check_max is not None:
        if not isinstance(check_max, (int, float)):
            raise TypeError(f"check_max must be numeric, got {type(check_max)}")
        parts.append(f'"{col_name}" <= {check_max}')

    if not parts:
        return ""
    return f"CHECK ({' AND '.join(parts)})"


class DDLBuilder:
    """Генерировать DDL (CREATE TABLE / CREATE INDEX) из schema_to_table_meta().

    Usage::

        mapper = SchemaBaseMapper()
        builder = DDLBuilder(mapper)
        stmts = builder.build_create_table(MySchema, dialect="sqlite")
        for s in stmts:
            connection.execute(text(s))
    """

    def __init__(self, schema_mapper: Any) -> None:
        """Инициализировать с mapper, имеющим ``schema_to_table_meta(cls)``."""
        self._mapper = schema_mapper

    # ------------------------------------------------------------------
    # Публичный API
    # ------------------------------------------------------------------

    def build_create_table(
        self, schema_class: Type, dialect: str = "sqlite"
    ) -> List[str]:
        """Генерировать CREATE TABLE + CREATE INDEX для схемы.

        Возвращает список SQL-строк:
        - первый элемент — всегда CREATE TABLE
        - оставшиеся — CREATE INDEX (если есть)
        """
        dialect = dialect.lower()
        if dialect not in _SUPPORTED_DIALECTS:
            raise ValueError(
                f"Unsupported dialect '{dialect}'. "
                f"Supported: {', '.join(sorted(_SUPPORTED_DIALECTS))}"
            )

        meta = self._mapper.schema_to_table_meta(schema_class)
        table_name: str = meta["table_name"]
        columns: Dict[str, Dict[str, Any]] = meta["columns"]
        primary_key: List[str] = meta["primary_key"]
        indexes: List[tuple] = meta.get("indexes", [])
        unique_together: List[tuple] = meta.get("unique_together", [])

        # --- Определения колонок ---
        col_defs: List[str] = []
        for col_name, col_info in columns.items():
            col_defs.append(
                self._column_def(col_name, col_info, primary_key, dialect)
            )

        # --- UNIQUE constraint на уровне таблицы ---
        for uniq_cols in unique_together:
            quoted = ", ".join(f'"{c}"' for c in uniq_cols)
            col_defs.append(f"UNIQUE ({quoted})")

        body = ",\n    ".join(col_defs)
        create_table = (
            f'CREATE TABLE IF NOT EXISTS "{table_name}" (\n'
            f"    {body}\n"
            f");"
        )

        statements: List[str] = [create_table]

        # --- CREATE INDEX выражения ---
        for idx_cols in indexes:
            idx_name = f"ix_{table_name}_{'_'.join(idx_cols)}"
            quoted_cols = ", ".join(f'"{c}"' for c in idx_cols)
            statements.append(
                f'CREATE INDEX IF NOT EXISTS "{idx_name}" '
                f'ON "{table_name}" ({quoted_cols});'
            )

        return statements

    def build_create_all(
        self, schema_classes: List[Type], dialect: str = "sqlite"
    ) -> List[str]:
        """Генерировать все DDL-выражения для нескольких схем."""
        statements: List[str] = []
        for cls in schema_classes:
            statements.extend(self.build_create_table(cls, dialect))
        return statements

    # ------------------------------------------------------------------
    # Внутренние вспомогательные методы
    # ------------------------------------------------------------------

    def _column_def(
        self,
        col_name: str,
        col_info: Dict[str, Any],
        primary_key: List[str],
        dialect: str,
    ) -> str:
        """Построить одно определение колонки."""
        is_pk = col_name in primary_key
        sa_type = col_info["type"]
        nullable = col_info.get("nullable", True)
        default = col_info.get("default")
        check_min = col_info.get("check_min")
        check_max = col_info.get("check_max")

        # Обнаружить auto-increment целочисленный PK
        is_auto_pk = (
            is_pk
            and col_name == "id"
            and self._is_integer_type(sa_type)
        )

        parts: List[str] = [f'"{col_name}"']

        if is_auto_pk:
            parts.append(self._auto_pk_clause(dialect))
        else:
            parts.append(_sql_type_string(sa_type, dialect))

            if is_pk:
                parts.append("PRIMARY KEY")

            if not nullable and not is_pk:
                parts.append("NOT NULL")

            if default is not None:
                parts.append(f"DEFAULT {_format_default(default, dialect)}")

            check = _build_check(col_name, check_min, check_max)
            if check:
                parts.append(check)

        return " ".join(parts)

    @staticmethod
    def _is_integer_type(sa_type: Any) -> bool:
        """Проверить, является ли sa_type Integer (класс или экземпляр)."""
        if sa_type is Integer:
            return True
        if isinstance(sa_type, type) and issubclass(sa_type, Integer):
            return True
        return isinstance(sa_type, Integer)

    @staticmethod
    def _auto_pk_clause(dialect: str) -> str:
        """Вернуть часть auto-increment PK для диалекта."""
        if dialect == "sqlite":
            return "INTEGER PRIMARY KEY AUTOINCREMENT"
        if dialect == "postgresql":
            return "SERIAL PRIMARY KEY"
        # mysql
        return "INTEGER AUTO_INCREMENT PRIMARY KEY"
