# Гейт: разрез двух god-файлов (C-107, C-109) — 2026-11-22

Полоса «Гейт», сессия inspector-bottles-21, ветка `test/sentrux-god-files`, код — `9dd89e86e`. Только перенос тестов: тела, имена и параметризация без изменений.
- **До:** `sentrux check .` — `✗ 1 violation(s)`: `test_recipe_1_0.py` fan-out 20 (25 тестов), `test_plugin_on_core.py` fan-out 18 (65 тестов).
- **После:** `sentrux check .` — `✓ All rules pass` (43 rules); fan-out каждого файла ≤ 12 (максимум у `core_rig.py`). Разность множеств имён `--collect-only` пуста, число 65 и 25.
- **Разрез:** камера — `test_plugin_on_core.py` 17 + `_contract` 39 + `_session` 9 + каркас `core_rig.py`; рецепты — `test_recipe_1_0.py` 7 + `_word_dispatch` 2 + `_belt_monitors` 16 + хелпер `recipe_pult_support.py`.
- **Прогон:** 8 файлов (с hazards и gate без правок) — 94 passed; ruff check и format чисты.
- **Break-injection:** 7 из 7 совпали с предсказаниями, записанными до прогона; общий хелпер (I7) ломает ровно 4 теста в двух файлах. Ревью: у reviewer ещё 11 собственных инъекций, красные до и после идентичны; AST-сравнение тел — 0 расхождений.
- **Ревью (sonnet, стадия 5):** APPROVED; блокирующих замечаний нет.

## Открыто
- `# ruff: noqa: F811` в `test_plugin_on_core.py` и `_session` действует на весь файл: дубль имени теста ruff там не поймает (сейчас дублей нет). Лечение — `make` в `conftest.py`, тогда править hazards-файл (не мой).
- `test_plugin_on_core_hazards.py` берёт `make`, `_feed`, `_res`, `RGB_24` через `test_plugin_on_core` (скрытая связь), не из `core_rig`.
- `plans/2026-10-18_camera-device-service/tasks/4.2a.md:81` ссылается на `test_plugin_on_core.py` как на весь набор: теперь 17 тестов из 65.
- Каталоги целиком, `scripts/validate.py` и полный гейт не гонялись; таймерные тесты (`produce_не_блокируется…`) не нагружались, прогон на macOS.
- Ветка `_pos` с отказом не покрыта ни одним тестом ни до, ни после (инъекция даёт 0 красных) — свойство исходника, не переноса.
