# observability — токены, tool calls, стоимость сессий

Опциональный модуль. Не MCP-сервер, а **OTel-телеметрия + statusline-инструменты** для Claude Code. Закрывает слепое пятно: сейчас в seed нельзя ответить на вопросы «сколько токенов ушло на эту задачу», «какие tool calls тратят больше всего», «codegraph дал маржу или нет?».

> Канонический путь Claude Code: переменная окружения `CLAUDE_CODE_ENABLE_TELEMETRY=1` включает экспорт OTel-метрик и логов. Дальше дело за collector'ом и dashboard'ом.

## Когда включать

✅ **Включить, если:**
- Решаешь, нужен ли тебе новый MCP — нужна замерочная база, а не интуиция
- Работаешь в команде / на нескольких проектах, нужно понимать burn-rate API
- Запускаешь длинные `/dev:pipeline` и хочешь видеть, где тормозит
- Используешь несколько моделей (Haiku/Sonnet/Opus) и проверяешь, что routing работает

❌ **Можно пропустить, если:**
- Личный проект, один разработчик, нет ограничений по бюджету
- Не готов поднимать Docker stack (для OTel collector — нужен)
- Достаточно ручного `/cost` Claude Code

## Что предлагается

Три ортогональных слоя — берёшь то, что нужно:

### Слой 1: OTel-экспорт (native)

Одна переменная окружения:

```bash
export CLAUDE_CODE_ENABLE_TELEMETRY=1
```

Без collector'а — это просто эмиссия в stdout/файл. Useful как первый шаг и для дешёвой проверки «работает ли вообще».

### Слой 2: Full stack — claude-code-otel

[ColeMurray/claude-code-otel](https://github.com/ColeMurray/claude-code-otel) (MIT, ~400★, активный). Docker Compose:

- OTel Collector — принимает поток
- Prometheus — метрики (tokens, tool calls, durations)
- Loki — структурированные логи
- Grafana — дашборды (готовые из коробки)

`docker compose up -d` → открыть `http://localhost:3000` → готовые панели.

### Слой 3: Statusline-tools (лёгкие, без Docker)

| Tool | Назначение | URL |
|------|-----------|-----|
| **ccusage** | Statusline + историческая аналитика расходов API | <https://ccusage.com/> |
| **ccstatusline** | Powerline-style статуслайн в Claude Code | <https://github.com/sirmalloc/ccstatusline> |
| **Claude Code Usage Monitor (ccm)** | Терминал-дашборд с ML burn-rate prediction | <https://claudefa.st/> |

Все ставятся через `npm i -g <name>` за пару минут, без инфраструктуры.

## Рекомендованный flow

**Минимум (single user, личный проект):**
1. `npm i -g ccusage` → видишь токены в статуслайне
2. Готово

**Полный (команда / несколько проектов):**
1. `CLAUDE_CODE_ENABLE_TELEMETRY=1` в `.env.example` нового проекта
2. Клонировать [claude-code-otel](https://github.com/ColeMurray/claude-code-otel) рядом, `docker compose up -d`
3. Дашборд в Grafana: токены по моделям, top-10 tool calls, drift по дням

## Как использовать для оценки MCP

Когда добавляешь новый MCP (например, codegraph) и хочешь честно проверить маржу:

1. Включи телеметрию **до** добавления
2. Прогони набор реальных задач (5–10 типовых вопросов), записывая tool calls
3. Добавь MCP
4. Прогони те же задачи
5. Сравни total tool calls и tokens. **Делать это в Grafana, а не глазами.**

Это то, что упомянуто в `mcp/codegraph/SETUP_GUIDE.md` § 5 (smoke-test).

## Стоимость

- OTel-экспорт сам по себе — бесплатно, native CC
- claude-code-otel — Docker overhead (~200 MB RAM), MIT
- ccusage/ccstatusline — npm-пакеты, ~10 MB

Нет внешних подписок. Всё локально.

## Конфликты со seed-принципами

Нет. Observability ортогональна git-tracked memory и opt-in MCP-структуре. Telemetry data в Prometheus/Loki **не** идёт в git и **не** конкурирует с `.claude/memory/`.

## Установка

См. [SETUP_GUIDE.md](SETUP_GUIDE.md) — пошагово для каждого из трёх слоёв.
