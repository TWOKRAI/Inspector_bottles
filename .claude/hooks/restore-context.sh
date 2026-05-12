#!/usr/bin/env bash
# PostCompact hook — восстанавливает критический контекст после сжатия
# Без этого Claude забывает ключевые правила в длинных сессиях

cat <<'CONTEXT'
## Restored context (PostCompact)
- **Layer imports:** framework → Services → Plugins → prototype (обратные запрещены)
- **Dict at Boundary:** между процессами только dict (to_dict/from_dict); Pydantic внутри
- **Commits:** Why: + Layer: trailers обязательны, иначе hook отклонит
- **Active prototype:** multiprocess_prototype/ — только сюда app-specific изменения
- **backup/:** multiprocess_prototype_backup/ — ЗАПРЕЩЕНО трогать
- **ADR sync:** после правок DECISIONS.md → python -m scripts.sync
- **Роутинг:** имя процесса (targets/send_message) ≠ канал Router (FieldRouting.channel)
- **GUI:** blockSignals перед программной правкой виджетов, setFlags осторожно (рекурсия)
CONTEXT
