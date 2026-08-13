# plans/ — ledger

Единый индекс планов, чтобы сессия не перечитывала все файлы. `/dev:plan`
регистрирует новый план строкой в «Active»; `/dev:ship` переносит строку
в «Archived» при закрытии (archive-on-done).

Планы, созданные до появления ledger (2026-08-13), дозаполняются лениво —
при первом касании соответствующего плана.

## Active

| План | Тип | Статус | Остаток |
|------|-----|--------|---------|
| [line-sim](line-sim/plan.md) ([vision](line-sim/vision.md)) | feat | DRAFT | весь v1: Ф0 (коммит sim-monitor) → Ф1 vertical slice → Ф2 лента → Ф3 движок слоёв → Ф4 камера → Ф5 правда → Ф6 пульт (19 задач) |
| [telemetry-stage6](telemetry-stage6.md) | feat | IN PROGRESS | ведётся на ветке feat/telemetry-stage6 (вне этого ledger-коммита) |
| [observability-roadmap](observability-roadmap.md) | docs | GOVERNING | зонтичный трек C-1…C-10 |

## Archived

| План | Закрыт | Итог |
|------|--------|------|
| — | | |
