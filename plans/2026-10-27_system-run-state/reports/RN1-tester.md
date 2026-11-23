# RN1 — отчёт слепого tester (стадия RED, до кода)

База: worktree detached на 536c60dee. Не коммичено, не `git add`. Прогон только через `machine_gate.sh light inspector-bottles-fr1-tester`. Запретные пути не читались. `interfaces.py` читать мне отказали в разрешениях (вне запретного списка), повторно не пробовал: для тестов хватило литералов брифа.

## Итог прогона трёх новых файлов: 31 failed, 1 passed (ruff чист)

| файл / тест | свойство / мутант | реальный результат |
|---|---|---|
| read_node: `test_node_dict_assembled_from_leaves_flat/_two_level`, `test_leaf_read_returns_value`, `test_leaf_with_none_value_is_found` | узел собирается; лист; None-лист найден (убивает откат на `get`, `is not None`) | FAIL: AttributeError, нет `read_node` |
| `test_leaf_ancestor_wins_over_descendants_inside_subtree`, `..._read_directly_returns_leaf`, `..._independent_of_write_order`, `test_leaf_at_node_path_wins_over_descendant_leaf` | лист-предок побеждает, порядконезависимо (мутант в) | FAIL: AttributeError. Предпосылки-assert по `snapshot` (смесь достижима) прошли, красный именно на `read_node` |
| `test_boundary_is_dot_not_prefix` | страж ядра: `snapshot("a.n")` без `a.n2.*` | PASS сразу (как и предсказано) |
| `test_boundary_read_node_dot_not_prefix` | то же через `read_node` (мутант е: срез `len(path)`) | FAIL: AttributeError |
| `test_missing_path_is_not_found`, `test_empty_path_is_not_found` | отсутствие / пустой путь | FAIL: AttributeError |
| `test_empty_path_cut_before_snapshot` | пустой путь до `snapshot` (мутант з): подкласс модели считает вызовы | FAIL: AttributeError |
| `test_read_node_makes_exactly_one_snapshot_call` | `calls == ["a.n"]` (DESIGN 2) | FAIL: AttributeError |
| `test_known_divergences_from_live_state_get_literals` | три литерала P3r | FAIL: AttributeError |
| `test_node_from_snapshot_*` (2), `test_assemble_leaves_*` (3) | чистые функции: фильтр startswith (мутант ж), лист-предок (в), порядок вставки | FAIL: ImportError (нет экспорта `node_from_snapshot`/`assemble_leaves`) |
| `test_race_under_external_lock` | один внешний Lock, читатель видит целые узлы | FAIL: читатель упал AttributeError (красный по методу, как заявлено в брифе) |
| `test_read_node_does_not_mutate_model[4 пути]` | чтение не меняет `write_seq`/снимок | FAIL: AttributeError |
| get_node: `test_get_node_returns_nested_dict_get_stays_leaf` (+ two_level, missing_default, found_none_not_default, empty_path_default) | мутанты (а) `get_node`=`get`, `is not None` вместо `found` | FAIL (5): AttributeError, нет `get_node` |
| io_debug: `test_replay_cached_renders_node_from_leaves_on_real_view_model` | настоящая VM; «обработка» в `_status` (мутанты а, б) | FAIL: AssertionError, `'обработка' in 'ожидание данных…'` (поведенческий красный, регресс П3 воспроизведён). Предпосылка `vm.get(_PATH) is None` прошла |
| `test_replay_cached_renders_input_and_output_from_node_leaves` | вход/выход отрисованы | FAIL: AssertionError, `'detections' in ''` |

Контроли ДО правки: `test_p3r_node_read.py`, `test_replay_live_parity.py`, `test_p3r_replay_await.py`, `test_await_condition.py`, `test_io_debug_section.py` — 76 passed (все зелёные).

## Находки по брифу
- Противоречие: литерал границы дан через `read_node("a.n")`, а REDS требует «зелёный сразу». Развёл на два теста: `test_boundary_is_dot_not_prefix` (через `snapshot`, зелёный) и `test_boundary_read_node_dot_not_prefix` (через `read_node`, красный).
- Литерал `a.n`=5 + poll `{"a.n.x":1}` (бриф) и порядок P3r (`a.n.x`, затем poll `a.n`=5) разные; покрыл оба порядка.
- Точная сигнатура `snapshot` в брифе не дана: `_CountingModel.snapshot(prefix="")` угадана по вызовам `snapshot("")` и `snapshot(path)` в существующих тестах.
- Ожидание «пустой путь» у VM (`get_node("", default=7) == 7`) прямо в брифе нет: выведено из пустого пути в `read_node`.

## Что я оставил открытым / ненадёжным
- ТРЕБУЕТ УТОЧНЕНИЯ БРИФА (мои дополнения сверх литералов, лид вправе удалить): `test_get_node_empty_path_returns_default`, `test_get_node_two_level_nested`, `test_read_node_does_not_mutate_model`, `test_replay_cached_renders_input_and_output_from_node_leaves` (подстроки «detections»/«overlay» взяты из `test_renders_only_active_path`, не из брифа), `test_read_node_makes_exactly_one_snapshot_call` (из DESIGN 2, не из литералов).
- Предсказания (г), (д) про делегат `backend_ctl/_node_read.py` слепо не покрыты: их несут контроли `test_red10`/`test_red7`, ничего своего не писал.
- Мутанты не прогонялись (кода нет): все мои «убивает мутанта» — предсказания, не доказательство. Красные по AttributeError/ImportError доказывают только отсутствие API, поведение проверится после реализации и инъекций.
- `test_race_under_external_lock` под одним внешним локом гонку не воспроизводит по построению; реальную гонку несёт `test_red7` (читатель в моём тесте без лока был бы красным при любой реализации, и я его не писал, как велит бриф).
- `test_read_node_does_not_mutate_model` и `test_known_divergences...` слабы против мутанта, который кэширует результат вне модели; сильнее не придумал без знания кода.
- `interfaces.py` не прочитан (отказ в разрешении): строку `read_node` в `ITelemetryReadModel` не проверяю.
