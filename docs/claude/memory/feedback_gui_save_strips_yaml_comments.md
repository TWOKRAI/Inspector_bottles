---
name: feedback_gui_save_strips_yaml_comments
description: GUI Settings-Save round-trips system.yaml через yaml.safe_dump(model_dump) → сносит ВСЕ комментарии; не коммитить system.yaml после запуска прототипа не глядя
metadata:
  type: feedback
---

Вкладка «Настройки → Система» сохраняет `multiprocess_prototype/backend/config/system.yaml`
через `save_settings` → `yaml.safe_dump(cfg.model_dump(), sort_keys=False)`
([`settings/yaml_io.py`](../../../multiprocess_prototype/frontend/widgets/tabs/settings/yaml_io.py)).
Это полный round-trip: **все комментарии-документация в файле стираются**, поля
приводятся к каноничному дампу (в т.ч. могут «всплыть» дефолты схемы, напр.
`backend_ctl.enabled` перезаписывается текущим значением).

**Why:** запуск прототипа во время разработки + Save в GUI молча переписывает
закоммиченный `system.yaml`, теряя документацию и потенциально флипая дефолты
dev-инструментов. Легко закоммитить как «изменение» то, что на деле cruft.

**How to apply:** после запуска приложения ВСЕГДА смотреть `git diff` на
`system.yaml` перед add; если видно снос комментариев — `git restore` этот файл,
осознанные дельты вносить руками в комментированный файл. Настоящий фикс (не сделан):
перевести `save_settings` на comment-preserving дамп (ruamel.yaml) или писать только
изменённые ключи. Связано с [[project_live_findings_webcam_2026_07]] (config врёт про
log_level) — общая тема «правда конфига».
