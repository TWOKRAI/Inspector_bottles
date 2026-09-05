# Plugins/io/otel_export — хост экспортёра OTLP

> **Стадия:** `contract` (Task 0.4 плана [`plans/otel-export.md`](../../../plans/otel-export.md)).
> Самого плагина (`plugin.py`) ещё нет — он приходит в Ф2.1. Сейчас здесь только дверь
> конфига и identity.

## Назначение

Хост для `Services/otel_export`: обычный плагин `ProcessModulePlugin` в `GenericProcessApp`,
как `telemetry_sink`, `capture`, `devices`. Он подписывается на хвост наблюдаемости, ставит
записям отметку приёма, отдаёт их сервису и считает счётчики.

Форма выбрана по прецеденту: в `Services/` нет ни одного подкласса `ProcessModule`, а все
прикладные процессы — это плагины в `GenericProcessApp`. Заводить ради экспортёра вторую
форму процесса значило бы плодить сущность.

## Что есть сейчас

| Файл | Что в нём |
|---|---|
| `registers.py` | `OtelExportRegisters` — подкласс `Services.otel_export.config.OtelExportConfig` с `@register_schema`. **Ни одного переобъявленного поля** |
| `config.py` | `OtelExportPluginConfig(PluginConfig)` — identity + `register_bindings` |

Состав полей, дефолты, валидация и `readback()` — в
[`Services/otel_export/README.md`](../../../Services/otel_export/README.md), раздел
`Public API`. Здесь их **нет намеренно**: два места объявления полей разъезжаются молча
(ADR-OTEL-003).

## Чего нет

`plugin.py` (Ф2.1), фрагмент топологии `backend/topology/otel_export.yaml` (Ф3.1), команды
`otel_export.status` / `otel_export.flush` (Ф2.1).

`plugin_class` в конфиге уже указывает на `Plugins.io.otel_export.plugin.OtelExportPlugin` —
это строка dotted-path, её резолвит `class_loader` при сборке топологии. Объявить раньше
реализации можно; **подключать фрагмент топологии до Ф2 нельзя** — процесс не поднимется.

## Границы

- Плагин знает `Services/otel_export` и `PluginContext`. Импорт `multiprocess_prototype.*`
  запрещён (ADR-120): плагин — словарь повторного использования между приложениями.
- Своего фильтра «записи не мои» не заводится, пока петля усиления не предъявлена красной:
  отказ подписки процесса на собственный хвост уже стоит во фреймворке
  (`ProcessModule.subscribe_observability_tail`). Задача Ф2.3 — **предъявить**, что он
  работает, а не поверить.
- Никаких `if sys.platform`.

## Ловушка, которую стоит прочитать до Ф2.1

`ctx.declare_metric` и `ctx.record_metric` — **разные плоскости**: первая объявляет уровень
дерева состояния и **отвергает точку в имени** (`ValueError`), вторая пишет счётчик в
плоскость stats и точечные имена принимает (`otel_export.received`). Дословный перенос
строки плана «счётчики через `declare_metric` + `record_metric`» с точечным именем уронит
плагин на старте. Разбор — в `Services/otel_export/README.md`, раздел `Counters`.
