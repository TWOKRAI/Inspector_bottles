---
name: Services vs Plugins distinction
description: User's architectural vision — Services are large external integrations (SDK, own process), Plugins are small processing units or bridges
type: project
originSessionId: 055294d4-05c9-45fb-bfe0-e822fa1bedc1
---
**Services** = большие внешние интеграции с собственным SDK/backend/процессом:
- Hikvision camera module (SDK)
- Database (PostgreSQL, SQLite)
- Telegram bot, Django
- Robot control (hardware)
- Neural networks (YOLO, ONNX)

**Plugins** = мелкие единицы обработки или мосты:
- Image processing (color_mask, grayscale, flip, resize...)
- Bridges между сервисами и программой
- Общение с менеджерами (logger_manager, router_manager)

**Why:** Сервис отличается от плагина тем, что у него может быть свой SDK, отдельный процесс, большой backend. Плагин — это мост между сервисом и программой, или самостоятельная мелкая обработка.

**How to apply:** В GUI два отдельных таба: Services (CRUD для тяжёлых интеграций) и Plugins (лёгкие обработки + мосты). В topology оба используют plugin-архитектуру v2, но UI разделяет по весу/сложности.
