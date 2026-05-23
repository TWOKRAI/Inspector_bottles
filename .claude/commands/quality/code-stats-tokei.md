---
description: Точный подсчёт LOC через tokei (общий TOML с /code-stats)
---

Запусти tokei-обёртку:

```bash
python scripts/code_stats/code_stats_tokei.py
```

Особенности:
- Использует ТОТ ЖЕ конфиг [scripts/code_stats/code_stats.toml](../../scripts/code_stats/code_stats.toml) — расширения, исключения, формат вывода.
- Требует бинарь `tokei` (`brew install tokei` / `cargo install tokei`). Если не установлен — скрипт даст подсказку и exit 3.
- Группировка всегда по языку (не по директории) — особенность tokei.
- LOC из tokei **точнее** stdlib-варианта: настоящие токенайзеры распознают комментарии и строковые литералы во всех языках.

Полезные варианты:
- `python scripts/code_stats/code_stats_tokei.py --root src/<package>`
- `python scripts/code_stats/code_stats_tokei.py --format json`

**Когда использовать tokei vs stdlib:**
- tokei — точные цифры, быстрее на больших репо, нужен бинарь.
- `/code-stats` (stdlib) — без зависимостей, можно группировать по директориям.

> `scripts/code_stats/` ставится автоматически через `claude-kit new`. Без него `tokei .` работает напрямую из любой точки проекта (но без shared TOML-конфига).

$ARGUMENTS
