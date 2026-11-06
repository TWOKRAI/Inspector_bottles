# Ревью ветки · C-30 `fix/recipe-save-noise` · частичная волна · 2026-11-06

Ревьюер: reviewer (Opus), сессия гейта inspector-bottles-28. Дифф `bd5067dc2..45c8467c2`, 93 файла. Текст сохранён координатором с отчёта ревьюера (у роли нет Write).

## Вердикт: APPROVED (частичная волна в main)
Блокеров и major нет, три minor — чинить после слияния. Два дефекта существовали до ветки (D1, D2) — в реестр, слияние не блокируют.

## Проверено запуском
- Save (1.13/1.14/1.14b): 4 файла `recipes/tests/test_save_*` — 32 passed. Камера (1.10): 3 файла — 33 passed.
- ruff на изменённых `.py` — exit 0; `sentrux check .` — 43 правила, всё зелёное; secrets_audit — чисто.
- Проба по 22 рецептам: дисплей update→persist→update + Save редактора с `foundation={"devices"}` — `+0/-0` везде, конфликтов нет.
- Camera Save: плоские `params` в файле, `brightness=130` → в бэкенд доходит `{brightness: 130, contrast: 40}`, `contrast` не потерян.
- Порядок RecipeConflict/rev: сверка `expected_rev` сразу после `read_canonical`, раньше проверки ссылок; авторитетная сверка под локом в `save_raw`.
- Проводка `app.py`: `TopologySession` создаётся до `AppServicesDeps`; `reset()` не трогает базу и `foundation`.

## Если сбой слияния base при старте (путь `_save_active_topology`)
| Случай | bridge_synth | webcam_sketch |
|---|---|---|
| A: проводка цела | +0/-0 | +0/-0 |
| B: не прочитались имена фундамента | +14/-0 (в файл попал `devices`) | +10/-12 |
| C: не прочиталась сборка (база не захвачена) | +1/-21, `processes=[]` | +3/-371, `processes=[]` |
Случай C — свойство 1.8, уже в main (D2). Camera Save в этом случае защищён (`save()` → False, файл не тронут).

## Находки
- **m1 (minor, 1.10×1.13):** при висячей привязке дисплея `ghost` Camera Save даёт `False`, `last_error=''`, статус «нет активного рецепта или изменений» — причина отказа неверная. Фикс: ловить `RecipeValidationError` и писать текст в `last_error` (`camera/presenter.py:162-167`, `section.py:76-80`).
- **m2 (minor):** `_merge_camera_params` (`camera/presenter.py:175`) без живых вызывающих. Не удалять (принцип 3), добавить в докстринг FREEZE с 1.10 и скрытый дефект (CTO Q2).
- **m3 (minor, тесты):** `test_callers_pass_session_foundation` (`pipeline/tests/test_save_conflict_rev.py:632`) проверяет kwarg шпионом; добавить по тесту на вызывающего с ожиданием `+0/-0` на `bridge_synth`.

## Переносится дальше
M4 ревью 1.10 (Camera Save гасит `layout_unsaved`); роль viewer нажимает «Сохранить» камеры и пишет рецепт (подозрение, не блокер); `unregister` дисплея с привязками → «перезагрузите» (2.0); замеры M1–M3 на стенде не выполнены; статус плана DRAFT, «Plan review: CHANGES 4» — блок финального merge, не частичной волны.

## Дефекты до ветки
- **D1:** галочка дисплея вкл→выкл→вкл пишет умолчание `enabled: true` (12 из 22 рецептов, +1…+3 строки); противоречит цели 7 плана.
- **D2:** сбой фрагмента base при старте → любой явный Save пишет пустой граф (`processes=[]`). Простой фикс: Save отказывает при пустом графе без захваченной базы.

## Не проверил / ненадёжно
Живой GUI и стенд не запускались (M1–M3, hot-apply `replace_blueprint`, откат PM); общий прогон domain/displays/pipeline/frontend — по данным лида (3753 passed, 1 известный красный); пробы на двойниках `FakeTopologyRepository`/`FakeEventBus`, одиночные прогоны; многокамерные рецепты и `RecipeApplyHandler` не проверялись.
