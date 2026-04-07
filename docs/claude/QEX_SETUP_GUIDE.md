# QEX MCP — Полный конспект настройки

> Дата составления: 2026-04-07  
> Стек: Rust (qex) · Qdrant (Docker) · Ollama · Claude Code MCP

---

## Оглавление

1. [Архитектура системы](#1-архитектура-системы)
2. [Файлы конфигурации — ГЛАВНОЕ](#2-файлы-конфигурации--главное)
3. [Qdrant — установка и запуск](#3-qdrant--установка-и-запуск)
4. [Ollama — установка и запуск](#4-ollama--установка-и-запуск)
5. [Сборка бинарника qex](#5-сборка-бинарника-qex)
6. [Развёртывание бинарника](#6-развёртывание-бинарника)
7. [Правильная конфигурация mcp.json](#7-правильная-конфигурация-mcpjson)
8. [Первый запуск — индексация](#8-первый-запуск--индексация)
9. [Диагностика — чеклист команд](#9-диагностика--чеклист-команд)
10. [Папка qex/ — что хранить, что удалять](#10-папка-qex--что-хранить-что-удалять)
11. [Типичные проблемы и решения](#11-типичные-проблемы-и-решения)

---

## 1. Архитектура системы

```
Claude Code (Claude Agent SDK)
    │
    └──► qex-mcp-v2.exe  (MCP сервер, Rust)
              │
              ├──► BM25 индекс  (Tantivy, локальный файл)
              │
              └──► Dense vectors
                        │
                        ├──► Ollama  :11434  (embeddings, qwen3-embedding:4b)
                        └──► Qdrant  :6333   (vector DB, Docker container)
```

**Поток при `index_codebase`:**
1. qex сканирует файлы воркспейса через tree-sitter
2. Каждый чанк кода → Ollama `/api/embed` → вектор 768-dim
3. Векторы батчами → Qdrant REST API (upsert)
4. BM25 индекс строится параллельно локально

**Поток при `search_code`:**
1. Запрос → Ollama → вектор запроса
2. Qdrant cosine search → top-K чанков
3. BM25 поиск → top-K чанков
4. Гибридный ранжировщик → финальные результаты

---

## 2. Файлы конфигурации — ГЛАВНОЕ

> ⚠️ КРИТИЧНО: Claude Code читает конфиги в следующем приоритете. Неправильный файл = изменения игнорируются.

### Стратегия: Windows vs macOS

Проект используется **на двух платформах**. Конфигурация разнесена так:

| Платформа | Где хранится конфиг | Модель эмбеддингов |
|-----------|--------------------|--------------------|
| Windows   | `C:\Users\INNOTECH\.claude.json` (глобальный mcpServers) | `qwen3-embedding:4b` |
| macOS     | `~/.claude.json` (секция `projects` → путь к проекту) | `qwen3-embedding:4b` |

Файл `.claude/mcp.json` в репозитории — **только справочник** (Windows-пример).  
На Windows он перекрывается глобальным `mcpServers` в `~/.claude.json`.  
На macOS он отключён через `disabledMcpjsonServers: ["qex"]` в проектной записи `~/.claude.json`.

### Приоритет конфигов MCP — Windows (по убыванию):

| # | Путь | Кто читает | Приоритет |
|---|------|-----------|-----------|
| 1 | `C:\Users\INNOTECH\.claude.json` | Claude Code CLI | **ГЛАВНЫЙ** |
| 2 | `C:\Users\INNOTECH\AppData\Roaming\Code\User\mcp.json` | VSCode Extension | **Для VSCode** |
| 3 | `.claude/mcp.json` (в проекте) | Claude Code CLI | Проектный |
| 4 | `~/.claude/mcp.json` | Claude Code CLI | Пользовательский |

> Файлы №1 и №2 — приоритетные. Именно они управляют запущенным процессом.  
> Если правишь №3 или №4, а №1/#2 тоже существуют — правки №3/#4 **не применяются**.

### Приоритет конфигов MCP — macOS (по убыванию):

| # | Путь | Приоритет |
|---|------|-----------|
| 1 | `~/.claude.json` → секция `projects["<путь к проекту>"]["mcpServers"]` | **ГЛАВНЫЙ** |
| 2 | `.claude/mcp.json` (в проекте) | Проектный (отключён через disabledMcpjsonServers) |

### Проверка активного конфига (Windows):

```powershell
# Что сейчас прописано в главном конфиге
python -c "import json; d=json.load(open(r'C:\Users\INNOTECH\.claude.json')); print(json.dumps(d.get('mcpServers',{}), indent=2))"

# Какой процесс реально запущен
Get-Process | Where-Object {$_.Name -like "*qex*"} | Select-Object Name, Path, Id
```

### Проверка активного конфига (macOS):

```bash
# Что прописано для проекта
python3 -c "
import json
d = json.load(open('/Users/twokrai/.claude.json'))
proj = d['projects'].get('/Users/twokrai/Project_code/inspector_bottles/Inspector_bottles', {})
print(json.dumps(proj.get('mcpServers', {}), indent=2))
print('disabled:', proj.get('disabledMcpjsonServers'))
"

# Запущен ли qex-процесс
pgrep -la qex
```

---

## 3. Qdrant — установка и запуск

### Первичная установка (один раз):

```powershell
# Скачать образ
docker pull qdrant/qdrant

# Создать контейнер с правильным маппингом портов (ОБЯЗАТЕЛЬНО -p флаги!)
docker run -d `
  --name qdrant `
  -p 6333:6333 `
  -p 6334:6334 `
  -v qdrant_storage:/qdrant/storage `
  qdrant/qdrant
```

> ⚠️ Без `-p 6333:6333` контейнер запустится, но порт не будет доступен с хоста!  
> Именно это была одна из ключевых проблем: `"6333/tcp":[]` → нет маппинга → connection refused.

### Ежедневный запуск:

```powershell
# Запустить существующий контейнер
docker start qdrant

# Проверить что запущен и порт доступен
docker ps --filter name=qdrant
curl http://localhost:6333/healthz
```

### Проверка данных:

```powershell
# Список коллекций
curl http://localhost:6333/collections

# Детали коллекции codebase_index
curl http://localhost:6333/collections/codebase_index

# Сколько векторов проиндексировано
curl http://localhost:6333/collections/codebase_index | python -c "import sys,json; d=json.load(sys.stdin); print('points:', d['result']['points_count'])"
```

### Если контейнер есть, но без маппинга портов (пересоздать):

```powershell
docker stop qdrant
docker rm qdrant
# Пересоздать командой выше с -p флагами
# ДАННЫЕ СОХРАНЯТСЯ в volume qdrant_storage
```

---

## 4. Ollama — установка и запуск

### Установка (один раз):
Скачать с https://ollama.com/download/windows и установить.

### Скачать нужную модель (один раз):

```powershell
ollama pull qwen3-embedding:4b
```

### Ежедневный запуск:

```powershell
# Запустить сервер (если не запущен как служба)
ollama serve

# Или проверить что уже работает
curl http://localhost:11434/
```

### Проверка модели:

```powershell
# Список загруженных моделей
ollama list

# Тест эмбеддинга (должен вернуть массив из 768 чисел)
curl http://localhost:11434/api/embed -d "{\"model\":\"qwen3-embedding:4b\",\"input\":\"hello world\"}" | python -c "import sys,json; d=json.load(sys.stdin); emb=d['embeddings'][0]; print(f'dims={len(emb)}, first3={emb[:3]}')"
```

---

## 5. Сборка бинарника qex

> Нужно только при изменении Rust-кода. Если бинарник уже есть — пропустить.

### Требования:
- Rust toolchain: `rustup update stable`
- MSVC Build Tools 14.x (Visual Studio Build Tools)

### Команда сборки (из папки `qex/`):

```powershell
cd C:\Users\INNOTECH\Desktop\PROJECT_INNOTECH\Inspector_bottles\qex

# ВАЖНО: features = dense + ollama обязательны!
cargo build --release --features "dense ollama"

# Бинарник появится здесь:
# qex/target/release/qex.exe  (43 MB)
```

> ⚠️ `[[bin]] name = "qex"` в Cargo.toml → бинарник называется `qex.exe`, не `qex-mcp.exe`!

### Проверка что features включены правильно:

```powershell
# Проверить Cargo.toml qex-mcp
cat qex/crates/qex-mcp/Cargo.toml | grep -A5 'features'
# Должно быть: features = ["dense", "ollama"]
```

---

## 6. Развёртывание бинарника

Скомпилированный `qex.exe` нужно скопировать в место, на которое указывает конфиг.

```powershell
# Текущий развёрнутый бинарник:
# venv/Scripts/qex-mcp-v2.exe

# Если собрали новую версию — НЕ перезаписывай работающий файл!
# Скопируй под новым именем:
cp qex/target/release/qex.exe venv/Scripts/qex-mcp-v3.exe

# Потом обнови путь в ~/.claude.json и AppData mcp.json
```

> ⚠️ **Нельзя перезаписать запущенный `.exe` на Windows** — ошибка "Device or resource busy".  
> Решение: копировать под новым именем (v2, v3 и т.д.), обновить конфиг, перезапустить Claude Code.

---

## 7. Правильная конфигурация mcp.json

### `C:\Users\INNOTECH\.claude.json` — секция mcpServers:

```json
{
  "mcpServers": {
    "qex": {
      "command": "C:\\Users\\INNOTECH\\Desktop\\PROJECT_INNOTECH\\Inspector_bottles\\venv\\Scripts\\qex-mcp-v2.exe",
      "args": [],
      "env": {
        "RUST_LOG": "info",
        "WORKSPACE_PATH": "C:\\Users\\INNOTECH\\Desktop\\PROJECT_INNOTECH\\Inspector_bottles",
        "QDRANT_URL": "http://localhost:6333",
        "QDRANT_COLLECTION_NAME": "codebase_index",
        "OLLAMA_BASE_URL": "http://localhost:11434",
        "EMBEDDING_MODEL": "qwen3-embedding:4b",
        "QEX_EMBEDDING_PROVIDER": "ollama"
      }
    }
  }
}
```

> `RUST_LOG=info` — включает логи бинарника (видны в Claude Code Output panel).  
> `QEX_EMBEDDING_PROVIDER=ollama` — явно указывает провайдер (auto-detect тоже работает, но явное надёжнее).

### `C:\Users\INNOTECH\AppData\Roaming\Code\User\mcp.json`:

Тот же блок `mcpServers`. Оба файла должны быть идентичны.

### Проверить что конфиг применился:

```powershell
# Перезапустить Claude Code полностью (закрыть и открыть заново)
# Затем проверить какой процесс запущен:
Get-Process | Where-Object {$_.Name -like "*qex*"} | Select-Object Name, Path
# Путь должен указывать на qex-mcp-v2.exe
```

---

## 8. Первый запуск — индексация

### Предварительная проверка (все три должны быть OK):

```powershell
# 1. Qdrant
curl http://localhost:6333/healthz
# Ожидаемо: {"time":0.0...,"status":"ok"}

# 2. Ollama
curl http://localhost:11434/
# Ожидаемо: "Ollama is running"

# 3. qex процесс
Get-Process | Where-Object {$_.Name -like "*qex*"}
# Должен быть запущен (запускается Claude Code автоматически)
```

### Запуск индексации через Claude Code:

```
# В чате с Claude Code:
index_codebase(force=True)

# или через MCP инструмент qex
```

> Время индексации: ~5-10 минут для 14k+ чанков с qwen3-embedding:4b.  
> Пока идёт — не закрывать Claude Code, не останавливать Ollama/Qdrant.

### Проверка результата:

```powershell
curl http://localhost:6333/collections/codebase_index | python -c "
import sys, json
d = json.load(sys.stdin)
r = d['result']
print('points:', r['points_count'])
print('status:', r['status'])
print('dims:', r['config']['params']['vectors']['size'])
"
# Ожидаемо: points: 14686, status: green, dims: 768
```

---

## 9. Диагностика — чеклист команд

### Полный чеклист при проблемах:

```powershell
# === 1. QDRANT ===
docker ps --filter name=qdrant --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
# Порты ДОЛЖНЫ быть: 0.0.0.0:6333->6333/tcp
# Если пусто — нет маппинга! Пересоздать контейнер.

curl http://localhost:6333/healthz
curl http://localhost:6333/collections

# === 2. OLLAMA ===
curl http://localhost:11434/
ollama list | grep nomic
# qwen3-embedding:4b должна быть в списке

# === 3. QEX БИНАРНИК ===
Get-Process | Where-Object {$_.Name -like "*qex*"} | Select-Object Name, Path, Id
# Путь должен вести к qex-mcp-v2.exe

# === 4. КОНФИГ ===
python -c "
import json
d = json.load(open(r'C:\Users\INNOTECH\.claude.json'))
mcp = d.get('mcpServers', {}).get('qex', {})
print('command:', mcp.get('command'))
print('env:', json.dumps(mcp.get('env',{}), indent=2))
"

# === 5. ТЕСТ ЭМБЕДДИНГА ===
curl http://localhost:11434/api/embed -d "{\"model\":\"qwen3-embedding:4b\",\"input\":\"test\"}" | python -c "import sys,json; d=json.load(sys.stdin); print('OK, dims=', len(d['embeddings'][0]))"
```

### Скрипт "один клик" для запуска всех служб:

```powershell
# health_check.ps1 — сохрани в удобном месте

Write-Host "=== QEX Health Check ===" -ForegroundColor Cyan

# Qdrant
$qdrant = docker ps --filter name=qdrant --format "{{.Status}}" 2>$null
if ($qdrant) {
    Write-Host "[OK] Qdrant: $qdrant" -ForegroundColor Green
} else {
    Write-Host "[!!] Qdrant не запущен. Запуск..." -ForegroundColor Yellow
    docker start qdrant
}

# Ollama
try {
    $ollamaResp = Invoke-WebRequest -Uri "http://localhost:11434/" -TimeoutSec 3 -ErrorAction Stop
    Write-Host "[OK] Ollama запущен" -ForegroundColor Green
} catch {
    Write-Host "[!!] Ollama не запущен. Запусти: ollama serve" -ForegroundColor Red
}

# Qdrant API
try {
    $qdrantResp = Invoke-RestMethod -Uri "http://localhost:6333/healthz" -TimeoutSec 3
    Write-Host "[OK] Qdrant API: $($qdrantResp.status)" -ForegroundColor Green
} catch {
    Write-Host "[!!] Qdrant API недоступен (проверь маппинг портов)" -ForegroundColor Red
}

# Коллекция
try {
    $coll = Invoke-RestMethod -Uri "http://localhost:6333/collections/codebase_index" -TimeoutSec 3
    $pts = $coll.result.points_count
    Write-Host "[OK] Коллекция codebase_index: $pts точек" -ForegroundColor Green
} catch {
    Write-Host "[--] Коллекция ещё не создана (нужна индексация)" -ForegroundColor Yellow
}

Write-Host "========================" -ForegroundColor Cyan
```

---

## 10. Папка qex/ — что хранить, что удалять

### Структура папки:

```
qex/
├── .cargo/          ← настройки cargo (registry mirror и т.п.)  ХРАНИТЬ
├── .claude/         ← заметки/контекст для Claude               ХРАНИТЬ
├── .gitignore       ← исключения git                            ХРАНИТЬ
├── Cargo.lock       ← точные версии зависимостей                ХРАНИТЬ (важен для воспроизводимой сборки)
├── Cargo.toml       ← манифест workspace                        ХРАНИТЬ
├── crates/          ← ИСХОДНЫЙ КОД                              ХРАНИТЬ
│   ├── qex-core/    ← ядро: BM25, dense, embedders              ХРАНИТЬ
│   └── qex-mcp/     ← MCP сервер, точка входа                   ХРАНИТЬ
├── docs/            ← документация                              ХРАНИТЬ
├── scripts/         ← вспомогательные скрипты                   ХРАНИТЬ
├── tests/           ← интеграционные тесты                      ХРАНИТЬ
├── LICENSE          ← лицензия                                  ХРАНИТЬ
├── PROGRESS.md      ← история разработки                        ХРАНИТЬ
├── README.md        ← документация                              ХРАНИТЬ
├── README.zh-CN.md  ← документация (китайский)                  ХРАНИТЬ
└── target/          ← АРТЕФАКТЫ СБОРКИ (2 GB!)                  МОЖНО УДАЛИТЬ
    └── release/
        └── qex.exe  ← скомпилированный бинарник (43 MB)
```

### Решение по `target/`:

| Ситуация | Действие |
|----------|----------|
| Бинарник уже скопирован в `venv/Scripts/` | `target/` **можно удалить** — освободит ~2 GB |
| Планируешь дорабатывать Rust-код | **Оставь** — инкрементальная сборка быстрее |
| Нужно место, но код может меняться | Удали только `target/debug/`, оставь `target/release/` |

```powershell
# Безопасное удаление только debug артефактов:
Remove-Item -Recurse -Force qex/target/debug

# Полное удаление (только если бинарник уже в venv/Scripts/):
Remove-Item -Recurse -Force qex/target
```

> После удаления `target/` следующая `cargo build` займёт 5-15 минут (полная перекомпиляция).  
> Частичная `target/release/` тоже можно удалить если `qex-mcp-v2.exe` уже в `venv/Scripts/`.

### Итог: что НЕЛЬЗЯ удалять никогда:

- `crates/` — это исходный код
- `Cargo.toml` и `Cargo.lock` — манифест и lock файл
- `venv/Scripts/qex-mcp-v2.exe` — активный бинарник MCP сервера

---

## 11. Типичные проблемы и решения

### Проблема: Dense индексация молча не работает

**Симптом:** `index_codebase` завершается быстро (<30 сек), в Qdrant 0 точек.

**Причина:** Embedder не загрузился, но ошибка была проглочена (`if let Ok(...)`).

**Проверка:**
```powershell
# Включи RUST_LOG=info в mcp.json и смотри Output > qex в VSCode
# Должна быть строка: "Dense search enabled — embedding N chunks"
# Если: "Dense indexing skipped — embedder failed: ..." → проблема в embedder
```

**Лечение:** Убедись что в env есть `OLLAMA_BASE_URL` и `EMBEDDING_MODEL` (auto-detect) **или** явно `QEX_EMBEDDING_PROVIDER=ollama`.

---

### Проблема: Qdrant доступен, но коллекция не создаётся

**Симптом:** `curl localhost:6333/healthz` работает, но upsert падает.

**Причина:** Контейнер без маппинга портов (`"6333/tcp":[]`).

```powershell
# Диагностика:
docker inspect qdrant --format '{{json .HostConfig.PortBindings}}'
# Должно быть: {"6333/tcp":[{"HostIp":"","HostPort":"6333"}]}
# Если пусто — пересоздать контейнер с -p 6333:6333
```

---

### Проблема: Обновил mcp.json, но qex всё ещё старый

**Причина:** Правишь не тот файл (`.claude/mcp.json` вместо `~/.claude.json`).

```powershell
# Узнать какой процесс запущен:
Get-Process | Where-Object {$_.Name -like "*qex*"} | Select-Object Path
# Если путь не тот — нашёл неправильный конфиг
```

---

### Проблема: Нельзя заменить qex-mcp.exe (файл занят)

**Симптом:** `cp: cannot create regular file: Device or resource busy`

**Решение:**
```powershell
# Копировать под НОВЫМ именем:
cp qex/target/release/qex.exe venv/Scripts/qex-mcp-v3.exe

# Обновить путь в ~/.claude.json
# Перезапустить Claude Code
```

---

### Быстрый запуск всего с нуля:

```powershell
# 1. Qdrant
docker start qdrant

# 2. Ollama (если не запущено как служба)
Start-Process ollama -ArgumentList "serve" -WindowStyle Hidden

# 3. Проверка
Start-Sleep 3
curl http://localhost:6333/healthz
curl http://localhost:11434/

# 4. Запустить Claude Code — qex стартует автоматически
# 5. В чате: index_codebase(force=True)  — только при первом запуске или после изменений кода
```

---

## 12. macOS — установка и настройка

> Всё то же самое что на Windows, но: нет `.exe`, другая модель эмбеддингов, конфиг в `~/.claude.json`.

### Бинарник qex:

```bash
# Путь к активному бинарнику (собран с --features "dense ollama"):
/Users/twokrai/.local/bin/qex-mcp-v2

# Проверка версии:
/Users/twokrai/.local/bin/qex-mcp-v2 --version
```

> Название совпадает с Windows: `qex-mcp-v2.exe` (Windows) / `qex-mcp-v2` (macOS).

Если нужно пересобрать:

```bash
cd qex
cargo build --release --features "dense ollama"
# Под новым именем (старый процесс может быть занят):
cp target/release/qex ~/.local/bin/qex-mcp-v3
# Обновить command в ~/.claude.json, перезапустить Claude Code
```

### Ollama — модель эмбеддингов:

На macOS используется `qwen3-embedding:4b` (уже загружена).

```bash
# Проверить наличие модели:
ollama list | grep qwen3-embedding

# Тест эмбеддинга (должен вернуть массив ~4096 чисел):
curl http://localhost:11434/api/embed \
  -d '{"model":"qwen3-embedding:4b","input":"hello world"}' | \
  python3 -c "import sys,json; d=json.load(sys.stdin); emb=d['embeddings'][0]; print(f'dims={len(emb)}, first3={emb[:3]}')"
```

### Конфигурация в `~/.claude.json`:

Проект уже добавлен в секцию `projects`. Активный конфиг:

```json
"/Users/twokrai/Project_code/inspector_bottles/Inspector_bottles": {
  "mcpServers": {
    "qex": {
      "type": "stdio",
      "command": "/Users/twokrai/.local/bin/qex-mcp-v2",
      "args": [],
      "env": {
        "RUST_LOG": "info",
        "WORKSPACE_PATH": "/Users/twokrai/Project_code/inspector_bottles/Inspector_bottles",
        "QDRANT_URL": "http://localhost:6333",
        "QDRANT_COLLECTION_NAME": "codebase_index",
        "OLLAMA_BASE_URL": "http://localhost:11434",
        "EMBEDDING_MODEL": "qwen3-embedding:4b",
        "QEX_EMBEDDING_PROVIDER": "ollama"
      }
    }
  },
  "disabledMcpjsonServers": ["qex"]
}
```

> `disabledMcpjsonServers: ["qex"]` — отключает Windows-конфиг из `.claude/mcp.json` в проекте.

### Qdrant (macOS):

```bash
# Первый раз (создать контейнер):
docker run -d \
  --name qdrant \
  -p 6333:6333 \
  -p 6334:6334 \
  -v qdrant_storage:/qdrant/storage \
  qdrant/qdrant

# Ежедневный запуск:
docker start qdrant
curl http://localhost:6333/healthz
```

### Ежедневный холодный старт (macOS):

```bash
# 1. Qdrant
docker start qdrant

# 2. Ollama (если не запущена)
ollama serve &

# 3. Проверка
sleep 2
curl http://localhost:6333/healthz && echo "Qdrant OK"
curl http://localhost:11434/ && echo "Ollama OK"

# 4. Запустить Claude Code — qex стартует автоматически
# 5. При первом запуске: index_codebase(force=True)
```

> ⚠️ Коллекция `codebase_index` создаётся с размерностью qwen3-embedding:4b (одинаково на обеих платформах).  
> Это отдельный локальный Qdrant — конфликтов с Windows-базой нет.

---

## 13. Важные отличия Windows vs macOS

| Параметр | Windows | macOS |
|----------|---------|-------|
| Бинарник | `venv/Scripts/qex-mcp-v2.exe` | `~/.local/bin/qex-mcp-v2` |
| Модель | `qwen3-embedding:4b` | `qwen3-embedding:4b` |
| Конфиг | `~/.claude.json` → `mcpServers` (глобальный) | `~/.claude.json` → `projects[path]["mcpServers"]` |
| `.claude/mcp.json` | Перекрыт глобальным конфигом | Отключён через `disabledMcpjsonServers` |
| Коллекция Qdrant | `codebase_index` (свой локальный) | `codebase_index` (свой локальный) |

---

*Составлено по итогам отладочной сессии 2026-04-07.  
macOS-секция добавлена 2026-04-06.  
Проблемы: неправильные конфиги, Qdrant без маппинга портов, silent failure в embedder, неверный дефолт провайдера.*
