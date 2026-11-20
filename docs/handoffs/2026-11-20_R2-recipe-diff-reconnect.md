# Дифф рецептов: `max_reconnect_attempts: 0` у `robot_main` и `vfd_belt` (полоса Р2, 2026-11-20)

Решение владельца 2026-11-20: лимит переподключения снят, нового кода нет (`Services/device_hub/drivers/base.py:108,285`). Рецепты правят владельцы: сим — Пульт, β — К. Я их не трогаю. Дифф построен на копиях рецептов с `main` `a53d5a61b`; `git apply --check` в чистом дереве прошёл (rc 0). Окончания строк — LF, как в файлах.

Ключ добавлен последним в `params` записей, а не после вложенного `robot_params` — чтобы не попасть внутрь вложенной карты. Две строки на рецепт, четыре всего.

## `multiprocess_prototype/recipes/letter_robot_sim.yaml` — владелец Пульт

```diff
@@ -81,6 +81,7 @@ devices:
       word_order: little
       feed_poll_s: 0.05
       telemetry_interval_s: 0.5
+      max_reconnect_attempts: 0  # без лимита: хаб сам переподключается (решение владельца 2026-11-20)
       robot_params:
         P_ZONE_MAX: 6000
   - id: vfd_belt
@@ -95,6 +96,7 @@ devices:
       default_freq_hz: 10.0
       poll_interval_s: 0.5
       stale_polls_limit: 6
+      max_reconnect_attempts: 0  # без лимита: хаб сам переподключается (решение владельца 2026-11-20)
 blueprint:
   processes:
     - process_name: gui
```

## `multiprocess_prototype/recipes/hikvision_letter_robot.yaml` (β) — владелец К

```diff
@@ -65,6 +65,7 @@ devices:
       word_order: little
       feed_poll_s: 0.05
       telemetry_interval_s: 0.5
+      max_reconnect_attempts: 0  # без лимита: хаб сам переподключается (решение владельца 2026-11-20)
   - id: vfd_belt
     name: ПЧ лента
     kind: vfd
@@ -77,6 +78,7 @@ devices:
       default_freq_hz: 10.0
       poll_interval_s: 0.5
       stale_polls_limit: 6
+      max_reconnect_attempts: 0  # без лимита: хаб сам переподключается (решение владельца 2026-11-20)
 blueprint:
   name: default
   description: ''
```

В β у `robot_main` стоит v1-драйвер `delta_universal3`: он тоже зовёт `_note_reconnect_failed` из базы (`robot_driver.py:556`), поэтому ключ действует и там. Остальное в β (старая камера, `use_linear: true`) — не трогать, это R4.

## Что проверить после применения

1. `ready` ≤ 3 × heartbeat + 1 с (16 с при heartbeat 5 с) **после включения робота** — критерий ACCEPTANCE 2.2 в `plans/2026-10-27_system-run-state/tasks/2.2.md` (формулировка исправлена в этой же ветке).
2. Закрытый порт: число строк лога хаба в минуту. Без лимита хаб ходит на порт раз в `RECONNECT_THROTTLE_S` (`base.py:71`, 2 с) — измерить, не оценивать (причина лимита — спам, `base.py:104-107`).
3. Рецепты с другим `id` робота и ПЧ, не перечисленные здесь, дифф не покрывает; список рецептов 1.0 даёт владелец.

## Что осталось открытым / ненадёжно

- Дифф проверен `git apply --check` на дереве, но рецепты с ним не загружались и стенд не гонялся.
- Схема валидации записи `devices:` в рецепте по коду не найдена (`extract_recipe_devices` отдаёт элементы как есть), запрета на ключ нет; прогон загрузки рецепта не делал.
- Доказательство, что `params` доходят до драйвера, — раздел ниже; граница доказательства там же.

## Доказательство: `params` рецепта доходят до драйвера (тест на симе, 2026-11-20)

Одноразовый тест через настоящий `DeviceHubPlugin.start()` с двумя записями, зеркальными `letter_robot_sim.yaml:71-95`; текст — `docs/handoffs/2026-11-20_R2-params-path-test.py.txt` (в `.txt`, в сборку тестов не входит). Прогон на `main` `a53d5a61b`, через `machine_gate.sh medium`:

| Проверка | Результат |
|---|---|
| T1: ключ `0` → `RobotDriverV2` и `VfdDriver` | `max_reconnect_attempts == 0` (и в записи реестра) |
| T1 контроль: без ключа | `== 3` у обоих |
| T2: лимит `0`, закрытый порт, 5 тиков | 5 реальных попыток, `reconnect_exhausted False`, `desired_connected True` |
| T2 контроль: умолчание 3 | ровно 3 попытки, затем `reconnect_exhausted True`, `desired_connected False` |
| T3: sim поднят после ожидания | драйвер сам вернулся в `connected` за **2,51 с** после подъёма sim, без ручного «Подключить» |
| Прогон | T1+T2 — 4 passed за 0,68 с; T3 — 1 passed за 10,06 с; все 5 вместе — 5 passed, 10,41 с |
| Break-injection (`base.py:108` читает `"max_reconnect_attempt"`) | предсказано: красны T1 с ключом, T2 с `0`, T3; получено: ровно эти три |

Границы: записи поданы в конфиг хаба вручную — звено `devices_sync` и загрузка YAML не прогонялись; тики зовёт тест, а не воркер плагина (тик 0,2 с вместо 0,5 с); 2,51 с — одно измерение: включает остаток throttle 2,0 с, `connect` и `sync_params`, на железе другое; ПЧ проверен только на значение лимита, поведение лимита — только у робота (мост ПЧ при закрытом носителе уходит в `DeviceHubError` до `connect`); счётчик попыток — приватное поле `_stats["reconnects"]`.
