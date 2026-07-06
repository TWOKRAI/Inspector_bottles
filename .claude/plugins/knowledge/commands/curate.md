---
description: Запустить sci-curator — организовать новый контент (URL/inbox) → draft wiki-статья с light enrichment.
---

Запусти процесс курирования: организуй новый контент из URL или `knowledge/inbox/` в wiki.

**Pipeline:** видео/статья → `inbox/` (или URL) → `/knowledge:curate` → wiki + перемещение в `raw/`.

Входные данные: $ARGUMENTS — один или несколько URL/файлов через пробел или пусто (тогда читается inbox).

## Принципы

1. **Не делай WebFetch в main thread.** URL передавай прямо в curator-агента — у него свой контекст, кэш WebFetch 15 минут.
2. **Не сохраняй полный текст веб-статей в inbox.** Inbox — для локальных файлов и pointer-заметок, не для скачанного веба.
3. **Dedup делает curator**, не main thread. Он всё равно читает `index.md` для своей работы.
4. **Synthesizer (Сценарий B) = opt-in.** По умолчанию запускается только curator. Сценарий B зовётся явно через `--enrich` или `/knowledge:synthesize <slug>`.
5. **Промпты агентам — короткие.** Источник, тема, особые акценты. Формат frontmatter, структура секций, обязательность wikilinks — всё это уже в system prompt агента.

## Флаги

- `--enrich` — после curator запустить sci-synthesizer (Сценарий B). Дорого; используй для глубоких/важных статей.
- `--no-dedup` — пропустить dedup-проверку.
- `--topic <name>` — подсказка папки темы.

## Алгоритм

### Уточнение папки (ОБЯЗАТЕЛЬНО перед каждым куратором)

Если `--topic` **не передан** — спроси у пользователя перед запуском куратора.

1. Прочитай `ls knowledge/wiki/` — актуальный список папок первого уровня.
2. По заголовку / URL / meta.md определи 1-3 наиболее подходящих папки.
3. Покажи вопрос:

```text
📂 Куда положить «{заголовок}»?

Предлагаю: {папка1} · {папка2}

Все папки: <список первого уровня>

→ Нажми Enter чтобы выбрать первый вариант, или введи другое / новое название:
```

- Enter → первый предложенный вариант
- Названо несуществующее → создаётся новая папка
- Batch (N>1 без `--topic`) → задай один вопрос со всеми целями, пронумеровав

### Если переданы URL/пути

1. **Парсинг** $ARGUMENTS → список целей + флаги.
2. **Уточнение папки** для каждой цели без `--topic`.
3. **Запуск sci-curator(ов)** — один агент на цель, параллельно при N>1 (батчи по 6 при N>6).

   **Промпт (компактный):**
   ```
   Источник: <URL или путь>
   Тема (hint): <topic или "">
   Dedup: <on|off>

   Алгоритм:
   1. Если URL — WebFetch источник. Если локальный файл — прочитай.
   2. Прочитай knowledge/wiki/index.md и knowledge/wiki/schema.md (если есть).
   3. Dedup (если on): найди близкие статьи в index.md (≥70% совпадение по сути) →
      НЕ создавай новую, верни STATUS: needs_enrich с путём.
   4. Создай draft knowledge/wiki/{type_folder}/{slug}.md (frontmatter по schema.md,
      ≥2 wikilink в `## Связи`, 3-5 verifiable hypotheses в `## Открытые вопросы`).
   5. Append предложение в workspace/wiki_index_proposals.md.
   6. Append запись в knowledge/wiki/log.md.
   7. Если inbox-файл (.md) — переместить в raw/articles/.
      Если inbox-папка (видео) — вернуть MOVE_REQUIRED в handoff.

   Верни структурированный handoff (см. sci-curator.md):
   - PATH: <путь>
   - STATUS: created | needs_enrich | skipped_dedup
   - RELATED_ARTICLES_FOUND: <число>
   - CROSS_REFS_USED: [wikilinks]
   - OPEN_QUESTIONS: [3-5 пунктов]
   - MOVE_REQUIRED: <inbox/{slug} → raw/videos/{slug}> | none
   ```

4. **Auto-hint synthesizer** — после curator-отчёта смотри на `RELATED_ARTICLES_FOUND`:
   - **<3** — Opus не добавит ценности. Ничего не предлагай.
   - **≥3** — если `--enrich` НЕ передан → выведи:
     ```
     💡 Найдено N связанных статей. Для глубинного обогащения через Opus:
        /knowledge:synthesize <slug>
     ```
   - Если `--enrich` передан → запускай sci-synthesizer автоматически.

5. **Если флаг `--enrich`** — запусти sci-synthesizer для каждой созданной статьи параллельно.

   **Промпт synthesizer (компактный, использует handoff от curator):**
   ```
   Обогати draft (Сценарий B).

   Handoff от curator:
     PATH: <PATH>
     CROSS_REFS_USED: <CROSS_REFS_USED>
     OPEN_QUESTIONS: <OPEN_QUESTIONS>

   Curator уже проставил cross-refs. НЕ перечитывай все связанные статьи —
   читай только сам draft + 1-2 article-stub'а из CROSS_REFS_USED.

   Добавь:
   - Параллели с проектом (если есть)
   - 2-3 неочевидных кросс-доменных инсайта
   - Расширь проверяемые гипотезы (3-5 → 6-10) с привязкой к экспериментам

   Не раздувай. Глубина > объём.
   ```

6. **Если получен `STATUS: needs_enrich`** — спроси:
   ```
   ⚠️ Найден близкий дубль: <статья>
   [a] обогатить через /knowledge:synthesize <slug>
   [b] всё равно создать новую (--no-dedup)
   [c] пропустить
   ```
   В Auto Mode по умолчанию `[a]`.

### Если без аргументов

1. **Сбор материалов** из `knowledge/inbox/`:

   | Тип | Как определить | Действие |
   |-----|---------------|----------|
   | Видео-папка (ready) | Папка с `meta.md`, `status: ready` | Куратор → wiki → переместить в raw |
   | Видео-папка (transcribed) | Папка с `meta.md`, `status: transcribed` | Перевод `transcript.en.md` → `transcript.ru.md` → обновить `meta.md` → куратор |
   | Markdown-файл | `.md` файл (не README, не processed) | Куратор → wiki → пометить processed |
   | URL-pointer | `.md` с полем `url:` в frontmatter | Куратор делает WebFetch → wiki |

2. **Пусто** → `Нет новых материалов. Используй /knowledge:curate <url> или /knowledge:transcribe <url>.`

3. **Перевод `transcribed` папок** (если есть) — до запуска curator-ов. Запусти `sci-translator` параллельно при N>1, потом обнови `meta.md → status: ready`.

4. **Параллельный запуск curator-ов** по тому же шаблону.

5. **После успешного курирования видео-папки** — переместить из `inbox/` в `raw/videos/`:
   ```bash
   mv knowledge/inbox/{slug} knowledge/raw/videos/
   ```

### Финал

1. Curator уже append'нул в `log.md` сам — main thread это НЕ делает повторно.
2. **⚠️ ОБЯЗАТЕЛЬНО: Перемещение из inbox/ в raw/** — сразу после получения handoff. Inbox должен быть ПУСТЫМ после /knowledge:curate.
3. **Двусторонние ссылки wiki ↔ raw** — после перемещения обновить frontmatter wiki-статьи (`source_path:` указывает на raw/) и в `meta.md` видео-папки добавить `wiki_article: <path>`.
4. Краткий отчёт:
   ```
   Обработано: N | Создано: M | Обогащено: K | Дублей: D
   Перемещено в raw/: P папок
   → /knowledge:research <вопрос> или /knowledge:synthesize <slug> для углубления
   ```

## Примеры

```
/knowledge:curate https://habr.com/ru/articles/1022578/              # быстрый curate
/knowledge:curate https://habr.com/ru/articles/1022578/ --enrich     # с обогащением
/knowledge:curate https://x.com https://y.com https://z.com          # batch (3 параллельно)
/knowledge:curate                                                     # обработать inbox
```
