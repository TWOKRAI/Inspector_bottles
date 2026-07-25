---
name: feedback-tests-invisible-to-testpaths
description: Каталог tests/ на диске, но не в testpaths — 58 зелёных тестов не гонялись; покрытие сверять с конфигом прогона, а не со списком файлов
metadata:
  type: feedback
---

Ф8 H.1 (2026-07-26): три каталога тестов фреймворка — `telemetry_readmodel_module/tests`,
`config_module/tools/tests`, `frontend_module/actions/handlers/tests` — существовали, были
зелёными (58 тестов) и **не гонялись ни разу**: их не было в `testpaths` файла
`modules/pytest.ini`. Прогон показывал 5361 passed и выглядел исчерпывающим.

**Why:** тест-невидимка хуже отсутствующего — он создаёт ложное чувство покрытия. Модуль
с тестами на диске читается как «покрыт», хотя его регрессы не ловятся. Это тот же класс,
что [[feedback-swallowed-failure-class]]: следствие есть, сигнала нет. Пополнение testpaths
— ручной шаг при заведении модуля, и он молча пропускается.

**How to apply:** судить покрытие по **конфигу прогона**, а не по наличию файлов. Быстрая
проверка: сопоставить `find . -type d -name tests` с секцией `testpaths`. В этом проекте
инвариант закреплён тестом `multiprocess_framework/modules/tests/test_module_tiers.py`
(`test_every_test_dir_is_collected`) — новый каталог мимо testpaths падает красным. При
переносе подхода в другой репозиторий заводить такой же страж, а не полагаться на дисциплину.
Смежное: [[feedback-plausible-is-not-verified]], [[feedback-check-red-on-main-first]].
