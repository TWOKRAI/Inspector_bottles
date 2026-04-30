---
name: kb-discover
description: Ищет источники по теме (YouTube, статьи, GitHub, papers). Возвращает ранжированный список со ссылками и one-line описаниями. Ничего не сохраняет — только список в чат для передачи в /curate. Закрывает discover-фазу, отсутствующую в /curate и /research.
---

# kb-discover

Поиск источников по теме. Без сохранения — только список.

## Вход

```
kb-discover "<тема>" [--lang ru|en|both] [--type youtube|article|github|paper|all] [--limit N] [--since YYYY]
```

Defaults: `both`, `all`, 10 на тип / 30 всего.

## Алгоритм

1. **3-5 поисковых вариантов** (синонимы, ru+en, узко/широко).
2. **Проверь wiki/index.md** — если тема покрыта, отметить «уже есть [[ссылки]]».
3. **Параллельные WebSearch** в одном turn:
   - общий запрос
   - `site:youtube.com` (если video)
   - `site:github.com` (если github)
   - `site:arxiv.org OR site:paperswithcode.com` (если paper)
4. **Дедуп + ранжирование**. Сигналы:
   - YouTube: просмотры, дата, канал (Karpathy, 3Blue1Brown, Yannic Kilcher = +)
   - Статьи: домен (Anthropic, HF, OpenAI, Karpathy gists = +)
   - GitHub: stars + last commit
   - Paper: citations + arxiv > random preprint
   - Свежесть: для AI/LLM > 12 мес в хвост
5. **One-liner на каждый**:
   ```
   [тип] Название (автор/канал, год) — URL
     → 10-20 слов о чём и почему стоит читать
   ```
6. **Финальный список** разбит по типам + секция «уже есть в базе» + «следующий шаг: /curate <url1> <url2>».
7. **Append log.md**:
   ```
   ## [YYYY-MM-DD] discover | <тема>
   - Найдено: N (yt:n1 art:n2 gh:n3 paper:n4)
   - В базе: [[..]], [[..]]
   ```

## Правила

- Ничего не пишет на диск (кроме log.md).
- Только реальные WebSearch результаты — никаких выдуманных URL.
- Топ 5-15, не 50.
- Один WebFetch на источник допустим только если сниппет неинформативен.
