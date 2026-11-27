# H1: ревью стадии 5 по SHA — `d89637973` и `989c669e5`

Дата: 2026-11-26. Проверял reviewer (sonnet), записал лид полосы К по итоговому сообщению ревьюера.

| SHA | Что | Вердикт |
|---|---|---|
| `d89637973` | `reconnect` в рецепте букв | **APPROVED** |
| `989c669e5` | `plate_source` в quad | **CHANGES REQUESTED** (итерация 1): правка верна, сторожа нет |

Quad — тестовый рецепт (2.0): замечание по нему 1.0 не держит.

## Как проверяли

Отдельное дерево `k-h1-rev`, HEAD `fab596efa`; `git diff <sha> HEAD` по проверяемым файлам пуст для обоих SHA.
Прогоны через `machine_gate light`, пропусков гейта нет.

База: тест reconnect, `test_build_characterization`, `test_letter_robot_sim_diff`, `test_hikvision_id3013_quad_recipe`,
`test_no_signal_plate` — 62 passed; набор quad (13 файлов) — 612 passed; прочие потребители рецепта букв — 142 passed.

## `d89637973` — APPROVED

Значения согласованы с ADR-CAM-008 (`Services/camera_device/DECISIONS.md:430-467`): `reconnect: true`,
`link_silence_s: 3.0` (75 периодов кадра при 25 fps), интервал по умолчанию 2.0.

Break-injection в рецепт; предсказано ровно 3 красных в каждой
(`test_letter_robot_camera_reconnects_after_silence`, `test_build_matches_snapshot[hikvision_letter_robot]`,
`test_operator_word_in_recipe_does_not_change_snapshot`):

| Инъекция | Получено | Ассерт теста reconnect |
|---|---|---|
| убрать `reconnect: true` | 3 failed, 4 passed | `assert False is True` |
| убрать `link_silence_s: 3.0` | 3 failed, 4 passed | `assert 0.0 == 3.0` |
| `link_silence_s: 30.0` | 3 failed, 4 passed | `assert 30.0 == 3.0` |
| добавить `reconnect_interval_s: 30.0` | 3 failed, 4 passed | `assert 30.0 == 2.0` |

На самом SHA снимок сборки был красным (и на родителе тоже); `e1d0f7285` это закрыл. Действий не нужно.

## `989c669e5` — CHANGES REQUESTED

Правка верна: `build_plate_sources` до неё давал `draw_1.overlay_draw` без номера и адреса, после —
`reader_1.code_reader_sdk`, `id3013-sdk-1`, `192.168.1.10` (для `reader_2` так же). Экраны камер не затронуты.

**Находка 1 (tests, major).** Строки `plate_source` (`hikvision_id3013_quad.yaml:345,361`) не сторожит ни один тест.
Предсказано 0 красных, получено:

| Вход | Прогон | Что видит `build_plate_sources` |
|---|---|---|
| убрать обе строки | 612 passed | source `draw_N.overlay_draw`, номер и адрес `None` |
| поменять считыватели местами | 612 passed | на экране reader_1 номер `id3013-sdk-2` и адрес `.11` |
| `reader_1.code_reader`, `reader_9.code_reader_sdk` | 612 passed | номер и адрес `None` |

Правка — отдельной задачей (H1-fix): один тест в `test_hikvision_id3013_quad_recipe.py`.

**Находка 2 (для 2.0, правки не требует).** Узла `processes.<p>.state.plugins.<n>` у считывателя нет: он пишет
`processes.<p>.state.code_reader_sdk` (`Services/code_reader/plugin/sdk_plugin.py:420`), у него нет `link` и `identity`,
плашка всегда пишет «нет кадров». Сегодня GUI дерево для плашки не читает (W2-c3 PENDING). При переезде считывателя на
общее ядро (задача 1.1) нужны узел `plugins.code_reader_sdk.{link,identity}` и тест.

## Что не проверено

- Живая камера: ложный `lost` при `link_silence_s 3.0` и переоткрытие после выдернутого кабеля не измерены (H6).
- Инъекция в код (`reconnect=self._reg.reconnect` в `plugin_base.py`) не делалась; какой тест сторожит проводку,
  не выяснено.
- Полный набор тестов не гонялся.
