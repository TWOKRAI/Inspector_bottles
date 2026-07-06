---
description: Check Markdown links (relative paths, anchors, optionally HTTP)
---

Запусти проверку Markdown-ссылок в проекте:

```bash
python scripts/link_check/link_check.py
```

Что ловит: битые относительные пути (`[x](../foo.md)`), отсутствующие anchor'ы (`[x](#section)`), нестандартные схемы. HTTP-проверка — опционально (по умолчанию OFF, чтобы не зависеть от сети).

Конфиг: [scripts/link_check/link_check.toml](../../scripts/link_check/link_check.toml). Детали и exit-коды — [README.md](../../scripts/link_check/README.md).

Полезные варианты:
- `python scripts/link_check/link_check.py --external` — включить HEAD-проверку HTTP-ссылок (медленнее).
- `python scripts/link_check/link_check.py --format json --no-strict` — для CI без падения.
- `python scripts/link_check/link_check.py --no-anchor` — пропустить anchor'ы (полезно если генератор сайта использует свои slug'и).

**Inline-suppression:** `<!-- link-check: ignore -->` в той же строке отключает все проверки.

**Когда использовать:**
- В `pre-commit` (с `--no-external`) — быстрый gate на правильность относительных путей.
- В CI как gate на корректность docs.
- После рефакторинга/переименования файлов — поймать ссылки, оторвавшиеся от целей.

**Замечания:**
- Парсер ловит `[text](url)` и `<https://...>`, не парсит reference-style `[text][ref]`.
- Slug'и заголовков — GitHub-стиль (`# My Heading` → `my-heading`). Для mkdocs-material с custom slug'ами выключи `--no-anchor`.

$ARGUMENTS
