# observability — Setup Guide

Три ортогональных слоя — устанавливай только нужное.

---

## Слой 1: native OTel-экспорт (5 минут)

Самый дешёвый шаг. Просто включает эмиссию OTel-метрик из Claude Code.

### macOS / Linux

```bash
# В ~/.zshrc или ~/.bashrc
export CLAUDE_CODE_ENABLE_TELEMETRY=1

# Опционально — куда писать (по умолчанию stdout)
export OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318
```

### Windows (PowerShell)

```powershell
[Environment]::SetEnvironmentVariable("CLAUDE_CODE_ENABLE_TELEMETRY", "1", "User")
```

### Проверка

```bash
echo $CLAUDE_CODE_ENABLE_TELEMETRY    # должно вывести 1
```

Перезапустить Claude Code. Без collector'а метрики уйдут в stdout — это нормально для smoke-теста.

---

## Слой 2: full stack (claude-code-otel)

Полный OTel + Prometheus + Loki + Grafana через Docker.

### Prerequisites

- Docker 24+ + Docker Compose
- Свободные порты: 3000 (Grafana), 4317/4318 (OTel), 9090 (Prometheus), 3100 (Loki)
- ~500 MB образов, ~200 MB RAM при работе

### Установка

```bash
# Клонировать рядом с проектом (или в ~/tools/)
git clone https://github.com/ColeMurray/claude-code-otel.git
cd claude-code-otel

# Поднять стек
docker compose up -d

# Проверить
docker compose ps
curl -s http://localhost:3000/api/health    # Grafana
curl -s http://localhost:9090/-/healthy     # Prometheus
```

### Подключение Claude Code

В `~/.zshrc` / `~/.bashrc` / Windows User env:

```bash
export CLAUDE_CODE_ENABLE_TELEMETRY=1
export OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318
export OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf
```

Перезапустить Claude Code. Через минуту первые метрики должны появиться в Grafana.

### Дашборды

Grafana: `http://localhost:3000` (admin/admin при первом входе). Готовые панели:

- **Tokens by model** — Haiku vs Sonnet vs Opus по времени
- **Top tool calls** — какие MCP/tools чаще всего и дольше всего
- **Session cost** — текущая стоимость в $ по проектам
- **Burn rate** — токены/минуту

### Остановка

```bash
cd claude-code-otel
docker compose down                # сохранить данные
docker compose down -v             # снести и данные тоже
```

---

## Слой 3: lightweight statusline (без Docker)

Для тех, кто не хочет Docker — три npm-пакета.

### ccusage — историческая аналитика

```bash
npm install -g ccusage

# Внутри Claude Code:
ccusage today                      # расходы за сегодня
ccusage week                       # последние 7 дней
ccusage statusline                 # включить в статуслайн CC
```

Документация: <https://ccusage.com/>.

### ccstatusline — powerline-style status

```bash
npm install -g ccstatusline
ccstatusline init                  # один раз — пропишет в Claude Code settings
```

### Claude Code Usage Monitor (ccm)

```bash
npm install -g claude-usage-monitor
ccm                                # терминал-дашборд real-time
```

Гайд: <https://claudefa.st/>.

---

## Workflow для оценки нового MCP

Это конкретный сценарий — например, оценка codegraph.

### 1. Baseline

```bash
# Перед добавлением MCP — записать состояние
export CLAUDE_CODE_ENABLE_TELEMETRY=1
```

Прогнать набор задач (5–10 реальных вопросов из проекта). Записать:
- Total tool calls (видно в Grafana → "Top tool calls" → sum)
- Total tokens (Grafana → "Tokens by model" → integral)
- Wall-clock time

### 2. С новым MCP

Добавить MCP. Прогнать **те же** задачи. Записать те же три метрики.

### 3. Сравнение

В Grafana удобно: фильтр по timestamp до/после. Если новый MCP дал:
- −20–50% tool calls на специфичной задаче (callers/callees для codegraph) — отлично
- −5% всего — пограничный
- 0% или +x% — overhead, отказаться

Не верь маркетинговым цифрам в README инструмента. Замеряй на своём кодбейзе.

---

## Troubleshooting

### Метрики не идут в Grafana

```bash
# Проверить, что переменная действительно установлена в shell CC
env | grep -i otel
env | grep -i claude

# Если CC запускается из GUI (VS Code) — переменные из .zshrc могут не подхватиться.
# Установить через GUI settings или ~/.config/claude/.env
```

### Docker compose жалуется на занятые порты

```bash
# Найти кто держит порт 3000
lsof -i :3000          # macOS / Linux
netstat -ano | findstr :3000   # Windows

# Поменять mapping в docker-compose.yml на свободный порт
```

### Grafana пустая после первой сессии

Подождать 30–60 секунд (Prometheus scrape interval). Если ничего — проверить логи collector'а:

```bash
docker compose logs otel-collector | tail -30
```

---

## Безопасность

- Все три слоя — **локальные**. Никакие данные не уходят на сторонние сервисы.
- OTel collector слушает только `localhost` (по дефолту claude-code-otel).
- Промпты и ответы в логи **не** попадают — только агрегаты (tokens, tool names, durations). См. native CC privacy docs.

Если включить отправку в SaaS (Datadog/Honeycomb/SigNoz) — внимательно проверь конфиг exporter'а на предмет того, что **именно** уходит.

---

## Когда снести

- Шум превышает пользу — например, ты смотришь дашборд один раз в месяц.
- Память Docker мешает на ноутбуке.
- Перешёл на менее требовательную замену (ccusage statusline сам по себе).

Снос:

```bash
cd claude-code-otel && docker compose down -v
unset CLAUDE_CODE_ENABLE_TELEMETRY
npm uninstall -g ccusage ccstatusline claude-usage-monitor
```
