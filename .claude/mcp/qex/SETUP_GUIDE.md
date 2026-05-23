# QEX — Полное руководство по настройке

> Дата: 2026-04-29  
> Версия qex: 0.0.2 (feature `vector`)  
> Стек: Rust (qex) · Ollama · Claude Code MCP · без Docker/Qdrant

---

## Оглавление

1. [Архитектура системы](#1-архитектура-системы)
2. [Сравнение: старая схема vs новая](#2-сравнение-старая-схема-vs-новая)
3. [Зависимости](#3-зависимости)
4. [Установка на Windows](#4-установка-на-windows)
5. [Установка на macOS](#5-установка-на-macos)
6. [MCP конфигурация](#6-mcp-конфигурация)
7. [Файл .ignore — что индексировать](#7-файл-ignore--что-индексировать)
8. [Первая индексация](#8-первая-индексация)
9. [Инкрементальное обновление индекса](#9-инкрементальное-обновление-индекса)
10. [Поиск](#10-поиск)
11. [Диагностика](#11-диагностика)
12. [Справочник переменных окружения](#12-справочник-переменных-окружения)
13. [FAQ](#13-faq)

---

## 1. Архитектура системы

```
Claude Code → qex (MCP stdio) → BM25 (Tantivy, локально)
                              → Dense vectors:
                                  HTTP → Ollama (GPU) → embedding (openai feature)
                                  Хранение → usearch HNSW (~/.qex/.../dense/dense.usearch)
                              → Hybrid = BM25 + Dense через RRF
```

**Поток при `index_codebase`:**

1. qex сканирует файлы воркспейса через tree-sitter
2. BM25 индекс строится через Tantivy (секунды)
3. Каждый чанк кода → Ollama `/v1/embeddings` (OpenAI-compatible endpoint) → вектор 4096-dim (macOS) / 2560-dim (Windows)
4. Векторы → usearch HNSW → `~/.qex/projects/.../dense/dense.usearch` (~30-40 мин для ~16k chunks)

**Поток при `search_code`:**

1. Запрос → Ollama → вектор запроса
2. BM25 поиск по Tantivy → top-K чанков
3. HNSW поиск по `dense.usearch` → top-K чанков (O(log n))
4. RRF (Reciprocal Rank Fusion) → гибридные результаты

**Хранение данных:**

```
~/.qex/projects/{project_name}_{hash}/
├── tantivy/               BM25 индекс (Tantivy)
├── dense/
│   ├── dense.usearch      usearch HNSW индекс (двоичный)
│   ├── dense_mapping.json маппинг key→chunk_id (+ file_path)
│   └── dense_meta.json    метаданные эмбеддера (provider, dimensions, model_name)
├── snapshot.json          Merkle-снимок файлов
├── snapshot_metadata.json
├── project_info.json
└── stats.json
```

---

## 2. Сравнение: старая схема vs новая

| | Старая (Qdrant) | Новая (vector, текущая) |
|---|---|---|
| Зависимости | Docker + Qdrant + Ollama | Только Ollama |
| Команда запуска | `docker start qdrant && ollama serve` | `ollama serve` |
| Хранение векторов | Docker volume (Qdrant) | `~/.qex/` JSON-файлы |
| Алгоритм поиска | HNSW O(log n) | Brute-force O(n) |
| Скорость поиска | ~2 ms | ~10 ms (для 16k chunks) |
| Качество результатов | Одинаковое | Одинаковое |
| Портабельность | Требует Docker | Работает везде |
| Масштаб | 100k+ chunks | До ~50k chunks |

**Когда вернуться к Qdrant:** если кодовая база вырастет до 100k+ chunks, brute-force
замедлится до ~60ms+. Тогда пересобрать с feature `dense` (usearch HNSW) или подключить
внешний Qdrant.

---

## 3. Зависимости

| Компонент | Обязательность | Описание |
|-----------|---------------|----------|
| **Ollama** | Обязательно | Embedding-модель на GPU. Единственная внешняя зависимость |
| **Docker / Qdrant** | Не нужен | Вектора хранятся в JSON-файле, Docker не требуется |
| **CUDA** | Не нужна напрямую | Ollama несёт свои CUDA-библиотеки |
| **Rust toolchain** | Только при сборке | Для компиляции qex из исходников |

**Модель эмбеддингов** (зависит от платформы):
- **macOS**: `qwen3-embedding:8b` (4096-dim, ~4.7 GB VRAM)
- **Windows**: `qwen3-embedding:4b` (2560-dim, ~2.5 GB VRAM)

Установка один раз (пример для macOS):
```bash
ollama pull qwen3-embedding:8b
```

---

## 4. Установка на Windows

### 4.1 Ollama

1. Скачать с https://ollama.com/download/windows и установить
2. Загрузить модель:
   ```powershell
   ollama pull qwen3-embedding:4b
   ```
3. Проверить:
   ```powershell
   curl http://localhost:11434/
   # Ожидаемо: "Ollama is running"
   ollama list | grep qwen3-embedding
   ```

### 4.2 Сборка бинарника qex

> Нужно только один раз. Если `~/.cargo/bin/qex.exe` уже есть — пропустить.

**Требования:** Rust toolchain (`rustup update stable`) + MSVC Build Tools 14.x

```powershell
# Скачать исходники qex-0.0.2 и перейти в них
# (располагать вне репозитория проекта — иначе target/ раздует проект на 2 GB)
cd $HOME\Downloads\qex-0.0.2

# Сборка с feature vector (кастомный brute-force vector store)
cargo build --release -p qex-mcp --features "vector"

# Развернуть бинарник
cp target\release\qex.exe $HOME\.cargo\bin\qex.exe
```

> Бинарник появится здесь: `target\release\qex.exe` (~43 MB).  
> После копирования в `~/.cargo/bin/` папку `target\` можно удалить — освободит ~2 GB.

### 4.3 Проверка бинарника

```powershell
# Проверить что бинарник доступен
$HOME\.cargo\bin\qex.exe --version
```

### 4.4 Ежедневный запуск (Windows)

```powershell
# Запустить Ollama ДО открытия Claude Code
ollama serve

# Или убедиться что Ollama уже работает как служба:
curl http://localhost:11434/
```

> Claude Code подхватывает qex автоматически через MCP при запуске. Никаких дополнительных
> действий не нужно — только чтобы Ollama был запущен раньше Claude Code.

---

## 5. Установка на macOS

> Полная пошаговая инструкция для агента на новой машине.

### 5.1 Ollama

```bash
# Установить Ollama
# Скачать DMG с https://ollama.com/download/mac и установить
# Либо через Homebrew:
brew install ollama

# Загрузить модель (на macOS используется 8b)
ollama pull qwen3-embedding:8b

# Проверить
curl http://localhost:11434/
ollama list | grep qwen3-embedding
```

### 5.2 Сборка бинарника qex

```bash
# Скачать исходники qex-0.0.2 (располагать вне репозитория проекта)
cd ~/Desktop/qex   # или ~/Downloads/qex-0.0.2

# Сборка для macOS: dense (usearch HNSW) + openai (HTTP-клиент для Ollama)
# На macOS Apple clang компилирует usearch без проблем
cargo build --release -p qex-mcp --features "dense,openai"

# Развернуть бинарник
cp target/release/qex ~/.local/bin/qex

# macOS 26 (Tahoe)+: обязательно пересигнировать после копирования
# Без этого — SIGKILL (Code Signature Invalid) при запуске
codesign --force --sign - ~/.local/bin/qex
```

> **Почему `dense,openai`?**
> - `dense` — включает usearch HNSW для хранения векторов (быстрее BM25-only, O(log n) поиск)
> - `openai` — включает HTTP-клиент для вызова Ollama через OpenAI-compatible API
> - Без `openai` флага: `QEX_EMBEDDING_PROVIDER=openai` завершится ошибкой тихо → только BM25

### 5.3 Создать `.mcp.json` в корне проекта

Создать файл `<путь_к_проекту>/.mcp.json`:

```json
{
  "mcpServers": {
    "qex": {
      "command": "/Users/<USER>/.local/bin/qex",
      "args": [],
      "env": {
        "RUST_LOG": "info",
        "WORKSPACE_PATH": "/Users/<USER>/path/to/project",
        "QEX_EMBEDDING_PROVIDER": "openai",
        "QEX_OPENAI_BASE_URL": "http://localhost:11434/v1",
        "QEX_OPENAI_API_KEY": "ollama",
        "QEX_OPENAI_MODEL": "qwen3-embedding:8b",
        "QEX_OPENAI_DIMENSIONS": "4096"
      }
    }
  }
}
```

Заменить `<USER>` на имя пользователя macOS, `<путь_к_проекту>` — на реальный путь.

### 5.4 Первая индексация (macOS)

```bash
# 1. Запустить Ollama ДО открытия Claude Code
ollama serve &

# 2. Открыть Claude Code (VS Code с расширением или claude CLI)
# 3. Reload Window если уже открыт: Cmd+Shift+P → Developer: Reload Window

# 4. В чате Claude Code:
# mcp__qex__index_codebase(path="/Users/<USER>/path/to/project", force=true)
```

Первая индексация: ~30-40 мин для ~16k chunks на GPU.

### 5.5 Ежедневный запуск (macOS)

```bash
# Запустить Ollama ДО открытия Claude Code
ollama serve &

# Всё. Claude Code подхватывает qex автоматически через MCP.
```

---

## 6. MCP конфигурация

### Модель эмбеддингов по платформе

| Платформа           | Модель               | Размерность | VRAM    |
|---------------------|----------------------|-------------|---------|
| **macOS** (dev)     | `qwen3-embedding:8b` | 4096 dim    | ~4.7 GB |
| **Windows** (build) | `qwen3-embedding:4b` | 2560 dim    | ~2.5 GB |

8b даёт более точный семантический поиск. На Windows используется 4b из-за ограничений VRAM.

> **Важно при смене модели:** измерения векторов меняются → нужно очистить индекс:
> `mcp__qex__clear_index` → `mcp__qex__index_codebase(force=true)`

### Конфиг macOS — `.mcp.json` в корне проекта (актуальный)

```json
{
  "mcpServers": {
    "qex": {
      "command": "/Users/twokrai/.local/bin/qex",
      "args": [],
      "env": {
        "RUST_LOG": "info",
        "WORKSPACE_PATH": "/absolute/path/to/your-project",
        "QEX_EMBEDDING_PROVIDER": "openai",
        "QEX_OPENAI_BASE_URL": "http://localhost:11434/v1",
        "QEX_OPENAI_API_KEY": "ollama",
        "QEX_OPENAI_MODEL": "qwen3-embedding:8b",
        "QEX_OPENAI_DIMENSIONS": "4096"
      }
    }
  }
}
```

### Конфиг Windows — `.mcp.json` в корне проекта

```json
{
  "mcpServers": {
    "qex": {
      "command": "C:\\Users\\<USER>\\.cargo\\bin\\qex.exe",
      "args": [],
      "env": {
        "RUST_LOG": "info",
        "WORKSPACE_PATH": "C:\\path\\to\\your-project",
        "QEX_EMBEDDING_PROVIDER": "openai",
        "QEX_OPENAI_BASE_URL": "http://localhost:11434/v1",
        "QEX_OPENAI_API_KEY": "ollama",
        "QEX_OPENAI_MODEL": "qwen3-embedding:4b",
        "QEX_OPENAI_DIMENSIONS": "2560"
      }
    }
  }
}
```

> `QEX_OPENAI_API_KEY=ollama` — Ollama не проверяет ключ, но поле обязательно для
> OpenAI-compatible API.  
> `QEX_OPENAI_DIMENSIONS` — обязательно указывать явно (2560 для 4b, 4096 для 8b).

### Проверка что конфиг применился (Windows)

```powershell
# Какой процесс qex реально запущен
Get-Process | Where-Object {$_.Name -like "*qex*"} | Select-Object Name, Path, Id

# После изменения mcp.json — перезагрузить окно:
# Ctrl+Shift+P → Developer: Reload Window
```

### Приоритет конфигов

Claude Code загружает и мержит MCP-конфиги из двух мест:

| Уровень | Путь | Назначение |
|---------|------|------------|
| Проектный | `.mcp.json` в корне проекта | Для команды (коммитится в git) |
| Глобальный | `~/.claude.json` → `mcpServers` | Персональный (не коммитится) |

> **Важно:** проектный файл — именно `.mcp.json` в корне, **не** `.claude/mcp.json`.
> Оба уровня мержатся. При конфликте имён глобальный может перекрыть проектный.

Проверить наличие глобального конфига:

```powershell
python -c "import json, os; d=json.load(open(os.path.expanduser(r'~\.claude.json'))); print(json.dumps(d.get('mcpServers',{}), indent=2))"
```

---

## 7. Файл .ignore — что индексировать

В корне проекта лежит `.ignore` (whitelist-стратегия): исключить всё, кроме активных директорий.

```
# Корень: исключить всё
/*
# Кроме активных директорий (адаптируй под свой проект)
!/src/
!/tests/
!/scripts/
!/docs/
!/plans/
!/.claude/

# Исключить мусор внутри разрешённых директорий
**/*.log
**/*.log.*
**/logs/
**/archive/
**/*.pyc
**/__pycache__/
**/.pytest_cache/
**/plans/
```

> При изменении `.ignore` нужна полная переиндексация: `clear_index` → `index_codebase(force=true)`.

---

## 8. Первая индексация

### Через Claude Code (рекомендуется)

После настройки `.mcp.json` и Reload Window в VS Code:

```
# В чате Claude Code:
mcp__qex__index_codebase(path="<PROJECT_PATH>", force=true)
```

Заменить `<PROJECT_PATH>` на абсолютный путь к проекту.

Ожидаемое время:
- BM25 часть (Tantivy): ~3 секунды
- Dense часть (Ollama GPU): ~30-40 мин для ~16k chunks на RTX 3050 4GB

### Через CLI (для скриптов)

```bash
(
echo '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"cli","version":"1.0"}}}'
echo '{"jsonrpc":"2.0","method":"notifications/initialized"}'
echo '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"index_codebase","arguments":{"path":"<PROJECT_PATH>","force":true}}}'
sleep 3600
) | RUST_LOG=info \
  QEX_EMBEDDING_PROVIDER="openai" \
  QEX_OPENAI_BASE_URL="http://localhost:11434/v1" \
  QEX_OPENAI_API_KEY="ollama" \
  QEX_OPENAI_MODEL="qwen3-embedding:4b" \
  QEX_OPENAI_DIMENSIONS="2560" \
  qex 2>&1
```

### Правильный порядок запуска

```
1. ollama serve       ← сначала Ollama
2. Открыть Claude Code ← только потом
```

Если Claude Code открыт до Ollama — qex MCP сервер стартует без подключения к embedder.
Исправление: перезагрузить окно (`Ctrl+Shift+P → Developer: Reload Window` на Windows,
`Cmd+Shift+P → Developer: Reload Window` на macOS).

---

## 9. Инкрементальное обновление индекса

При обычной работе qex обновляется автоматически: хранит хеши файлов в SQLite и при
`index_codebase(force=false)` переиндексирует только изменённые файлы.

| Сценарий | Команда | Время |
|----------|---------|-------|
| Изменил несколько файлов | `index_codebase(force=false)` или авто | Секунды |
| Изменил `.ignore` | `clear_index` → `index_codebase(force=true)` | ~40 мин |
| Сменил embedding-модель | `clear_index` → `index_codebase(force=true)` | ~40 мин |
| Первая установка | `index_codebase(force=true)` | ~40 мин |

---

## 10. Поиск

```
mcp__qex__search_code(path="<PROJECT_PATH>", query="маршрутизация сообщений")
```

Режим поиска определяется автоматически:
- Если `dense.usearch` существует → **гибридный** (BM25 + HNSW + RRF)
- Если нет → **BM25 only** (fallback: бинарник без dense feature или embedding не завершился)

Статус индексации:

```
mcp__qex__get_indexing_status(path="<PROJECT_PATH>")
```

---

## 11. Диагностика

### Проверка Ollama

```bash
# Ollama запущен?
curl http://localhost:11434/
# Ожидаемо: "Ollama is running"

# Модель установлена?
ollama list | grep qwen3-embedding

# Тест эмбеддинга (должен вернуть 2560 чисел)
curl http://localhost:11434/v1/embeddings \
  -H "Content-Type: application/json" \
  -d '{"model":"qwen3-embedding:4b","input":"hello world"}' | \
  python3 -c "import sys,json; d=json.load(sys.stdin); emb=d['data'][0]['embedding']; print(f'dims={len(emb)}')"
# Ожидаемо: dims=2560
```

### Проверка индекса

```bash
# Директория индекса создана?
ls -lh ~/.qex/projects/
# Windows:
dir $HOME\.qex\projects\

# Проверить наличие dense-индекса (usearch)
ls -lh ~/.qex/projects/*/dense/dense.usearch
# Windows:
dir $HOME\.qex\projects\*\dense\dense.usearch

# Метаданные эмбеддера
cat ~/.qex/projects/*/dense/dense_meta.json
# Ожидаемо: {"provider":"openai","dimensions":4096,"model_name":"qwen3-embedding:8b"}
```

### Проверка qex процесса (Windows)

```powershell
# qex запущен?
Get-Process | Where-Object {$_.Name -like "*qex*"} | Select-Object Name, Path, Id

# Логи qex (в VS Code: View → Output → выбрать "qex" в выпадающем меню)
```

### qex не запускается на macOS 26 (Tahoe) — SIGKILL

**Симптом:** `qex --version` завершается с exit code 137, в crash-репорте:
```
"signal": "SIGKILL (Code Signature Invalid)"
"namespace": "CODESIGNING", "indicator": "Invalid Page"
```

**Причина:** macOS 26 ужесточил валидацию code signature при загрузке dyld. Бинарник,
скомпилированный из исходников (`cargo build`), получает невалидную ad-hoc подпись.

**Решение:** пересигнировать после каждой сборки/копирования:
```bash
codesign --force --sign - ~/.local/bin/qex

# Проверить
/Users/twokrai/.local/bin/qex --version   # должно напечатать версию
```

**Диагностика:**
```bash
# Проверить crash-репорт
ls ~/Library/Logs/DiagnosticReports/ | grep qex

# Проверить spctl
spctl --assess --verbose ~/.local/bin/qex
```

---

### Полный чеклист при проблемах

```bash
# 1. Ollama
curl http://localhost:11434/               # "Ollama is running"
ollama list | grep qwen3-embedding         # модель присутствует

# 2. Индекс
ls ~/.qex/projects/                        # директория существует

# 3. Статус через MCP
# mcp__qex__get_indexing_status(path="<PROJECT_PATH>")

# 4. Тест поиска
# mcp__qex__search_code(path="<PROJECT_PATH>", query="test")
```

---

## 12. Справочник переменных окружения

| Переменная | Значение | Описание |
|-----------|----------|----------|
| `RUST_LOG` | `info` | Уровень логирования (`info` / `debug` / `trace`) |
| `WORKSPACE_PATH` | путь к проекту | Рабочая директория для qex |
| `QEX_EMBEDDING_PROVIDER` | `openai` | Провайдер эмбеддингов (`openai` = OpenAI-compatible API, работает с Ollama) |
| `QEX_OPENAI_BASE_URL` | `http://localhost:11434/v1` | URL Ollama (OpenAI-compatible endpoint) |
| `QEX_OPENAI_API_KEY` | `ollama` | API key (Ollama не проверяет, но поле обязательно) |
| `QEX_OPENAI_MODEL` | `qwen3-embedding:4b` | Модель для эмбеддингов |
| `QEX_OPENAI_DIMENSIONS` | `2560` | Размерность вектора (зависит от модели, для `qwen3-embedding:4b` = 2560) |

---

## 13. FAQ

### Q: Нужен ли Docker / Qdrant?

Нет. В текущей схеме (qex 0.0.2, feature `dense,openai`) вектора хранятся в usearch HNSW файле
`~/.qex/projects/.../dense/dense.usearch`. Docker и Qdrant не нужны.

### Q: Какие feature-флаги нужны при сборке?

**macOS:** `--features "dense,openai"` — usearch HNSW (O(log n)) + HTTP-клиент для Ollama  
**Windows:** требует отдельного исследования (usearch может плохо компилироваться MSVC). Возможно, нужен другой подход.

### Q: `index_codebase` завершается мгновенно (~1 сек), dense-поиск не работает

Два возможных сценария:

**Сценарий A: бинарник собран без нужных feature-флагов**
- Симптом: индекс строится за 1 секунду, `dense/` директории нет
- Причина: бинарник собран без `--features "dense,openai"` → только BM25
- Решение: пересобрать с `cargo build --release -p qex-mcp --features "dense,openai"`,
  задеплоить, перезагрузить окно

**Сценарий B: Ollama не был запущен при старте Claude Code**
- Симптом: `dense/` директории нет или пустая, индекс за 1 сек
- Причина: qex инициализировал embedder при старте, Ollama был недоступен — ошибка поглощена тихо
- Решение: запустить `ollama serve`, перезагрузить окно (`Cmd+Shift+P → Developer: Reload Window`),
  затем `index_codebase(force=true)`

**Проверить правильно ли собран бинарник:**
```bash
nm ~/.local/bin/qex | grep -c "usearch"
# Должно быть > 0 (usearch скомпилирован)
```

### Q: Как проверить что dense-индексация прошла успешно?

```bash
ls -lh ~/.qex/projects/*/dense/dense.usearch
cat ~/.qex/projects/*/dense/dense_meta.json
```

`dense.usearch` должен существовать и иметь ненулевой размер (для ~16k chunks 4096-dim — около 270-300 MB).
`dense_meta.json` содержит `{"provider":"openai","dimensions":4096,"model_name":"qwen3-embedding:8b"}`.

> **Примечание:** `dense_search_available: true` в ответе `get_indexing_status` означает что ONNX-модель
> `arctic-embed-s` установлена локально — это НЕ индикатор что Ollama/OpenAI embedder готов.
> Для проверки используй `ls -lh ~/.qex/projects/*/dense/dense.usearch`.

### Q: Сменил embedding-модель, поиск стал хуже / падает с ошибкой

При смене модели нужен полный сброс индекса:
1. `mcp__qex__clear_index(path="<PROJECT_PATH>")`
2. Обновить `QEX_OPENAI_MODEL` и `QEX_OPENAI_DIMENSIONS` в `.mcp.json`
3. Reload Window
4. `mcp__qex__index_codebase(path="<PROJECT_PATH>", force=true)`

### Q: Можно ли вернуться к старой схеме (Qdrant)?

Да. Пересобрать с feature `dense` (usearch HNSW, на macOS) или подключить внешний Qdrant.
Потребуется изменить переменные окружения: добавить `QDRANT_URL`, `QDRANT_COLLECTION_NAME`,
изменить `QEX_EMBEDDING_PROVIDER`. Описание старой схемы: предыдущая версия этого файла
в git-истории (коммит до 2026-04-29).

### Q: Нельзя заменить qex.exe — файл занят (Windows)

Решение: копировать под новым именем, обновить `command` в конфиге.

```powershell
cp $HOME\.cargo\bin\qex.exe $HOME\.cargo\bin\qex-new.exe
# Обновить command в .mcp.json на qex-new.exe
# Ctrl+Shift+P → Developer: Reload Window
```
