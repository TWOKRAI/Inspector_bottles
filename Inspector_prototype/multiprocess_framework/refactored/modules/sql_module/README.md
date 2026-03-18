# sql_module — универсальный SQL-менеджер

## Назначение

Универсальный модуль доступа к БД для multiprocess framework. Поддерживает PostgreSQL, MySQL, SQLite на базе SQLAlchemy 2.0. Dual sync/async через адаптеры, Unit of Work, fork-safety, typed commands. Интеграция с BaseManager, data_schema_module, router_module, command_module.

## Импорты

```python
from sql_module import SQLManager, SQLManagerConfig, GenericRepository
from sql_module.commands import DBQueryCommand, DBExecuteCommand
from sql_module.interfaces import ISQLManager, IRepository
```

## Точки входа

| Класс/функция | Метод | Описание |
|---------------|-------|----------|
| SQLManager | `initialize()` | Создать engine, проверить подключение |
| SQLManager | `shutdown()` | Освободить пул соединений |
| SQLManager | `execute(sql, params)` | Выполнить DML |
| SQLManager | `query(sql, params)` | Выполнить SELECT |
| SQLManager | `uow()` | Unit of Work для транзакций (sync) |
| SQLManager | `uow_async()` | Unit of Work для транзакций (async, ленивый адаптер) |
| SQLManager | `get_repository(schema_class)` | Репозиторий по схеме |
| SQLManager | `execute_command(cmd)` | Обработка команд от CommandManager |

## Зависимости

- **Зависит от:** `base_manager`, `data_schema_module`, `sqlalchemy>=2.0`
- **Используется в:** `command_module`, `router_module`, DatabaseProcess

## Интеграция с модулями фреймворка

SQLManager наследует ObservableMixin и через `managers` передаёт:
- **logger_module** — `_log_info`, `_log_error` (логи, инициализация)
- **error_module** — `_track_error` при исключениях (execute, query, execute_command)
- **statistics_module** — `_record_timing` для длительности запросов (`db.query.duration`, `db.execute.duration`)

```python
# DatabaseProcess передаёт менеджеры
SQLManager(
    config=sql_config,
    managers={
        "logger": self.logger_manager,
        "errors": self.error_manager,  # опционально
        "stats": self.stats_manager,
    },
    process=self,
)
```

## Схемы для get_repository

Поддерживаются:
- **data_schema_module.SchemaBase** — схемы фреймворка с FieldMeta
- **pydantic.BaseModel** — любые Pydantic-модели

```python
# Вариант 1: data_schema_module
from data_schema_module import SchemaBase, FieldMeta

class UserSchema(SchemaBase):
    id: int | None = None
    name: str

# Вариант 2: Pydantic
from pydantic import BaseModel

class EventSchema(BaseModel):
    id: int | None = None
    type: str
    ts: float

repo = mgr.get_repository(UserSchema, table_name="users")
```

## Пример

```python
from sql_module import SQLManager, SQLManagerConfig
from pydantic import BaseModel

class UserSchema(BaseModel):
    id: int | None = None
    name: str

cfg = SQLManagerConfig(url="sqlite:///:memory:", dialect="sqlite")
mgr = SQLManager(config=cfg)
mgr.initialize()

mgr.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT)")
mgr.execute("INSERT INTO users (name) VALUES (:n)", {"n": "Alice"})
rows = mgr.query("SELECT * FROM users")

repo = mgr.get_repository(UserSchema, table_name="users")
user = repo.insert(UserSchema(name="Bob"))

with mgr.uow().connection() as conn:
    from sqlalchemy import text
    conn.execute(text("INSERT INTO users (name) VALUES ('Carol')"))

mgr.shutdown()
```

## Async Unit of Work

Адаптер создаётся **лениво** при первом вызове `uow_async()` — не нагружает инициализацию.

```python
uow = mgr.uow_async()
async with uow.connection() as conn:
    from sqlalchemy import text
    await conn.execute(text("INSERT INTO users (name) VALUES ('Dave')"))
```

## Команды для CommandManager

```python
# Регистрация
command_manager.register_command("db.query", lambda msg: sql_manager.execute_command(msg))
command_manager.register_command("db.execute", lambda msg: sql_manager.execute_command(msg))

# Формат сообщений
{"command": "db.query", "sql": "SELECT * FROM t", "params": {}}
{"command": "db.execute", "sql": "INSERT INTO t VALUES (:v)", "params": {"v": 1}}
{"command": "db.insert", "table": "users", "data": {"name": "Alice"}}
```

## Fork-safety

При `INSPECTOR_MULTIPROCESS=1` или `config.fork_safe=True` используется NullPool. Рекомендуется создавать SQLManager и вызывать `initialize()` **внутри дочернего процесса** после fork.

## Структура модуля

```
sql_module/
├── __init__.py
├── interfaces.py
├── core/
│   ├── sql_manager.py
│   ├── engine_factory.py
│   ├── base_repository.py
│   └── unit_of_work.py
├── adapters/
│   ├── sync_adapter.py
│   ├── async_adapter.py
│   ├── schema_mapper.py
│   ├── sqlite.py
│   ├── postgresql.py
│   └── mysql.py
├── commands/
│   └── db_commands.py
├── config/
│   └── sql_manager_config.py
└── tests/
```

## Примечания

- Async для PostgreSQL требует `asyncpg`, для MySQL — `aiomysql`, для SQLite — `aiosqlite`
- Sync для PostgreSQL — `psycopg2` или `pg8000`, для MySQL — `PyMySQL` или `mysqlclient`
