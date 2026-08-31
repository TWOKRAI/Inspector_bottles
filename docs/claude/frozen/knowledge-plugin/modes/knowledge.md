# Knowledge Mode — работа со знаниями

Загружается при задачах: транскрипция видео/аудио, курирование заметок, синтез статей, поиск по wiki, Q&A по базе знаний, перевод материалов, уборка wiki-индекса.

## Pipeline знаний

```
URL/файл         → /knowledge:transcribe            →  knowledge/raw/videos/{slug}/  (неизменяемо)
                 → /knowledge:curate [--enrich]     →  knowledge/wiki/{type_folder}/{slug}.md  (1 источник → draft + light enrichment)
                 → /knowledge:synthesize            →  knowledge/wiki/{type_folder}/{slug}.md  (2+ источников ИЛИ deep enrichment Opus)
                 → /knowledge:library               →  обновить index.md (+ структурный lint)
                 → /knowledge:compress              →  knowledge/wiki-llm/  (уровень 2 → 3, активируется с ≥30 статей)
                 → /knowledge:research [--save]     →  Q&A; --save → wiki/qa/{date}-{slug}.md (компаундинг)
```

## Двухуровневая wiki

При правке любой статьи `knowledge/wiki/**/*.md` (если подключён auto-pipeline хуками):
1. **PostToolUse hook** добавляет путь в `knowledge/wiki-llm/.compress_queue`
2. **SessionStart hook** напоминает: "В очереди N статей. Запусти /knowledge:compress queue"
3. `/knowledge:compress queue` → sci-compressor (Haiku) сжимает каждую → sync-линтер → очистка очереди
4. **Stop hook** + **pre-commit hook** ловят рассинхрон при выходе/коммите

При `/knowledge:research` / Q&A — Claude читает `knowledge/wiki-llm/index.md` первым (~3000 слов), спускается на L2 только при `[?DETAILS]`. Экономия ×5-6 на токенах чтения.

L3 окупается с ~30 статей. До этого порога — оставлять `wiki-llm/` пустым, не сжимать.

## Spec-файлы wiki (Karpathy-метод)

| Файл | Owner | Назначение |
|------|-------|------------|
| `wiki/index.md` | sci-librarian (single-owner) | Каталог one-line summaries по темам |
| `wiki/log.md` | append-only, любая команда | Хроника операций (curate/research/synthesize) |
| `wiki/schema.md` | редкие правки | Конституция: frontmatter, naming, статусы |

Каждая команда (`/knowledge:curate`, `/knowledge:research --save`, `/knowledge:synthesize`) **обязана дописывать запись в log.md** в конце операции. Формат: `## [YYYY-MM-DD] <операция> | <описание>`.

## Typed entities (frontmatter `type:`)

8 типов: `concept | person | paper | video | tool | comparison | qa | daily`. Полный enum + правила в [`knowledge/wiki/schema.md`](../../knowledge/wiki/schema.md).

## Состав команды (`.claude/plugins/knowledge/agents/`)

| Агент | Модель | Команда | Назначение |
|-------|--------|---------|-----------|
| **sci-transcriber** | Sonnet | `/knowledge:transcribe` | URL/файл → `raw/videos/{slug}/` (yt-dlp + Whisper + перевод + организация) |
| **sci-curator** | Sonnet | `/knowledge:curate` | 1 source → draft wiki-статья. Читает `inbox/` и `raw/` |
| **sci-synthesizer** | Opus | `/knowledge:synthesize` | 2+ sources → полная статья ИЛИ промоушен draft → reviewed |
| **sci-researcher** | Opus | `/knowledge:research` | Глубокое Q&A по базе знаний, перекрёстный анализ |
| **sci-searcher** | Sonnet | `/knowledge:search` | Семантический поиск через qex MCP (per-zone: knowledge, apps, projects, workspace) |
| **sci-librarian** | Sonnet | `/knowledge:library` | Единственный owner `knowledge/wiki/index.md`. Дедупликация, чистка тегов, валидация промоушенов |
| **sci-compressor** | Haiku | `/knowledge:compress` | Wiki (~800 слов) → wiki-llm (~80 слов). Автоматически, без ручных правок |
| **sci-digest** | Haiku | `/knowledge:digest` | Еженедельный отчёт: что добавлено, выросшие статьи, открытые вопросы |
| **sci-translator** | Dynamic | `/knowledge:translate` | EN→RU. Роутинг: Haiku для коротких простых текстов, Sonnet для длинных/технических |

## Ключевые правила

1. **Raw is sacred** — `knowledge/raw/` никогда не редактируется после создания
2. **Wiki-LLM auto-generated** — `knowledge/wiki-llm/` пишет ТОЛЬКО sci-compressor, никогда вручную
3. **Wiki index single-owner** — только sci-librarian пишет в `knowledge/wiki/index.md`. Остальные предлагают через `workspace/wiki_index_proposals.md`
4. **Curator vs Synthesizer** —
   - 1 source → sci-curator создаёт draft + **light enrichment** (≥1 инсайт, ≥2 wikilink, 3-5 проверяемых гипотез)
   - 2+ sources → sci-synthesizer Сценарий A (полная статья)
   - 1 source + 3+ связанных wiki-статей в теме → sci-synthesizer Сценарий B opt-in через `/knowledge:curate --enrich` или `/knowledge:synthesize <slug>` (Opus, дорого, structured handoff от curator)
   - Промоушен draft → reviewed → sci-synthesizer Сценарий C + sci-librarian validation
5. **Translate routing** — по длине И содержанию: Sonnet если ≥300 слов ИЛИ код ИЛИ frontmatter ИЛИ технические термины; Haiku только для коротких простых заметок
6. **Search zones isolated** — каждый qex-индекс per-zone (knowledge, projects:<slug>, apps, workspace). Удаление проекта не трогает другие индексы

## Inbox auto-check

При задачах `/knowledge:research`, `/knowledge:search`, `/knowledge:curate`, `/knowledge:synthesize` или любом вопросе по wiki:
1. Проверить `knowledge/inbox/` на необработанные файлы
2. Если не пусто — перечислить файлы + спросить: "Обработать сначала?"
3. Если yes → `/knowledge:curate` (или `/knowledge:synthesize` для нескольких связанных источников) для каждого, потом к исходному запросу
4. Если no → пропустить, работать с существующей wiki

Проверка **периодическая, не блокирующая** — один раз за сессию. После проверки не переспрашивать.

## Типовые сценарии

```
Новое видео/подкаст → wiki        →  /knowledge:transcribe URL  →  /knowledge:curate  →  /knowledge:library apply
Новая идея / заметка → wiki       →  файл в inbox  →  /knowledge:curate
Обзор по теме из 3+ источников    →  /knowledge:synthesize <тема>  →  /knowledge:library apply
Быстрый поиск в базе              →  /knowledge:search knowledge:"запрос"
Глубокий ответ на вопрос          →  /knowledge:research "вопрос"
Полезный ответ → новая страница   →  /knowledge:research "вопрос" --save
Уборка структуры (индекс, дубли)  →  /knowledge:library
Еженедельный отчёт                →  /knowledge:digest
Перевод EN → RU                   →  /knowledge:translate <файл>
```

## Zones языки

| Zone | Path | Language |
|------|------|----------|
| Wiki | `knowledge/wiki/` | Russian (по умолчанию), Obsidian wikilinks, frontmatter required |
| Wiki-LLM | `knowledge/wiki-llm/` | Same as wiki, auto-generated |
| Raw | `knowledge/raw/` | Mixed (EN transcripts возможны) |
| Inbox | `knowledge/inbox/` | Any, temporary |

Если в проекте установлена строгая language policy в [`_stack.md`](_stack.md) — wiki должна следовать ей.
