# Передача координатора общей машины (2026-10-14, ~13:10)

Координатор — сессия `inspector-bottles-23`. Правила роли — skill `coordinator` (обновлён 6e74a47f3: классы
light / medium / medium timed / heavy, §2–§4). Состояние — `D:\PROJECT_INNOTECH\Inspector_vision\machine.lock`
и очередь владельца `plans/queue/ORDER.md`. Прошлая передача — `2026-10-13_coordinator.md`.

## machine.lock сейчас

```
coordinator: inspector-bottles-23 | since 2026-10-14 08:43
stand: free
```
Окон нет, заявок нет.

## Полосы (вкладка → имя → задача)

| Вкладка | Сессия | Полоса | Задача | Где стоит |
|---|---|---|---|---|
| «Полоса Р · T3.7 robot_host линии на v2» | `inspector-bottles-0f` | Р | robot-protocol-v2 T3.7 — **DONE**, влита dc209d6ec, передача 93e6c9513 | стенд 16:00: 3 буквы, jobs_failed 0; сессия ушла на /clear; следующая — T3.8 (промпт выдан) |
| «Полоса С · 6.3 экспорт обучения…» | `inspector-bottles-26` | С | layer-render 6.3 — **DONE**, влита 8499ae616, передача 83681ccd0 | сессия ушла на /clear; следующая полоса С — letters-retrain 0.4 (нужно окно стенда) |
| «Инструменты · skill и 1.2» | `inspector-bottles-05` | Инструменты | machine-gate-hook Task 1.2 — **DONE**, влита cd56fa535 | закрывается; передача docs/handoffs/2026-10-14_tooling-machine-gate-lock-1.2.md. Окна теперь можно выдавать `machine_gate.sh grant/close`, `status` показывает RAM/CPU |
| «Полоса Р · T3.8 вид робота из состояния линии» | `inspector-bottles-66` | Р | robot-protocol-v2 T3.8 | с ~16:15, стадии 0–1; позже timed robot_comm, heavy матрица, stand |
| «Полоса Р2 · T5.3 команды хаба робота» | `inspector-bottles-62` | Р2 | robot-protocol-v2 T5.3 | с ~16:50, стадия 0; стык с T3.8: `sim.robot.state` (линия) против `devices/robot_*` (хаб) — сообщён обеим |
| «Полоса Р2 · T5.2 RobotDataStore» | `inspector-bottles-89` | Р2 | robot-protocol-v2 T5.2 — **DONE**, влита a7b7c3c56 | матрица 20/20 (прогноз 19/20), итог robot_comm 1460 passed; передача task-T5.2-close-lead; сессия ушла на /clear; следующая — T5.3 (промпт выдан, условия выполнены) |

**Передать полосе С при открытии (от 66, T3.8, решение владельца):** полоса Р правит `apps/line_sim/pipeline.yaml` —
в плагин `robot_host` добавляются ключи `robot_state` (поза робота в `sim.robot.state`) и `robot_state_hz`; ещё README
`Plugins/sim/robot_host`. `Services/layer_render`, `plans/letters-retrain` полоса Р не трогает.

Приоритет при одновременных заявках: T3.7 (веха М1).

## Сделано 13–14 октября

| Что | SHA |
|---|---|
| line-sim 6.5 — ассеты стенда из фикстур, плитка 410x484 | f80419f5e |
| T5.1 RobotDriverV2 (потоки — в ALLOWLIST G6 до T5.3, решение владельца) | 337047255 |
| layer-render 6.2 LayerSceneGenerator | 91d595e6b, передача 87dd240dc |
| хук гейта 1.1 (classify, medium, --timed, хук PreToolUse) | f15ea6e04 |
| правила гейта в skill coordinator / project-rules / .claude/CLAUDE.md | 6e74a47f3 |
| память: теги уроков и BY-MODULE (validate на main зелёный) | 0f60d89e1, 0b983cb80 |
| skill coordinator: строка «ВКЛАДКА:» в промпте, ловушка старого имени | 07b878114 |
| план хука: ответы владельца, класс medium | b1fc4e458 |
| qex: полная переиндексация, 4 184 файла, 61 314 чанков, без data\ | 13.10, OPEN_QUESTIONS 5495844fc |

## Решения владельца 2026-10-14 (~14:40)

1. `b5` закрыта.
2. Слияние gate-lock 1.2 — разрешено; сливает `05` по сигналу координатора после окна `0f` (матрица T3.7 до ~15:35).
3. Передача T0.3 влита: d8effc842.
4. Урок lupa — дописан в `feedback_zero_observations_looks_like_a_result.md` (пятое обличье).
5. Уборка worktree: 14 влитых и чистых удалены с ветками (44 → 30). Второй ярус (с `--force`/`-D`) — на слове владельца.
6. serena в сессиях полос **не отключать** — при нехватке RAM просить закрыть лишние вкладки, не serena.

## Долги

- Gate 1.2: `grant … stand` не пишет строку `stand:`, `close` её не снимает — координатор дописывает/снимает её Write'ом
  (проверено 2026-10-14 15:31 и 16:00; `status` после ручной строки — rc 0). Задача на доделку — по слову владельца.

- T5.1: два сырых потока RobotDriverV2 (`robot_driver_v2.py:517`, `:605`) — переделать до T5.3.
- T0.3 Virtual Robot отложена; при возврате — первым делом повтор сухого прогона с `-rf` в тихое окно.

## Ловушки дня

- Переоткрытая из истории сессия получает новое имя и подписывается старым (за два дня: 51/a4, 5c/1c, d1/55, ec/f5,
  b5/84) — верить `from-name`, не подписи.
- Агент Explore не запускает pytest (роль); `junior` требует бриф по форме или `BRIEF-OVERRIDE: <причина>`.
- Свободная RAM — главный ограничитель окон: каждая вкладка Claude с serena ~1 ГБ; Chrome ~1 ГБ.

## Что оставил открытым / ненадёжным

- Перечитывает ли уже открытая сессия `settings.json` с хуком сразу — проверено только на новой сессии и субагенте (P1).
- Сухой прогон пробы 2/53 — причина не установлена.
