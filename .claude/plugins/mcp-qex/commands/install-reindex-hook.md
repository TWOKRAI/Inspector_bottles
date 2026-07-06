---
description: Install the qex post-commit reindex hook (auto-reindexes qex after each commit; no-ops when Ollama/qex is down)
---

Установи git post-commit hook, который инкрементально переиндексирует qex после
каждого `git commit` — чтобы семантический поиск (`mcp__qex__search_code`) не
отставал от текущего состояния кода и агенты не деградировали в `Grep`.

Скопируй шаблон хука в git-каталог хуков и сделай его исполняемым (идемпотентно —
повторный запуск просто перезапишет). Каталог хуков резолвится через
`git rev-parse --git-path hooks`, поэтому работает и в обычном репо, и в **linked
worktree / submodule** (там `.git` — файл, а хуки лежат в общем git-каталоге):

```bash
(
  cd "$(git rev-parse --show-toplevel)" || exit 1
  HOOKS_DIR="$(git rev-parse --git-path hooks)"
  cp .claude/plugins/mcp-qex/templates/post-commit.hook.sh "$HOOKS_DIR/post-commit"
  chmod +x "$HOOKS_DIR/post-commit"
  echo "Installed: $HOOKS_DIR/post-commit"
)
```

Проверь, что хук на месте (`test -f` — Windows/NTFS не хранит exec-bit, поэтому
`test -x` там бессмысленен):

```bash
test -f "$(git rev-parse --git-path hooks)/post-commit" && echo OK || echo MISSING
```

Что это даёт:

- После каждого коммита qex запускает **инкрементальную** переиндексацию в фоне
  (Merkle-diff, обычно < 5 секунд) — не блокирует коммит.
- Семантический поиск остаётся свежим без ручного `/mcp-qex:qex-reindex`.

**Безопасно при выключенных зависимостях.** Хук сам проверяет окружение и тихо
выходит с `exit 0`, если:

- бинарник qex не найден (`QEX_BIN`, по умолчанию `~/.cargo/bin/qex`);
- Ollama недоступен на `http://localhost:11434/`.

То есть установка хука не ломает коммиты даже без MCP-зависимости.

**Путь к бинарнику** — если qex не в `~/.cargo/bin/qex`, задай `QEX_BIN` в окружении
или поправь строку `QEX_BIN=` в начале установленного `.git/hooks/post-commit`.

**Отключение** (надёжный способ для всех платформ — удалить файл):

```bash
rm "$(git rev-parse --git-path hooks)/post-commit"
```

> На Linux/macOS можно временно: `chmod -x "$(git rev-parse --git-path hooks)/post-commit"`.
> На **Windows/Git-Bash** `chmod -x` неэффективен (NTFS не хранит POSIX exec-bit —
> git-for-windows запускает хук, пока файл существует), поэтому отключай через `rm`.

**Лог переиндексации** пишется в `.qex-reindex.log` в корне проекта.

> ⚠️ **Worktree / lock-гонка.** Если qex уже запущен в Claude Code и держит
> блокировку на индексе, фоновый вызов из хука может конфликтовать (хук это
> переживёт — напечатает «qex stdio call failed»). При работе в нескольких
> git-worktree запускай переиндексацию **только из главного worktree**; в таком
> случае отключи хук и вызывай `/mcp-qex:qex-reindex` вручную.

Файлы:

- [templates/post-commit.hook.sh](../templates/post-commit.hook.sh) — шаблон хука
  (что копируется в `.git/hooks/`).

После установки хук работает локально (не уезжает в репозиторий — `.git/hooks/`
вне version control). На новой машине надо переустановить. Проверить, установлен
ли хук, можно через `/core:quality:doctor`.

$ARGUMENTS
