# Refactoring plan: `sql_module` (module #17) -- Enhanced SQL Toolkit

> **Status:** DRAFT
> **Date:** 2026-04-12
> **Author:** Opus 4.6 (Manager)
> **Executors:** TeamLead (Opus) / Developer (Sonnet) / Docs Writer (Haiku)
> **Reviewer:** Claude Code (Opus)
> **Links:** [00_overview.md](../../plans/refactoring/00_overview.md) - [ARCHITECTURE.md](../../multiprocess_framework/ARCHITECTURE.md)

---

## 0. Context

`sql_module` -- mature SQL manager for the multiprocess framework (Stage 8/8). Supports PostgreSQL, MySQL, SQLite via SQLAlchemy 2.0. Dual sync/async adapters, Unit of Work, GenericRepository, typed commands, TableExporter.

**Architectural Vision (Director decision):** Transform sql_module into a powerful, schema-aware SQL toolkit that deeply understands `SchemaBase` and `FieldMeta`. SchemaBase itself is NOT modified -- it remains a descriptor for UI/routing/registers. sql_module becomes the intelligent consumer of SchemaBase metadata for DDL generation, constraint mapping, QuerySet building, and enhanced repository operations.

**Key additions:**
1. Enhanced `SchemaBaseMapper` -- reads FieldMeta (min/max -> CHECK, defaults -> DEFAULT, Optional -> NULLABLE, readonly -> block update, max -> VARCHAR)
2. `SQLMeta` -- declarative ClassVar nested class on SchemaBase subclasses (table_name, indexes, unique_together)
3. Auto DDL -- `create_tables([schemas])` from SchemaBase + FieldMeta + SQLMeta
4. QuerySet builder -- Django-style chained queries with lookups
5. Enhanced Repository -- readonly field blocking, bulk operations, find_by
6. Legacy cleanup -- remove metrics/, fix async dispose, fix SQL injection in query_range
7. Documentation -- DECISIONS.md, ARCHITECTURE.md section 6.16, updated README/STATUS

**Complexity:** 4/5 -- QuerySet builder and Auto DDL are architecturally significant; the rest is standard implementation.

---

## 1. Current State (baseline)

### 1.1 Metrics

| Metric | Value |
|--------|-------|
| Source files (no tests) | 17 .py |
| Source LOC (no tests) | ~900 |
| Test files | 5 |
| Test count | ~20 |
| STATUS.md stage | 8/8 |

### 1.2 LOC breakdown (top files)

```
239  core/sql_manager.py
122  adapters/async_adapter.py
 92  adapters/schema_mapper.py
 84  adapters/sync_adapter.py
228  export/table_exporter.py
220  interfaces.py
 76  core/base_repository.py
 69  core/unit_of_work.py
134  core/engine_factory.py
 35  commands/db_commands.py
 43  configs/sql_manager_config.py
 35  metrics/sql_metrics.py     <- DEAD CODE
```

### 1.3 External consumers

| Module/File | Imports | Affected? |
|-------------|---------|-----------|
| `multiprocess_prototype/.../database_process.py` | `SQLManager`, `SQLManagerConfig`, `TableExporter`, `SchemaBaseMapper` | No (API only extended, not broken) |
| `multiprocess_prototype/.../export_detections.py` | `ExportFormat` | No |
| `multiprocess_prototype/.../utils.py` | `TableExporter`, `ExportFormat` | No |

### 1.4 Identified Issues

| # | Issue | Severity |
|---|-------|----------|
| P1 | `metrics/` package -- dead code (IMetricsCollector + SQLMetricsCollector). Never imported outside definitions. ObservableMixin replaces. | Medium |
| P2 | `async_adapter.dispose()` -- uses deprecated `asyncio.get_event_loop()`, unreliable in 3.10+ | Medium |
| P3 | `query_range()` -- table/order_by via f-string, no identifier validation | High |
| P4 | `SchemaBaseMapper` ignores FieldMeta entirely (min/max/readonly/defaults not read) | Feature gap |
| P5 | No Auto DDL -- tables must be created manually with raw SQL | Feature gap |
| P6 | No QuerySet builder -- all queries are raw SQL strings | Feature gap |
| P7 | Repository lacks bulk operations, find_by, readonly field protection | Feature gap |
| P8 | No DECISIONS.md, no ARCHITECTURE.md section 6.16 | Documentation gap |
| P9 | README shows `config/` instead of `configs/` in structure section | Minor |

### 1.5 SchemaBase / FieldMeta Available Metadata

From `data_schema_module/core/field_meta.py` -- what sql_module can read:

| FieldMeta attr | SQL mapping |
|----------------|-------------|
| `min` / `max` (float) | CHECK constraint (`col >= min AND col <= max`) |
| `readonly` (bool) | Repository blocks update on these fields |
| `hidden` (bool) | No SQL impact (UI only) |
| Default value (from `field_info.default`) | SQL DEFAULT clause |
| `Optional[T]` annotation | NULLABLE column |
| `max` on string fields | VARCHAR(max) instead of TEXT |

From `SchemaBase.model_fields` (Pydantic v2):
- `field_info.annotation` -- Python type -> SQLAlchemy type
- `field_info.is_required()` -- nullable detection
- `field_info.default` -- default value
- `field_info.metadata` -- list containing FieldMeta instances

---

## 2. Execution Order

### Phase 1: Legacy Cleanup & Fixes (no new features)
- Task 1.1: Remove metrics/ dead code
- Task 1.2: Fix async_adapter.dispose()
- Task 1.3: Fix SQL injection in query_range()
- Task 1.4: Fix README typo

### Phase 2: SQLMeta + Enhanced SchemaBaseMapper
- Task 2.1: Implement SQLMeta descriptor class
- Task 2.2: Enhance SchemaBaseMapper to read FieldMeta + SQLMeta

### Phase 3: Auto DDL
- Task 3.1: Implement DDLBuilder + create_tables()

### Phase 4: QuerySet Builder
- Task 4.1: Implement QuerySet class with chained API

### Phase 5: Enhanced Repository
- Task 5.1: Enhance GenericRepository (readonly protection, bulk ops, find_by)

### Phase 6: Integration into SQLManager
- Task 6.1: Wire new features into SQLManager public API

### Phase 7: Tests
- Task 7.1: Tests for Phase 1 fixes
- Task 7.2: Tests for SQLMeta + enhanced mapper
- Task 7.3: Tests for Auto DDL
- Task 7.4: Tests for QuerySet builder
- Task 7.5: Tests for enhanced Repository

### Phase 8: Documentation
- Task 8.1: DECISIONS.md
- Task 8.2: ARCHITECTURE.md section 6.16
- Task 8.3: Update README, STATUS.md, __init__.py

---

## 3. Task Specifications

---

### Task 1.1 -- Remove metrics/ dead code (P1)

**Level:** Middle (Sonnet)
**Executor:** developer
**Goal:** Delete unused metrics/ package and IMetricsCollector references.

**Files:**
- `Services/sql/metrics/sql_metrics.py` -- DELETE
- `Services/sql/metrics/__init__.py` -- DELETE
- `Services/sql/interfaces.py` -- remove IMetricsCollector (lines 165-182)
- `Services/sql/__init__.py` -- remove IMetricsCollector from imports and __all__

**Steps:**
1. Delete `metrics/sql_metrics.py` and `metrics/__init__.py` (entire `metrics/` directory)
2. In `interfaces.py`: remove the `IMetricsCollector` Protocol class (lines 165-182, the entire section including comment header)
3. In `__init__.py`: remove `IMetricsCollector` from the import line (line 22) and from `__all__` (line 50)

**Acceptance criteria:**
- [ ] `metrics/` directory no longer exists
- [ ] `grep -r "IMetricsCollector" sql_module/` returns 0 results
- [ ] `grep -r "SQLMetricsCollector" sql_module/` returns 0 results
- [ ] ` && python -m pytest Services/sql/tests -v` -- all pass
- [ ] `python -c "from sql_module import SQLManager"` -- no import errors

**Out of scope:** Do NOT remove ObservableMixin integration (_record_timing, _log_info etc.) -- that is the active metrics path.

**Dependencies:** None

---

### Task 1.2 -- Fix async_adapter.dispose() (P2)

**Level:** Middle+ (Sonnet)
**Executor:** developer
**Goal:** Replace deprecated asyncio.get_event_loop() with safe pattern in BaseAsyncAdapter.dispose().

**Files:**
- `Services/sql/adapters/async_adapter.py` -- modify dispose() (lines 77-89)

**Steps:**
1. Replace the current `dispose()` method (lines 77-89) with:
   - Try `asyncio.get_running_loop()` -- if running, schedule `engine.dispose()` as a task
   - If no running loop (`RuntimeError`), create a new loop with `asyncio.new_event_loop()`, run `engine.dispose()`, then close the loop
   - Always set `self._engine = None` and `self._initialized = False`
2. The pattern:
   ```
   try:
       loop = asyncio.get_running_loop()
       loop.create_task(self._engine.dispose())
   except RuntimeError:
       loop = asyncio.new_event_loop()
       try:
           loop.run_until_complete(self._engine.dispose())
       finally:
           loop.close()
   ```

**Acceptance criteria:**
- [ ] No usage of `asyncio.get_event_loop()` in `async_adapter.py`
- [ ] `grep "get_event_loop" sql_module/adapters/async_adapter.py` returns 0
- [ ] Existing async tests pass: ` && python -m pytest Services/sql/tests/test_adapters.py -v`

**Out of scope:** Do not refactor the entire async adapter pattern.
**Edge cases:** dispose() called when no event loop exists at all; dispose() called from within an async context.

**Dependencies:** None

---

### Task 1.3 -- Fix SQL injection in query_range() (P3)

**Level:** Middle+ (Sonnet)
**Executor:** developer
**Goal:** Validate table and order_by identifiers in query_range() to prevent SQL injection.

**Files:**
- `Services/sql/core/sql_manager.py` -- modify query_range() (lines 127-154)

**Steps:**
1. Add a private method `_validate_identifier(name: str) -> str` to SQLManager that:
   - Checks that `name` matches regex `^[a-zA-Z_][a-zA-Z0-9_]*$` (valid SQL identifier)
   - Raises `ValueError(f"Invalid SQL identifier: {name!r}")` if not matching
   - Returns the validated name
2. In `query_range()`, call `_validate_identifier(table)` and `_validate_identifier(order_by)` before building the SQL string
3. Keep the existing quoting (`"{table}"`) as defense-in-depth

**Acceptance criteria:**
- [ ] `sql_manager.query_range("users; DROP TABLE users--")` raises ValueError
- [ ] `sql_manager.query_range("valid_table", order_by="id")` works normally
- [ ] Existing tests pass

**Out of scope:** Do not change _handle_insert (table name comes from typed command, validated separately).
**Edge cases:** Table names with digits (allowed after first char), empty string (rejected), unicode (rejected).

**Dependencies:** None

---

### Task 1.4 -- Fix README typo (P9)

**Level:** Junior (Haiku)
**Executor:** docs-writer
**Goal:** Fix `config/` -> `configs/` in README structure section.

**Files:**
- `Services/sql/README.md` -- line ~170, change `config/` to `configs/`

**Steps:**
1. Find `config/` in the "Structure" section and replace with `configs/`

**Acceptance criteria:**
- [ ] `grep "config/" sql_module/README.md` returns only `configs/` (not bare `config/`)

**Dependencies:** None

---

### Task 2.1 -- Implement SQLMeta descriptor class

**Level:** Senior (Opus)
**Executor:** teamlead
**Goal:** Create SQLMeta as a declarative ClassVar nested class pattern, plus a utility to extract it from any SchemaBase subclass.

**Files:**
- `Services/sql/adapters/sql_meta.py` -- CREATE new file

**Steps:**
1. Create `sql_meta.py` with:
   - `class SQLMeta`: a plain class (not Pydantic, not dataclass) serving as a namespace. Attributes:
     - `table_name: str` (optional, default derived from class name)
     - `indexes: List[Tuple[str, ...]]` -- composite indexes (each tuple is column names)
     - `unique_together: List[Tuple[str, ...]]` -- unique constraints
     - All attributes are class-level with sensible defaults (empty lists)
   - `def extract_sql_meta(schema_class: Type[Any]) -> Dict[str, Any]`: utility function that:
     - Looks for `schema_class.SQLMeta` (hasattr check)
     - If present, reads `table_name`, `indexes`, `unique_together` from it
     - If absent, generates `table_name` from class name: lowercase, strip "Schema" suffix, add "s" (same logic as current SchemaBaseMapper)
     - Returns dict: `{"table_name": str, "indexes": list, "unique_together": list}`
2. SQLMeta lives in sql_module (NOT in data_schema_module). It is ClassVar so Pydantic ignores it entirely. SchemaBase is NOT modified.

**Usage example (for understanding, NOT code to write):**
```python
class UserSchema(SchemaBase):
    class SQLMeta:
        table_name = "users"
        indexes = [("email",), ("name", "age")]
        unique_together = [("email",)]
    id: int | None = None
    name: str
    email: str
    age: int = 0
```

**Acceptance criteria:**
- [ ] `extract_sql_meta(UserSchemaWithSQLMeta)` returns correct table_name, indexes, unique_together
- [ ] `extract_sql_meta(SchemaWithoutSQLMeta)` returns derived table_name and empty lists
- [ ] SQLMeta does NOT affect Pydantic serialization: `UserSchema.model_fields` has no "SQLMeta" key
- [ ] File exists: `sql_module/adapters/sql_meta.py`

**Out of scope:** Do NOT touch SchemaBase or FieldMeta in data_schema_module. Do NOT add any import of sql_module into data_schema_module.
**Edge cases:** Class named "Schema" (table_name -> "s"), class with no fields (empty columns dict).

**Dependencies:** None

---

### Task 2.2 -- Enhance SchemaBaseMapper to read FieldMeta + SQLMeta

**Level:** Senior (Opus)
**Executor:** teamlead
**Goal:** SchemaBaseMapper.schema_to_table_meta() reads FieldMeta constraints and SQLMeta, producing rich table metadata.

**Files:**
- `Services/sql/adapters/schema_mapper.py` -- major rewrite of SchemaBaseMapper

**Steps:**
1. Import `extract_sql_meta` from `sql_module.adapters.sql_meta`
2. Rewrite `schema_to_table_meta()` to:
   - Call `extract_sql_meta(schema_class)` for table_name, indexes, unique_together
   - For each field in `schema_class.model_fields`:
     - Extract base type via existing `_get_annotation_type()`
     - Map to SQLAlchemy type via `_python_type_to_sqlalchemy()`
     - **NEW:** Check for FieldMeta in `field_info.metadata`:
       - `FieldMeta.min` / `FieldMeta.max` on numeric fields -> add `"check_min"` / `"check_max"` to column dict
       - `FieldMeta.max` on string fields (when base type is `str`) -> use `String(max)` instead of `String()` (VARCHAR with length)
       - `FieldMeta.readonly` -> add `"readonly": True` to column dict
     - **NEW:** Check `field_info.default` (not `PydanticUndefined`) -> add `"default"` to column dict
     - **NEW:** Check nullable via `Optional[T]` detection (existing logic) plus `field_info.is_required() is False`
   - Return enriched dict with: `table_name`, `columns` (each with type, nullable, check_min, check_max, default, readonly), `primary_key`, `indexes`, `unique_together`
3. Keep backward compatibility: existing callers that read only `table_name`, `columns.type`, `columns.nullable`, `primary_key` still work
4. Add `_TYPE_MAP` entry for `datetime.date` -> `Date`

**Acceptance criteria:**
- [ ] `schema_to_table_meta(SchemaWithFieldMeta)` returns columns with check_min, check_max, default, readonly
- [ ] String field with `FieldMeta(max=255)` produces `String(255)` not `String()`
- [ ] `Optional[int]` field has `nullable: True`
- [ ] `indexes` and `unique_together` populated from SQLMeta
- [ ] Existing test `test_repositories.py` still passes (GenericRepository uses this mapper)

**Out of scope:** Do NOT generate actual SQL CHECK constraints yet (that is Task 3.1). Only produce metadata.

**Dependencies:** Task 2.1 (SQLMeta)

---

### Task 3.1 -- Implement DDLBuilder + create_tables()

**Level:** Senior (Opus)
**Executor:** teamlead
**Goal:** Auto-generate CREATE TABLE from SchemaBase metadata, supporting SQLite/PostgreSQL/MySQL dialects.

**Files:**
- `Services/sql/core/ddl_builder.py` -- CREATE new file
- `Services/sql/core/sql_manager.py` -- add `create_tables()` method

**Steps:**
1. Create `ddl_builder.py` with class `DDLBuilder`:
   - `__init__(self, schema_mapper: ISchemaMapper)` -- takes the mapper
   - `build_create_table(schema_class: Type, dialect: str = "sqlite") -> str`:
     - Call `schema_mapper.schema_to_table_meta(schema_class)` to get full metadata
     - Generate `CREATE TABLE IF NOT EXISTS "table_name" (...)`:
       - Column definitions with SQLAlchemy type names mapped to SQL dialect strings
       - PRIMARY KEY clause
       - NOT NULL for required fields
       - DEFAULT for fields with defaults (serialize Python value to SQL literal)
       - CHECK constraints from check_min/check_max: `CHECK ("col" >= min AND "col" <= max)`
       - VARCHAR(N) for string fields with max
     - Generate CREATE INDEX statements from `indexes`
     - Generate UNIQUE constraints from `unique_together`
   - `build_create_all(schema_classes: List[Type], dialect: str = "sqlite") -> List[str]`:
     - Returns list of SQL statements (CREATE TABLE + CREATE INDEX for each schema)
   - Dialect differences to handle:
     - SQLite: `INTEGER PRIMARY KEY AUTOINCREMENT` for `id: int`
     - PostgreSQL: `SERIAL PRIMARY KEY` for auto-increment
     - MySQL: `INT AUTO_INCREMENT PRIMARY KEY`
     - Boolean: SQLite -> INTEGER, PostgreSQL -> BOOLEAN, MySQL -> TINYINT(1)
2. In `sql_manager.py`, add `create_tables(self, schema_classes: List[Type], dialect: str = None) -> int`:
   - Uses `DDLBuilder` to generate SQL
   - Dialect auto-detected from `self._config_dict.get("dialect", "sqlite")` if not provided
   - Executes all statements via `self.execute()`
   - Returns count of tables created
   - Idempotent (IF NOT EXISTS)

**Acceptance criteria:**
- [ ] `sql_manager.create_tables([UserSchema])` creates table with correct columns, types, constraints
- [ ] CHECK constraints from FieldMeta min/max appear in generated SQL
- [ ] VARCHAR(N) for string fields with FieldMeta.max
- [ ] IF NOT EXISTS -- calling twice does not error
- [ ] `DDLBuilder.build_create_table()` returns valid SQL string for all 3 dialects
- [ ] Auto-increment ID works for each dialect

**Out of scope:** Foreign keys, migrations, ALTER TABLE. No schema evolution.
**Edge cases:** Schema with no `id` field (no auto-increment), schema with only optional fields, empty schema.

**Dependencies:** Task 2.2 (enhanced mapper)

---

### Task 4.1 -- Implement QuerySet builder

**Level:** Senior+ (Opus)
**Executor:** teamlead
**Goal:** Django-style QuerySet with chained API generating parameterized SQL.

**Files:**
- `Services/sql/core/queryset.py` -- CREATE new file
- `Services/sql/core/sql_manager.py` -- add `objects()` method

**Steps:**
1. Create `queryset.py` with class `QuerySet[T]`:
   - `__init__(self, adapter: ISyncEngineAdapter, schema_class: Type[T], schema_mapper: ISchemaMapper, table_name: str)`:
     - Stores adapter, schema_class, mapper, table_name
     - Internal state: `_filters: List`, `_excludes: List`, `_order: List[str]`, `_limit_val: Optional[int]`, `_offset_val: Optional[int]`
   - Each method returns a **new** QuerySet (immutable pattern -- do NOT mutate self):
     - `.filter(**kwargs) -> QuerySet[T]`: add WHERE conditions. Key format: `field__lookup`
     - `.exclude(**kwargs) -> QuerySet[T]`: add WHERE NOT conditions
     - `.order_by(*fields) -> QuerySet[T]`: prefix `-` for DESC. E.g. `order_by("-score", "name")`
     - `.limit(n: int) -> QuerySet[T]`: LIMIT clause
     - `.offset(n: int) -> QuerySet[T]`: OFFSET clause
   - Lookup resolution from `field__lookup` kwarg keys:
     - `field__eq` or just `field` -> `"col" = :param`
     - `field__ne` -> `"col" != :param`
     - `field__gt` -> `"col" > :param`
     - `field__gte` -> `"col" >= :param`
     - `field__lt` -> `"col" < :param`
     - `field__lte` -> `"col" <= :param`
     - `field__in` -> `"col" IN (:p0, :p1, ...)` (expand list)
     - `field__like` -> `"col" LIKE :param`
     - `field__isnull` -> `"col" IS NULL` (if True) or `"col" IS NOT NULL` (if False)
   - Terminal methods (execute the query):
     - `.all() -> List[T]`: execute SELECT, return list of schema instances via mapper.row_to_entity
     - `.first() -> Optional[T]`: LIMIT 1, return single instance or None
     - `.count() -> int`: execute SELECT COUNT(*)
     - `.values() -> List[Dict[str, Any]]`: execute SELECT, return raw dicts (Dict at Boundary)
     - `.delete() -> int`: execute DELETE with WHERE clauses, return rowcount
     - `.update(**kwargs) -> int`: execute UPDATE SET ... WHERE ..., return rowcount
   - Internal `_build_sql() -> Tuple[str, Dict[str, Any]]`: builds parameterized SQL + params dict
     - All column names quoted with double quotes
     - All values as named parameters (`:param_N`)
     - Parameter names are unique (auto-incrementing counter `_p0`, `_p1`, ...)
2. In `sql_manager.py`, add `objects(self, schema_class: Type[T], table_name: str = None) -> QuerySet[T]`:
   - Gets table_name from mapper if not provided
   - Returns `QuerySet(self._adapter, schema_class, self._schema_mapper, table_name)`
   - Requires initialized adapter

**Acceptance criteria:**
- [ ] `sql_manager.objects(User).filter(age__gte=18).order_by("-score").limit(10).all()` returns list of User instances
- [ ] `sql_manager.objects(User).filter(name="Alice").first()` returns single instance or None
- [ ] `sql_manager.objects(User).filter(age__gte=18).count()` returns int
- [ ] `sql_manager.objects(User).filter(age__gte=18).values()` returns List[Dict]
- [ ] `sql_manager.objects(User).filter(id=1).delete()` deletes and returns rowcount
- [ ] `sql_manager.objects(User).filter(id=1).update(name="Bob")` updates and returns rowcount
- [ ] `.exclude(status="banned")` generates `WHERE NOT ("status" = :p0)`
- [ ] All parameters are parameterized (no f-string injection)
- [ ] Chaining is immutable: `qs = objects(User); qs.filter(x=1); qs.all()` returns ALL users (filter not applied to qs)
- [ ] `field__in` with empty list produces `WHERE 1=0` (no results)

**Out of scope:** JOIN, subqueries, aggregate functions (SUM/AVG), GROUP BY. Async QuerySet.
**Edge cases:** Empty filter (select all), filter on non-existent field (no validation -- SQL error from DB), __in with single element, chaining multiple filters (AND logic).

**Dependencies:** Task 2.2 (enhanced mapper for table_name resolution)

---

### Task 5.1 -- Enhance GenericRepository

**Level:** Middle+ (Sonnet)
**Executor:** developer
**Goal:** Add readonly field protection, bulk operations, and find_by to GenericRepository.

**Files:**
- `Services/sql/core/base_repository.py` -- extend GenericRepository
- `Services/sql/interfaces.py` -- extend IRepository with new methods

**Steps:**
1. In `GenericRepository.__init__()`:
   - After calling `self._mapper.schema_to_table_meta()`, extract set of readonly field names: `self._readonly_fields = {name for name, col in meta.get("columns", {}).items() if col.get("readonly")}`
2. In `GenericRepository.update()`:
   - Before building SET clause, remove readonly fields from `row` dict: `row = {k: v for k, v in row.items() if k not in self._readonly_fields}`
   - If all non-id fields are readonly, raise `ValueError("All fields are readonly, cannot update")`
3. Add `insert_many(self, entities: List[T]) -> List[T]`:
   - Convert all entities to rows via mapper
   - Build single INSERT with multiple value sets (for efficiency)
   - Return list of validated entities
   - For SQLite: use `executemany` pattern (batch execute with same SQL, different params)
4. Add `update_many(self, updates: List[Tuple[ID, T]]) -> int`:
   - For each (id, entity) pair, call update() internally
   - Return total rowcount
   - Note: not a true batch UPDATE -- sequential for simplicity and correctness
5. Add `find_by(self, **kwargs) -> List[T]`:
   - Build `SELECT * FROM table WHERE col1 = :col1 AND col2 = :col2 ...`
   - All values parameterized
   - Return list of entities via mapper
6. In `interfaces.py`, extend `IRepository` Protocol:
   - Add `insert_many(entities: List[T]) -> List[T]`
   - Add `update_many(updates: List[Tuple[ID, T]]) -> int`
   - Add `find_by(**kwargs) -> List[T]`

**Acceptance criteria:**
- [ ] `repo.update(1, entity_with_readonly_field)` -- readonly fields are silently skipped in SET clause
- [ ] `repo.insert_many([user1, user2, user3])` inserts 3 rows
- [ ] `repo.find_by(name="Alice")` returns list of matching entities
- [ ] `repo.find_by(name="Alice", age=25)` uses AND logic
- [ ] Existing tests (find_by_id, insert, delete) still pass
- [ ] IRepository Protocol updated with new method signatures

**Out of scope:** Async versions of new methods. Upsert. Pagination in find_by.
**Edge cases:** find_by with no kwargs (returns all), insert_many with empty list (returns []), update with all fields readonly.

**Dependencies:** Task 2.2 (enhanced mapper provides readonly info in table_meta)

---

### Task 6.1 -- Wire new features into SQLManager public API

**Level:** Middle+ (Sonnet)
**Executor:** developer
**Goal:** Expose create_tables(), objects(), and updated get_repository() through SQLManager.

**Files:**
- `Services/sql/core/sql_manager.py` -- add methods
- `Services/sql/__init__.py` -- update exports
- `Services/sql/core/__init__.py` -- update exports
- `Services/sql/interfaces.py` -- extend ISQLManager

**Steps:**
1. In `sql_manager.py`:
   - Import `DDLBuilder` from `sql_module.core.ddl_builder`
   - Import `QuerySet` from `sql_module.core.queryset`
   - Add `create_tables(self, schema_classes: List[Type], dialect: str = None) -> int` (delegates to DDLBuilder, see Task 3.1 for logic)
   - Add `objects(self, schema_class: Type[T], table_name: str = None) -> QuerySet[T]` (see Task 4.1 for logic)
   - Update `get_repository()` -- no `table_name` param change needed, mapper now returns richer meta
2. In `interfaces.py`, extend ISQLManager:
   - Add `create_tables(self, schema_classes: List[Type]) -> int`
   - Add `objects(self, schema_class: Type) -> Any` (QuerySet, but Protocol uses Any to avoid circular)
3. In `__init__.py`, add exports: `DDLBuilder`, `QuerySet`
4. In `core/__init__.py`, add exports: `DDLBuilder`, `QuerySet`

**Acceptance criteria:**
- [ ] `sql_manager.create_tables([UserSchema])` works end-to-end
- [ ] `sql_manager.objects(UserSchema).all()` works end-to-end
- [ ] `from sql_module import DDLBuilder, QuerySet` works
- [ ] ISQLManager updated
- [ ] Existing tests still pass

**Out of scope:** New typed commands for create_tables or objects (command_module integration).

**Dependencies:** Task 3.1 (DDLBuilder), Task 4.1 (QuerySet), Task 5.1 (enhanced repo)

---

### Task 7.1 -- Tests for Phase 1 fixes

**Level:** Middle (Sonnet)
**Executor:** developer
**Goal:** Test coverage for legacy cleanup and security fixes.

**Files:**
- `Services/sql/tests/test_sql_manager.py` -- add tests
- `Services/sql/tests/test_adapters.py` -- add tests

**Steps:**
1. In `test_sql_manager.py` add:
   - `test_query_range_rejects_injection`: pass `table="users; DROP TABLE"`, expect ValueError
   - `test_query_range_valid_identifier`: pass normal table name, verify results
   - `test_query_range_with_offset_and_limit`: verify correct SQL behavior
2. In `test_adapters.py` add:
   - `test_async_adapter_dispose_no_running_loop`: create async adapter, setup, dispose -- no error
   - `test_async_adapter_dispose_not_initialized`: dispose without setup -- no error
3. Verify `from sql_module import SQLManager` does NOT export `IMetricsCollector`

**Acceptance criteria:**
- [ ] All new tests pass
- [ ] `test_query_range_rejects_injection` confirms ValueError on malicious input
- [ ] No regressions in existing tests

**Dependencies:** Tasks 1.1, 1.2, 1.3

---

### Task 7.2 -- Tests for SQLMeta + enhanced mapper

**Level:** Middle (Sonnet)
**Executor:** developer
**Goal:** Test SQLMeta extraction and enhanced SchemaBaseMapper.

**Files:**
- `Services/sql/tests/test_schema_mapper.py` -- CREATE new file

**Steps:**
1. Define test schemas:
   - `SimpleSchema(SchemaBase)` -- no SQLMeta, no FieldMeta
   - `FullSchema(SchemaBase)` -- with SQLMeta (table_name, indexes, unique_together) and FieldMeta (min, max, readonly)
   - `StringSchema(SchemaBase)` -- string field with FieldMeta(max=100)
2. Tests:
   - `test_extract_sql_meta_with_class`: verify table_name, indexes, unique_together from SQLMeta
   - `test_extract_sql_meta_without_class`: verify derived table_name, empty lists
   - `test_mapper_returns_check_constraints`: numeric field with min/max -> check_min/check_max in column dict
   - `test_mapper_varchar_from_field_meta_max`: string field with max -> String(100)
   - `test_mapper_readonly_field`: FieldMeta(readonly=True) -> "readonly": True in column dict
   - `test_mapper_default_value`: field with default -> "default" in column dict
   - `test_mapper_nullable_optional`: Optional[int] field -> nullable: True
   - `test_mapper_backward_compatible`: existing callers still get table_name, columns, primary_key

**Acceptance criteria:**
- [ ] All tests pass
- [ ] File exists: `sql_module/tests/test_schema_mapper.py`
- [ ] Coverage of all FieldMeta -> SQL metadata mappings

**Dependencies:** Tasks 2.1, 2.2

---

### Task 7.3 -- Tests for Auto DDL

**Level:** Middle (Sonnet)
**Executor:** developer
**Goal:** Test DDLBuilder SQL generation and create_tables() integration.

**Files:**
- `Services/sql/tests/test_ddl_builder.py` -- CREATE new file

**Steps:**
1. Tests:
   - `test_build_create_table_sqlite`: verify generated SQL contains correct column types, PRIMARY KEY, IF NOT EXISTS
   - `test_build_create_table_postgresql`: verify SERIAL for auto-increment
   - `test_build_create_table_mysql`: verify AUTO_INCREMENT
   - `test_check_constraints_in_ddl`: schema with FieldMeta(min=0, max=100) -> CHECK clause in SQL
   - `test_varchar_in_ddl`: string field with max -> VARCHAR(N) in SQL
   - `test_create_tables_idempotent`: call create_tables twice, no error
   - `test_create_tables_integration`: create table from schema, insert row, query back
   - `test_indexes_in_ddl`: SQLMeta with indexes -> CREATE INDEX statements
   - `test_unique_constraint_in_ddl`: SQLMeta with unique_together -> UNIQUE clause

**Acceptance criteria:**
- [ ] All tests pass
- [ ] Generated SQL is syntactically valid for SQLite (executed against in-memory DB)
- [ ] File exists: `sql_module/tests/test_ddl_builder.py`

**Dependencies:** Task 3.1

---

### Task 7.4 -- Tests for QuerySet builder

**Level:** Middle+ (Sonnet)
**Executor:** developer
**Goal:** Comprehensive tests for QuerySet chained API.

**Files:**
- `Services/sql/tests/test_queryset.py` -- CREATE new file

**Steps:**
1. Setup: create table `users` with id, name, age, score columns. Insert test data (Alice/25/90, Bob/30/85, Carol/20/95).
2. Tests:
   - `test_all_returns_all_rows`: `.all()` returns 3 User instances
   - `test_filter_eq`: `.filter(name="Alice").all()` returns [Alice]
   - `test_filter_gte`: `.filter(age__gte=25).all()` returns [Alice, Bob]
   - `test_filter_lt`: `.filter(age__lt=25).all()` returns [Carol]
   - `test_filter_in`: `.filter(name__in=["Alice", "Bob"]).all()` returns 2
   - `test_filter_like`: `.filter(name__like="A%").all()` returns [Alice]
   - `test_filter_isnull_true`: field IS NULL test
   - `test_filter_isnull_false`: field IS NOT NULL test
   - `test_exclude`: `.exclude(name="Alice").all()` returns [Bob, Carol]
   - `test_order_by_asc`: `.order_by("age").all()` -> Carol, Alice, Bob
   - `test_order_by_desc`: `.order_by("-score").all()` -> Carol, Alice, Bob
   - `test_limit`: `.limit(2).all()` returns 2
   - `test_offset`: `.offset(1).limit(1).all()` returns 1
   - `test_first`: `.first()` returns single instance
   - `test_first_empty`: empty result `.first()` returns None
   - `test_count`: `.count()` returns 3
   - `test_count_with_filter`: `.filter(age__gte=25).count()` returns 2
   - `test_values_returns_dicts`: `.values()` returns List[Dict]
   - `test_delete`: `.filter(name="Alice").delete()` returns 1, total count now 2
   - `test_update`: `.filter(name="Alice").update(age=26)` returns 1, verify age changed
   - `test_chaining_immutable`: `qs = objects(User); qs2 = qs.filter(x=1)` -- qs is not modified
   - `test_in_empty_list`: `.filter(name__in=[]).all()` returns []
   - `test_multiple_filters_and`: `.filter(age__gte=20).filter(age__lte=25).all()` -> AND logic

**Acceptance criteria:**
- [ ] All tests pass against in-memory SQLite
- [ ] File exists: `sql_module/tests/test_queryset.py`
- [ ] At least 20 test cases
- [ ] All lookups tested: eq, ne, gt, gte, lt, lte, in, like, isnull

**Dependencies:** Task 4.1, Task 3.1 (create_tables for setup)

---

### Task 7.5 -- Tests for enhanced Repository

**Level:** Middle (Sonnet)
**Executor:** developer
**Goal:** Test readonly field protection, bulk operations, and find_by.

**Files:**
- `Services/sql/tests/test_repositories.py` -- extend existing file

**Steps:**
1. Define a schema with FieldMeta(readonly=True) on one field
2. Tests:
   - `test_update_skips_readonly_fields`: update entity with readonly field, verify field not changed in DB
   - `test_insert_many`: insert 3 entities, verify all 3 in DB
   - `test_insert_many_empty`: insert empty list, verify returns []
   - `test_find_by_single_field`: find_by(name="Alice") returns matching
   - `test_find_by_multiple_fields`: find_by(name="Alice", age=25) returns matching
   - `test_find_by_no_results`: find_by(name="Nonexistent") returns []
   - `test_find_by_no_kwargs`: find_by() returns all rows
   - `test_update_many`: update 2 entities, verify both updated

**Acceptance criteria:**
- [ ] All new tests pass
- [ ] Existing tests in test_repositories.py still pass
- [ ] Readonly protection confirmed by DB verification

**Dependencies:** Task 5.1, Task 3.1 (create_tables for setup)

---

### Task 8.1 -- Create DECISIONS.md

**Level:** Junior (Haiku)
**Executor:** docs-writer
**Goal:** Document all architectural decisions for sql_module.

**Files:**
- `Services/sql/DECISIONS.md` -- CREATE

**Steps:**
1. Create DECISIONS.md with the following ADRs:
   - **ADR-200: Dual sync/async via adapters** -- ISyncEngineAdapter / IAsyncEngineAdapter, lazy async creation
   - **ADR-201: Fork-safety with NullPool** -- INSPECTOR_MULTIPROCESS env, config.fork_safe
   - **ADR-202: SchemaBaseMapper as plugin (ISchemaMapper)** -- replaceable mapper, Protocol-based
   - **ADR-203: Remove IMetricsCollector in favor of ObservableMixin** -- dead code, _record_timing replaces
   - **ADR-204: SQLMeta as ClassVar nested class** -- lives in sql_module, SchemaBase unchanged, Pydantic ignores
   - **ADR-205: Enhanced SchemaBaseMapper reads FieldMeta** -- min/max -> CHECK, max -> VARCHAR, readonly -> repo block
   - **ADR-206: Auto DDL via DDLBuilder** -- create_tables() idempotent, dialect-aware, IF NOT EXISTS
   - **ADR-207: QuerySet builder (Django-style)** -- immutable chaining, parameterized SQL, lookups
   - **ADR-208: Readonly field protection in Repository** -- FieldMeta.readonly -> silently excluded from UPDATE
   - **ADR-209: Identifier validation in query_range** -- regex whitelist, defense against SQL injection
   - **ADR-210: UnitOfWork delegates to adapter connection()** -- commit/rollback are no-ops by design
2. Follow format from `router_module/DECISIONS.md`: Status, Date, Context, Decision, Consequences

**Acceptance criteria:**
- [ ] File exists: `sql_module/DECISIONS.md`
- [ ] 11 ADRs documented
- [ ] Each ADR has Status, Date, Context, Decision, Consequences

**Dependencies:** All implementation tasks (1.x through 6.1)

---

### Task 8.2 -- Fill ARCHITECTURE.md section 6.16

**Level:** Junior (Haiku)
**Executor:** docs-writer
**Goal:** Replace TODO placeholder in ARCHITECTURE.md with sql_module description.

**Files:**
- `multiprocess_framework/ARCHITECTURE.md` -- replace line 791 (`### 6.16 sql_module -- TODO`)
- `multiprocess_framework/DECISIONS.md` -- add sql_module row to module decisions table

**Steps:**
1. Replace `### 6.16 \`sql_module\` — *TODO (после модуля #16)*` with full section:
   - Role: Universal SQL toolkit -- DDL, queries, repositories, export
   - Architecture diagram: SQLManager -> adapters (SQLite/PG/MySQL), DDLBuilder, QuerySet, GenericRepository, SchemaBaseMapper, UoW
   - Key decisions: ADR-200..210 summary
   - Link to README and DECISIONS.md
2. In main DECISIONS.md, add row: `| sql_module | [link] | Storage | ADR-200..210 |`

**Acceptance criteria:**
- [ ] ARCHITECTURE.md section 6.16 no longer says TODO
- [ ] Main DECISIONS.md has sql_module row

**Dependencies:** Task 8.1

---

### Task 8.3 -- Update README, STATUS.md, __init__.py

**Level:** Junior (Haiku)
**Executor:** docs-writer
**Goal:** Update all documentation files to reflect new features.

**Files:**
- `Services/sql/README.md` -- add sections for create_tables, objects, SQLMeta, find_by, insert_many
- `Services/sql/STATUS.md` -- update stage, add new checklist items
- `Services/sql/__init__.py` -- verify all new exports present

**Steps:**
1. README.md:
   - Add "Auto DDL" section with create_tables() example
   - Add "QuerySet builder" section with chained query example
   - Add "SQLMeta" section explaining declarative table config
   - Add "Enhanced Repository" section (find_by, insert_many, readonly protection)
   - Update "Structure" section with new files (sql_meta.py, ddl_builder.py, queryset.py)
   - Fix `config/` -> `configs/` (if not already done in Task 1.4)
2. STATUS.md:
   - Add new checklist items for DDL, QuerySet, enhanced repo, tests
   - Update evaluation scores
   - Add integration note for create_tables/objects
3. __init__.py: verify DDLBuilder, QuerySet, extract_sql_meta are exported

**Acceptance criteria:**
- [ ] README has examples for all new features
- [ ] STATUS.md reflects current state
- [ ] `from sql_module import DDLBuilder, QuerySet` works

**Dependencies:** All implementation and test tasks

---

## 4. Risks and Constraints

| Risk | Mitigation |
|------|-----------|
| QuerySet SQL generation bugs | Extensive parameterized test suite (Task 7.4, 20+ tests) |
| Dialect differences in DDL | Test with SQLite (primary), note PostgreSQL/MySQL as manual verification |
| Breaking existing consumers | All new features are additive; existing API unchanged |
| SQLMeta polluting Pydantic schema | ClassVar -- confirmed Pydantic v2 ignores it completely |
| FieldMeta.max ambiguity (numeric vs string) | Check base type: if str -> VARCHAR, if numeric -> CHECK constraint |
| Performance of QuerySet | Uses adapter.query() which is already optimized; no ORM overhead |

---

## 5. Definition of Done

### Phase 1 (Legacy Cleanup)
- [ ] `metrics/` directory deleted
- [ ] `IMetricsCollector` removed from all files
- [ ] `async_adapter.dispose()` uses `get_running_loop()` pattern
- [ ] `query_range()` validates identifiers
- [ ] README typo fixed
- [ ] Phase 1 tests pass (Task 7.1)

### Phase 2 (SQLMeta + Mapper)
- [ ] `sql_meta.py` created with `SQLMeta` pattern and `extract_sql_meta()`
- [ ] `SchemaBaseMapper` reads FieldMeta (min/max/readonly/default) and SQLMeta
- [ ] Phase 2 tests pass (Task 7.2)

### Phase 3 (Auto DDL)
- [ ] `DDLBuilder` generates valid CREATE TABLE for SQLite, PostgreSQL, MySQL
- [ ] `sql_manager.create_tables()` works end-to-end
- [ ] CHECK constraints, VARCHAR(N), indexes, unique_together in generated DDL
- [ ] Phase 3 tests pass (Task 7.3)

### Phase 4 (QuerySet)
- [ ] All lookups work: eq, ne, gt, gte, lt, lte, in, like, isnull
- [ ] Terminal methods: all, first, count, values, delete, update
- [ ] Chaining is immutable
- [ ] All parameters are parameterized (no SQL injection)
- [ ] Phase 4 tests pass (Task 7.4)

### Phase 5 (Enhanced Repository)
- [ ] Readonly fields blocked in update
- [ ] insert_many, update_many, find_by work
- [ ] Phase 5 tests pass (Task 7.5)

### Phase 6 (Integration)
- [ ] `sql_manager.create_tables()` and `sql_manager.objects()` accessible
- [ ] ISQLManager updated
- [ ] New classes exported from `sql_module`

### Phase 7-8 (Documentation)
- [ ] DECISIONS.md with 11 ADRs
- [ ] ARCHITECTURE.md section 6.16 filled
- [ ] Main DECISIONS.md has sql_module row
- [ ] README updated with all new features
- [ ] STATUS.md updated

### Final
- [ ] ` && python -m pytest Services/sql/tests -v` -- ALL GREEN
- [ ] `python -c "from sql_module import SQLManager, DDLBuilder, QuerySet"` -- no errors
- [ ] No existing consumer broken (database_process.py, export_detections.py)
