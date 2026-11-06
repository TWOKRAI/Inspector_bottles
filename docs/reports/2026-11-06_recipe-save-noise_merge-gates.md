# C-30 recipe-save-noise: слияние main в ветку и гейты (2026-11-06)
## Суть
В `fix/recipe-save-noise` слит `main` (`bd5067dc2`) командой `git merge main`, не rebase (решение координатора: хеши из планов и ревью не переписываются). Конфликтов нет. Слияние `45c8467c2`; ветка шла на 33 коммита впереди и 84 позади. `bridge_synth.yaml` не тронут. Окно `heavy` 60 мин взято и снято.
## Итог
Красных от ветки нет: четыре красных воспроизводятся на `main` так же. Три из них в реестре (C-13, C-26, C-74), один (domain, `stop_window_s`) в реестре не значится.
## Проверка (числа)
- `scripts/validate.py`: 2 FAIL (теги памяти, индекс BY-MODULE); на main те же 2.
- `multiprocess_prototype/backend/tests`: 298 passed, 46 с.
- Фреймворк `run_framework_tests.py`: 12687 passed, 2 failed, 46 skipped, 1 xfailed, 1605 с (26:44).
- Тронутые модули (adapters, domain, recipes, frontend целиком): 3753 passed, 1 failed, 13 skipped, 141 с. `Services/` ветвь не трогает: там не гоняли.
- Импорт из дерева ветки: `multiprocess_framework/__init__.py` лежит внутри worktree.
## Красные поимённо
| Тест | Реестр | Ветка одиночно | main одиночно (гейт) |
|---|---|---|---|
| `validate.py`: память (теги, BY-MODULE) | C-13 закрыт 2026-10-21, красный вернулся | FAIL | FAIL |
| `test_module_tiers::test_no_test_dir_is_invisible_to_every_runner` | C-74 открыт | 3 из 3 красный | 3 из 3 красный |
| `test_event_manager_exit::test_child_with_5000_unread_events_exits_within_2s` (2.016 с при сроке 2 с) | C-26 открыт | 3 из 3 зелёный | 3 из 3 зелёный |
| `domain/tests/test_entities_roundtrip.py::TestExtrasShorthandDriftGuard::test_every_pick_key_reaches_framework_from_domain` | нет | 3 из 3 красный | 3 из 3 красный |

C-74: все 510 «невидимых» каталогов лежат в `data/atlas/checkout/*` (`.gitignore`, локальные checkout атласа), а не в новом каталоге tests/, как в записи; каталогов из git среди них нет.
Domain: framework читает из extras ключ `stop_window_s`, домен его не доносит. Ключ ввёл T1.11 (`b1e695121`, 2026-10-27), он уже лежит в базе ветки; был ли тест красным до слияния, не проверялось.
## Открыто
- Внести в реестр красный domain; пометить, что красный памяти (C-13) вернулся; уточнить причину C-74.
- Полные логи: `docs/reports/_gate_framework.log`, `_gate_touched.log`, `_gate_backend.log` (под `*.log` в `.gitignore`, не закоммичены).
## Дальше
Решение о слиянии в main: координатор и владелец; записи в реестр вносит лид.
