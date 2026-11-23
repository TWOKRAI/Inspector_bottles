# Task 1.4m — ревью стадии 5 (reviewer sonnet `aa9c697de7a224e0c`, 2026-11-09)

Сохранён лидом по тексту отчёта ревьюера (у ревьюера нет Write). Ветка `feat/gui-close-1.4m`, реализация `f1f904d6e`, слепые тесты `5cc95c67e`.

**Вердикт: APPROVED.** Блокеров и major нет, 4 minor.

## Что ревьюер запускал (worktree `op-1.4m`, только чтение)

| Проверка | Результат |
|---|---|
| light: `config/tests` + `test_launch_pre_stop.py` + `test_build_characterization.py` | 36 passed |
| medium: `test_hot_rebuild_parity_acceptance.py` + `_hazards.py` | 19 passed |
| `backend/state/tests/test_integration.py` целиком | 19 passed, 1 failed: `TestGenericProcessApp::test_shutdown_cleans_proxy` — красный и на чистом `main` (`62d904246`), к 1.4m не относится; гипотеза причины (не доказана): тест патчит `__mro__[2]`, `shutdown` не определён в `GenericProcess` |
| `sentrux check .` на `git archive f1f904d6e` | 43 правила, All rules pass |
| `ruff check`, `ruff format --check` | чисто |
| `save_settings` round-trip | равен, шаг сохранён |

## Подтверждено

DESIGN выполнен: `ShutdownSection` (`list[Any]`, `default_factory`, `None → []`), ключ `pre_stop` в `launch.py:757` с `deepcopy`, безусловный; единственное место сборки `orchestrator_config` в прототипе; `timeout_s: 35` числом; снимки — ровно `+8 pre_stop` и `+10 sys_config.shutdown`; framework не тронут; слои чисты. L1c доказывает, что настоящий ответ `devices` дошёл до PM (R2: INFO 16:44:37,131 → `devices/busy.log` 16:44:37,143 → WARNING «ошибка ответа» 16:44:37,146). `outcomes devices: null` — при force и при `pre_stop: []` тоже, значит не от 1.4m; согласуется с пределом ADR-PMM-042, но не доказано.

## Находки

- **M1 (minor, текст/README).** DESIGN: «`pre_stop: "x"` проходит в PM, который пишет ERROR» — неверно. `"x"` и словарь вместо списка → `ValidationError` при загрузке (`list[Any]`). Проходят `[1]` и записи с плохим `timeout_s`. Правка — текст DESIGN и строка README.
- **M2 (minor, README и комментарий `system.yaml`).** «шаг тихо пропадёт с ERROR» — внутреннее противоречие; INFO `pre_stop: шагов N` пишется только при graceful-стопе, не на старте — это не сказано.
- **M3 (minor, тесты).** Свойство «негодную запись проверяет PM, а не загрузка» ни одним тестом не закреплено: замена `list[Any]` на `list[dict[str, str]]` оставляет все 8 тестов зелёными. Предложен тест: загрузка `[1, {"process": "devices"}, {…, "timeout_s": "35"}]` не падает, записи не изменены, `parse_pre_stop` даёт `steps == []` и 3 ошибки. Пишет автор (новый файл), слепой набор не правится.
- **M4 (minor, текст).** ACCEPTANCE противоречит себе («с v1-симулятором и без» и «прогон с симулятором убран»); оценка «фаза детей 5 с и больше» неверна для `robot_demo` (фактически 0,33–0,53 с).

## Слабости ячеек (чтение, не инъекции)

reds1 — слабость непроверяема (pydantic копирует изменяемые умолчания), I2 = 0 красных честно. reds5 — без предусловия «база непустая» (закрыто reds6). reds4c+4a вместе закрывают слабость 4в. Между `launch.py` и `PM.get_config("pre_stop")` нет теста на настоящих объектах (`spawner.py:95-96`) — доказано только живьём (advisory).

## Что ревьюер оставил открытым

Матрица инъекций не доделана (прогнан только I1); причина красного `test_shutdown_cleans_proxy` и «предел или дефект» для `outcomes devices: null` не установлены; строка про `observability.documents` в README опирается на воспроизведение ревьюера стадии 0; L1b/L4 на macOS не проверены; `validate.py` не запускался.
