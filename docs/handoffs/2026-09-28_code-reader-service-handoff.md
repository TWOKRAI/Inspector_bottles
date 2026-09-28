# Передача: code_reader — сервис считывателя ID3000 в прототипе (2026-09-28)

План: [`plans/qr-code-reader.md`](../../plans/qr-code-reader.md) (один файл, не многофазный — раскладку по фазам
план требует, но она не сделана). Ветка `feat/qr-code-reader`, слито в неё:
`3ed16096` (сервис + плагин + рецепт), `70283c20` (итоги Ф2/Ф3 в плане). Не пушилось.

## Цель владельца

Основное (трек A): считыватель работает **автономно с ПЛК**, наша система в цепочке не участвует.
Попутное (трек B, эта сессия): «пока камера в руках — внедрить в свою систему», наблюдать и
настраивать; канал камера → ПК может остаться насовсем. Просьба 2026-09-28 дословно по смыслу:
«чтобы в прототип камера могла передавать данные, сервис как полагается, как остальные».

## Сделано в этой сессии

| Что | Где | Итог |
|---|---|---|
| Source-плагин | `Services/code_reader/plugin/` | `code_reader`, category `source`, порт `code`; команды `start_sink`/`stop_sink`/`get_status`/`reset_stats`. Discovery уже сканирует `Services/` — реестр видит его рядом с `hikvision`/`phone_camera` |
| Телеметрия | `plugin/registers.py` | параметры приёма + readonly `last_code`, `last_status`, `sink_state`, `total_reads`, `no_reads`, `bad_reads`, `dropped`, `last_error` |
| Симулятор прибора | `tools/reader_sim.py` | подключается как `TCP Client`, шлёт коды в формате, снятом с железа; `--no-read-every`, `--selfcheck` |
| Рецепт-стенд | `multiprocess_prototype/recipes/qr_reader_demo.yaml` | нода `reader`, `wires`/`displays` пусты; 6 тестов в `recipes/tests/test_qr_reader_demo.py` |
| ADR | `Services/code_reader/DECISIONS.md` | CR-001 (сервис вместо каналов в плагине, без Protocol/фабрики), CR-002 (эксклюзивный bind), CR-003 (очередь вместо ожидания) |

**Живой прогон** (`BACKEND_CTL=1`, рецепт + симулятор): 20 срабатываний → `total_reads=16`,
`no_reads=4`, `dropped=0`, `pending=0`, история из 20 записей в порядке отправки; перезапуск
симулятора → 16 → 19, процесс не перезапускался. Тесты: 36 сервиса + 6 рецепта. `validate.py` чист.

**Дефект, найденный стендом.** Первый прогон дал ноль кодов при `sink_state=listening` и пустом
`last_error`: на 5000 висел забытый с сессии на железе `id3000_tcp_sink.py`, а `SO_REUSEADDR` на
Windows разрешает **двух** слушателей — bind проходил молча. Исправлено `SO_EXCLUSIVEADDRUSE`
(ADR-CR-002), тест на двойной bind падает при откате флага.

**Отменённые решения плана** (Task 2.2): каналы внутри плагина, `Protocol CodeReaderBackend` +
`create_backend(kind)`, `sim_server.py` с режимом `triggered`, команда `trigger`. Причины — в
ADR-CR-001; в плане это отмечено в шапке Ф2, исходная постановка сохранена ниже неё.

## Начинать отсюда

1. **Независимый `tester` + `reviewer` по Ф2** — не запускались, задача по правилам проекта
   считается непроверенной. Тестировщику: worktree на `490cec04` (коммит до реализации), запретить
   `Services/code_reader/plugin/**`, `Services/code_reader/tests/**`, `Services/code_reader/core/sink.py`.
   Приёмочные критерии — Task 2.1/2.3 плана, но с поправкой: `sim`/`tcp` backend'ов и `trigger` нет.
2. **Ф3: плагин `code_view`** (Task 3.1) + замер задержки «срабатывание → код на экране» (Task 3.3).
   Сейчас код видно только зондом и в инспекторе; потребителя в рецепте нет, мерить нечем.
3. **Живая камера через рецепт** (Ф4, Task 4.1): в IDMVS указать `TCP Dst Addr` = IP этого ПК,
   `TCP Dst Port` = 5000 и прогнать `qr_reader_demo` на настоящем приборе. Плагин **ни разу не
   видел железо** — все 20 срабатываний живого прогона от симулятора.
4. **Трек A (основной, не начат)**: Ф0 — снять из IDMVS `ModBus Mode` и фактические
   Space/Offset/Size (два мануала расходятся), версию железа 2.0/3.0 (от неё вся схема с ПЛК; до
   ответа I/O не подключать). Ф1 — доказать автономию на столе.

## Что в этой работе ненадёжно

- Плагин не видел прибор; тайминги, `NoRead` от железа и потеря линка не проверены.
- `Output Result Buffer` (досылка накопленного прибором после обрыва) не проверялся и симулятором
  не изображается.
- `dropped` проверен синтетически (вызов `_on_result` в цикле), не на живом приёме.
- Статус `BAD_CODE` реализован по смыслу названий параметров прибора; на железе различение не снято.
- GUI **глазами не смотрел** — только зонд `backend_ctl` (`introspect_registers`, `state_get_subtree`).
- Красный тест **не мой**: `multiprocess_prototype/backend/tests/test_hot_rebuild_provenance_acceptance.py::test_hot_rebuild_framework_layer_key_count_is_pinned`
  — 38 framework-ключей против зафиксированных 37; `system.yaml` и тест не тронуты, ключ пришёл с
  `88dc5b85`. Решение (поднять константу и объяснить) — отдельной задачей.
- Забытый зонд `id3000_tcp_sink.py --port 5000` (PID 23448) снят в этой сессии. Если запускается
  снова — он конфликтует с рецептом за порт, теперь громко (`WinError 10048`).

## Команды

```bash
python multiprocess_prototype/run.py qr_reader_demo          # ВНИМАНИЕ: перезаписывает pipeline в app.yaml
python Services/code_reader/tools/reader_sim.py --port 5000 --interval 1.0 --no-read-every 5
python -m pytest Services/code_reader/tests multiprocess_prototype/recipes/tests -q
```

Запуск рецепта по имени пишет `pipeline:` в `multiprocess_prototype/app.yaml` (и переформатирует
список `base:`) — после прогона вернуть файл на место (`git checkout -- multiprocess_prototype/app.yaml`).
