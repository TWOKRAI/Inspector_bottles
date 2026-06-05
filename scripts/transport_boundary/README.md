# transport_boundary

Архитектурный инвариант плана **transport-router-hub** (P4.3): прямой queue/SHM-транспорт
разрешён **только внутри хаба**. Stdlib-only (AST), Python 3.12+.

Единственный способ отправки сообщения между компонентами — `router.send(message)`.
Прямые низкоуровневые вызовы транспорта (`queue_registry.send_to_queue`,
`broadcast_message`, инстанцирование SHM-примитивов) обходят хаб и запрещены везде,
кроме слоя-хаба и транспортной библиотеки.

## Зачем отдельный чекер (а не sentrux)

sentrux-правила — это **import-boundaries** между путями (`from`→`to`). Они физически
не ловят этот инвариант: транспорт зовут через атрибут
`router_manager.queue_registry.send_to_queue(...)` — **без импорта** имени. Поэтому нужен
**call-site**-детектор по AST (имя вызываемого символа), а не граф импортов.

## Быстрый старт

```bash
# Сканировать все слои с дефолтным конфигом
python scripts/transport_boundary/transport_boundary.py

# Один корень
python scripts/transport_boundary/transport_boundary.py --root multiprocess_framework

# JSON для CI
python scripts/transport_boundary/transport_boundary.py --format json

# Только отчёт, без падения
python scripts/transport_boundary/transport_boundary.py --no-strict
```

Включён в `scripts/ci.py` как gate-шаг «Транспортный инвариант (router.send)».

## Exit-коды

| Код | Когда |
|-----|-------|
| `0` | Новых нарушений нет (известные долги `[[debt]]` допускаются) |
| `1` | Есть вызов вне `allow`/`debt` (в `--no-strict` → 0) |
| `2` | Ошибка конфига / ни одного файла не просканировано / пустой `forbidden_calls` |

Идеально для **pre-push** и CI: дефолт `strict=true` → push блокируется при новом обходе хаба.

## Ratchet-модель

На текущем коде живут известные обходы (broadcast B7), которые удаляются в **P5**
(см. [plan.md](../../plans/2026-05-31_transport-router-hub/plan.md),
[recon_p4.md](../../plans/2026-05-31_transport-router-hub/recon_p4.md)). Они перечислены
в секции `[[debt]]` конфига:

- печатаются как `KNOWN DEBT (P5)` — **видны**, но **не роняют** чекер;
- любой **новый** прямой вызов вне `allow`/`debt` → `exit 1`.

Так инвариант защищает от регресса уже сейчас, не требуя сначала вычистить легаси.
Добавлять запись в `[[debt]]` можно **только** со ссылкой на ADR/план — это не «глушилка»,
а ledger одобренного долга.

## Что детектируется

`[detect].forbidden_calls` (имена вызываемых символов, AST):

| Символ | Почему обход |
|--------|--------------|
| `send_to_queue` | прямая адресная доставка в очередь мимо `router.send` |
| `broadcast_message` | широковещание мимо хаба (queue_registry) |
| `RingBufferWriter` / `RingBufferReader` | прямой SHM вне Claim Check хаба |
| `MemoryHandle` | прямой доступ к SHM-сегменту вне middleware |

Матчатся **вызовы** (`ast.Call`), не определения и не импорты: `def broadcast_message`
и `from ... import RingBufferWriter` чекер не трогает.

## Allowlist («внутри хаба»)

```toml
[allow]
paths = [
    "multiprocess_framework/modules/router_module/**",          # хаб + frame-middleware
    "multiprocess_framework/modules/shared_resources_module/**", # сама библиотека очередей/SHM
]
```

Здесь прямой транспорт легитимен — это и есть реализация хаба и нижнего хранилища.

## Inline-suppression

```python
qr.send_to_queue(...)  # transport-boundary: ignore
```

Действует **только для этой строки**. Использовать точечно, с обоснованием рядом.

## Что настраивается

| Секция | Что |
|--------|-----|
| `[scan].roots` | Корни сканирования (слои проекта) |
| `[exclude]` | `dirs` (имена), `path_patterns` (relpath-глобы; тесты/docs/архив) |
| `[detect].forbidden_calls` | Имена транспортных символов |
| `[allow].paths` | Глобы путей, где прямой транспорт разрешён |
| `[[debt]]` | `path` + `reason` — известные долги (ratchet) |
| `[output]` | `format` (table\|json), `strict` |

CLI-флаги (`--root`, `--format`, `--no-strict`) перекрывают конфиг.

## Ограничения

- **Детектор по имени символа.** `communication.broadcast_message()` (публичный API)
  и `queue_registry.broadcast_message()` (обход) неразличимы по имени — оба матчатся.
  Это сознательный компромисс: оба — часть одной broadcast-машинерии, деферятся вместе.
- **Не сканирует git-историю** — только текущий tree.
- **Tests/docs исключены** — там прямой транспорт уместен (фикстуры/моки/примеры).
