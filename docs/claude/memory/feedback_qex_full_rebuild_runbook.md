---
name: feedback-qex-full-rebuild-runbook
description: Как запускать полный реиндекс qex на Windows без провалов — Ollama вне харнесса, тег -qex, reindex_progress с PYTHONUTF8, проверки до и после; 2026-10-01 первый прогон убит собственным лимитом на 94%
metadata:
  type: feedback
---

**Владелец (2026-10-01): «без таймаутов», и каждый реиндекс «с какими-то проблемами с запуском».
Любой таймаут при реиндексе — мой дефект запуска, а не свойство среды.** Ниже порядок, который
отработал; идти по нему, а не вспоминать по частям.

## Что сломалось 2026-10-01 (все три — запуск, не qex)

1. **`ollama serve` через Bash `run_in_background` без `timeout`** — харнесс убивает фон через
   30 мин. Ollama умер на батче 1543/1639 (~94%) → `Connection refused` → `Indexing failed`.
   У векторной половины нет чекпойнта: 30 минут работы потеряны целиком.
2. **Тега `qwen3-embedding:0.6b-qex` не было**, только базовый `0.6b` (список после рестарта
   Ollama/переустановки). Без тега контекст берётся из `OLLAMA_CONTEXT_LENGTH` (там стояло
   65536) → риск CPU-offload. Лаунчер только предупреждает в stderr, не блокирует.
3. **`reindex_progress.py` падает `UnicodeDecodeError`**: родитель читает вывод дочернего в
   cp1251, а `reindex.py` пишет UTF-8. Лечится окружением `PYTHONUTF8=1`, код не трогать.

## Порядок запуска

1. **Статус сначала:** `get_indexing_status` → `last_indexed` числом (см.
   [[feedback-check-qex-freshness-before-use]]).
2. **Ollama — отдельным процессом, вне харнесса:**
   `powershell -NoProfile -Command "Start-Process -FilePath ollama -ArgumentList 'serve' -WindowStyle Hidden"`
   и ждать `until curl -s -m 2 http://localhost:11434/`. Не фоном Bash. Уже запущенный — не трогать.
3. **Тег `-qex`:** `ollama list | grep 0.6b-qex`; нет →
   `ollama create qwen3-embedding:0.6b-qex -f .claude/plugins/mcp-qex/templates/qwen3-embedding-0.6b-win.Modelfile`,
   затем `ollama show ... --parameters` → `num_ctx 2048`, `num_gpu 999`.
4. **Прогрев и проверка GPU до старта:** `/api/embed` с `keep_alive:"120m"`; `/api/ps` →
   `size == size_vram` (100% GPU); три батча по 64 дают ровные ~2.7 с (скачок 40+ с = модель
   выгружается). Лог Ollama `inference compute ... library=CUDA` подтверждает CUDA.
5. **Запуск:** `PYTHONUTF8=1 PYTHONUNBUFFERED=1 python .claude/plugins/mcp-qex/reindex_progress.py --force`
   в Bash `run_in_background` с **`timeout: 7200000`**. НЕ через MCP `index_codebase` (у
   MCP-вызова клиентский таймаут). Без `--clear`: старый индекс жив до успешного конца.
6. **Один индексатор.** Два на одном Ollama выбивают друг друга по зашитому ~10 с таймауту; MCP-сервер
   сессии в это время ничего не индексирует.
7. **Монитор по строкам qex, не по счётчику скрипта.** `grep "Embedding batch"` → `N/M (X chunks
   done)`. Встроенный счётчик `embedded N` читает `%LOCALAPPDATA%\Ollama\server.log` и при Ollama,
   поднятом не приложением, **стоит на 0** при живой работе (ложный «ничего не происходит»).
   Фильтр монитора обязан ловить отказ: `Connection refused|Indexing failed|Traceback|attempt [12]/3`
   и смерть Ollama (`curl` не отвечает) — молчание не значит «идёт».
8. **Фазы:** сначала BM25 на процессоре (GPU ~0–30%, векторов нет) — норма; потом векторы (GPU 65–90%,
   ~55–63 эмбеддинга/с). Замер 2026-10-01: 52 443 чанка, 1639 батчей по 32, ~30 мин всего.

## Что считать результатом

- **Упавший `--force` оставляет индекс разобранным:** `get_indexing_status` → `file_count: 0`,
  `last_indexed: null` при ненулевом `chunk_count`. Это **не рабочий индекс** — `search_code`
  доверять нельзя, до успешного повтора работать на `Grep`. Не принимать за «обновился».
- Успех: `last_indexed` сегодняшний, `file_count > 0`, `dense/vector_meta.json` = 1024 / 0.6b,
  и `search_code` по только что написанному коду находит его.

## Чего здесь нет намеренно

4b. Не помещается в 4 ГБ VRAM (3876 МиБ) и удалена с диска; размерность 1024 зашита в лаунчер,
`reindex.py` и `reindex_progress.py`. Рецепт `keep_alive=-1` из [[feedback-qex-reindex-budget]] был
под 4b и для 0.6b не нужен (модель ~2.1 ГБ, держится в VRAM сама). Смена модели = правка трёх
файлов + размерность + `clear_index`, см. [[project-qex-model]].

Связано: [[project-qex-reindex-timeout]], [[feedback-qex-reindex-budget]], [[feedback-no-global-taskkill]].
