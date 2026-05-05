# Phase 3: Output

**Статус:** ✅ DONE

## Цель

Сохранение результатов обработки — база данных и/или файловая система.

## Задачи

### Task 3.1 — Database Plugin (из v1)
**Level:** Middle (Sonnet)
**Goal:** Адаптировать DatabasePlugin для записи результатов детекции
**Files:**
- `plugins/database/plugin.py`
- `plugins/database/config.py`
**Acceptance criteria:**
- [x] SQLite по умолчанию
- [x] Batch-буферизация (flush по таймеру или по count)
- [x] Схема через SchemaBase (config через PluginConfig/SchemaBase)

### Task 3.2 — Frame Saver Plugin (новый)
**Level:** Junior (Sonnet)
**Goal:** Периодическое сохранение кадров на диск
**Files:**
- `plugins/frame_saver/plugin.py`
- `plugins/frame_saver/config.py`
**Acceptance criteria:**
- [x] Сохраняет каждый N-й кадр в output_dir
- [x] Configurable формат (PNG/JPEG) и интервал

### Task 3.3 — Topology: Full Pipeline
**Files:**
- `topology/phase3_pipeline.yaml`
**Acceptance criteria:**
- [x] camera → processor → database + frame_saver
- [x] Fan-out wire: один выход → два получателя

## Оценка прототипа v1

**Что было:** DatabaseProcess — отдельный процесс с:
- SQLManager lifecycle
- Batch buffer с flush по таймеру
- Schema auto-DDL

**Что улучшили (v2):**
- Database как plugin (не отдельный процесс — экономия ресурсов)
- Прямой sqlite3 вместо тяжёлого SQLManager (достаточно для прототипа)
- Batch buffer с двойным триггером: по count + по таймеру
- Оба output-плагина в одном процессе (fan-out через wires)
- Нет зависимости от DatabaseService/Adapter из v1 — чистый self-contained plugin

## Архитектурные решения Phase 3

| Решение | Обоснование |
|---------|-------------|
| sqlite3 напрямую (не SQLManager) | Минимум зависимостей, прототип не требует ORM |
| Оба output в одном процессе | Экономия ресурсов, общий memory_manager |
| flush по таймеру + по count | Не теряем данные при малом потоке, не копим при большом |
| frame_saver через SHM read | Консистентно с остальными плагинами |
