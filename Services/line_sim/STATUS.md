# line_sim — статус

**Состояние:** каркас (Task 3.1 + 3.1a, план `plans/line-sim/phase-3-object-engine.md`).

| Часть | Статус |
|---|---|
| Контракт слоя/паспорта (`interfaces.py`) | готово |
| `LayeredObject` — выборка и рендер один раз | готово |
| `ScenePreset` — dict/YAML round-trip, валидация | готово (только слои) |
| `encoder_to_offset_mm` | готово |
| `SceneCompositor` | только Protocol — реализация Task 3.4 |
| Загрузка спрайта по строковому id, каталог `real_letters_disk` | Task 3.2 |
| Подключение к `SceneSourcePlugin` | Task 3.4 |

Тесты: `Services/line_sim/tests/` — `test_acceptance_3_1.py` (независимый tester), `test_hazards_3_1.py` (автор).
