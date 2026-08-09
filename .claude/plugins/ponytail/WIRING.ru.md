# ponytail — как он установлен здесь

**Конфигурация: skills-only.** Хуков в `.claude/settings.json` нет, always-on-инъекции нет.
Границу «когда применять» задаёт секция *«ponytail — when the laziness ladder applies»*
в [`.claude/CLAUDE.md`](../../CLAUDE.md).

Почему не always-on:

- Собственное описание скилла — «use on ANY coding task», то есть в этом репозитории
  это тот же always-on, только со случайным моментом срабатывания.
- Свод правил ponytail спорит с дисциплиной проекта («trivial one-liners need no test»,
  «fewest files possible», «code first, at most three short lines») — оба набора помечены
  как постоянно активные, и победитель непредсказуем. Секция в `CLAUDE.md` разрешает
  конфликт явно: правила проекта побеждают.
- Замеренный выигрыш (JetBrains, 80 парных задач, Sonnet 5) — −15% кода / −10% стоимости
  на фиче-задачах с нуля. Здесь преобладает работа с механикой 27 существующих модулей,
  где верхние ступени лестницы почти не срабатывают.

## Что доступно

| Скилл | Что делает |
|---|---|
| `ponytail` | лестница YAGNI перед написанием кода |
| `ponytail-review` | ревью дифа только на переусложнение |
| `ponytail-audit` | то же по всему репозиторию |
| `ponytail-debt` | собрать все `ponytail:`-комментарии в реестр долга |
| `ponytail-gain` | табло замеров апстрима |
| `ponytail-help` | справка по режимам |

## Замеры на этой машине

| Что | Значение |
|-----|----------|
| Инъекция SessionStart, режим `full` | 5252 байта (~1.4k токенов) |
| То же, `lite` / `ultra` | 5225 / 5290 — **разница 65 байт**, дозировки нет |
| `UserPromptSubmit` на обычном промпте | пустой вывод, exit 0 |
| `UserPromptSubmit` на `/ponytail ultra` | `PONYTAIL MODE CHANGED — level: ultra` |

Уровни `lite`/`full`/`ultra` фильтруют лишь строку таблицы и пару примеров — сам свод
правил идентичен. «Включить послабее» не работает.

## Аудит стороннего кода (сделан перед вливанием)

- Сеть (`fetch` / `http` / `https`) — **ни одного вызова**.
- Выполнение команд (`child_process` / `execSync` / `spawn`) — **нет**.
- Запись на диск: `~/.claude/.ponytail-active` (флаг режима) и
  `%APPDATA%\ponytail\config.json` (только по `/ponytail default <mode>`).
- MIT, v4.8.4. Вендорнуты только `hooks/` + `skills/` (110 КБ); benchmarks, assets
  и tests апстрима не переносились.

## Если всё-таки понадобится always-on

Требует `node` в PATH (проверено: v20.20.2). Три вставки в `.claude/settings.json`:

**1. Вторым элементом массива `hooks.SessionStart`** (после блока с `session-memory-banner.sh`):

```json
{
  "matcher": "startup|resume|clear|compact",
  "hooks": [
    {
      "type": "command",
      "command": "node \"${CLAUDE_PROJECT_DIR}/.claude/plugins/ponytail/hooks/ponytail-activate.js\"",
      "timeout": 5,
      "statusMessage": "Loading ponytail mode..."
    }
  ]
}
```

**2. Новые ключи `hooks.UserPromptSubmit` и `hooks.SubagentStart`** (рядом с `PreToolUse`) —
дают переключение `/ponytail lite|full|ultra|off` и раздачу режима субагентам dev-команды:

```json
"UserPromptSubmit": [
  {
    "hooks": [
      {
        "type": "command",
        "command": "node \"${CLAUDE_PROJECT_DIR}/.claude/plugins/ponytail/hooks/ponytail-mode-tracker.js\"",
        "timeout": 5,
        "statusMessage": "Tracking ponytail mode..."
      }
    ]
  }
],
"SubagentStart": [
  {
    "hooks": [
      {
        "type": "command",
        "command": "node \"${CLAUDE_PROJECT_DIR}/.claude/plugins/ponytail/hooks/ponytail-subagent.js\"",
        "timeout": 5,
        "statusMessage": "Loading ponytail mode..."
      }
    ]
  }
],
```

Выключить, не трогая settings.json: `PONYTAIL_DEFAULT_MODE=off` в env.

## Обновление

```bash
git clone --depth 1 https://github.com/DietrichGebert/ponytail.git /tmp/pt
cp -r /tmp/pt/hooks /tmp/pt/skills .claude/plugins/ponytail/
for d in .claude/plugins/ponytail/skills/*/; do
  cp "$d/SKILL.md" ".claude/skills/$(basename "$d")/SKILL.md"
done
```

Версию в [`.claude/enabled.yaml`](../../enabled.yaml) обновить вручную.
