# serialization/ — Статус

**Статус:** STABLE.

## Компоненты

| Компонент | Файл | Тесты | Статус |
|-----------|------|-------|--------|
| `DataConverter` (dict/JSON/YAML) | converter.py | ✅ test_converter.py (25+ тестов) | Готов |
| `FormatType` enum | converter.py | ✅ | Готов |
| `registers_to_dict/from_dict` | io.py | ✅ test_io.py | Готов |
| `registers_to_json/from_json` | io.py | ✅ | Готов |
| `registers_to_yaml/from_yaml` | io.py | ✅ | Готов (опционально, требует PyYAML) |
| `registers_to_flat_dict/from_flat_dict` | io.py | ✅ | Готов |
| `FileStorage` (JSON-файлы) | file_storage.py | ✅ test_file_storage.py | Готов |
| Interfaces (`IDataConverter`, `ISchemaStorage`, `IAsyncSchemaStorage`) | interfaces.py | ✅ | Готов (ADR-DS-005) |

## Внешние зависимости

| Зависимость | Тип | Назначение |
|-------------|-----|------------|
| `core/` | внутренний | SchemaBase / model_dump |
| Pydantic v2 | runtime | model_dump / model_validate |
| PyYAML | optional | для `*_yaml` функций |

## Потребители

- 4 импорта `DataConverter`
- 0 прямых импортов `registers_to_dict` / `_to_json` / etc. (но это public API на будущее)
- `FileStorage` импортируется из `storage/` (внутренний re-export)

## Async

`IAsyncSchemaStorage` определён как Protocol для будущей интеграции с Redis/PostgreSQL/S3. **Реализация пока есть только синхронная** (`FileStorage`).

## Legacy aliases

`IRegisterStorage` / `IAsyncRegisterStorage` — обратная совместимость с до-v2.0 API. 0 живых потребителей; сохранены до явного решения об удалении (см. полировку 2026-05-11).

## Известные TODO

- [ ] Async-FileStorage (с `aiofiles`).
- [ ] Опциональный gzip для больших dump'ов.
- [ ] Schema migration helpers (при изменении SchemaBase-структуры).
