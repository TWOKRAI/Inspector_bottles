# Phase 2: Processing

**Статус:** ✅ DONE

## Цель

Добавить процессинг-плагин с chain-обработкой. Доказать Wire-совместимость портов и data flow через pipeline.

## Задачи

### Task 2.1 — Grayscale Plugin
**Level:** Junior (Sonnet)
**Goal:** Простейший обработчик: BGR → GRAY
**Files:**
- `plugins/grayscale/plugin.py`
- `plugins/grayscale/config.py`
**Acceptance criteria:**
- [x] Input port: image/bgr, Output port: image/gray
- [x] Читает frame из SHM, конвертирует, пишет результат

### Task 2.2 — Color Mask Plugin (из v1)
**Level:** Middle (Sonnet)
**Goal:** Скопировать и адаптировать ColorMaskPlugin
**Files:**
- `plugins/color_mask/plugin.py`
- `plugins/color_mask/config.py`
**Acceptance criteria:**
- [x] HSV-фильтрация с configurable порогами
- [x] Пороги изменяются через команды (runtime)

### Task 2.3 — Topology: Camera → Processor
**Level:** Junior (Sonnet)
**Files:**
- `topology/phase2_processing.json`
**Acceptance criteria:**
- [x] Wire: camera → grayscale работает
- [x] Port compatibility check: BGR→BGR = OK, BGR→GRAY input = OK
- [x] Результат записывается в отдельный SHM region

## Оценка прототипа v1

**Что было:** ProcessorProcess (~400 строк):
- ChainThreadPool для параллельного выполнения шагов
- WorkerPoolDispatcher для распределения по процессам
- Каталог операций (YAML)
- Сложная система callback'ов

**Что улучшаем:**
- Каждая операция = отдельный plugin (composition вместо monolith)
- Chain = последовательность plugins в одном процессе (wires)
- Параллелизация — через framework WorkerManager, не кастомный pool
