# code_reader

Сервис промышленного считывателя кодов **Hikrobot ID3000** (наш экземпляр —
`MV-ID3013PM-06M-SENSOTEC`). Приём результатов чтения по TCP, разбор формата,
зонды для стенда и вся снятая с прибора конфигурация в одном месте.

---

## Назначение

Считыватель декодирует код сам и отдаёт строку наружу. Этот сервис отвечает за
сторону ПК:

- принять результаты по TCP (прибор работает как `TCP Client`, мы — сервер);
- разобрать пакет в типизированный `ReadResult` с внятным статусом;
- отличить «код прочитан» от «кода нет» и «код есть, но не читается»;
- отдать код в pipeline прототипа source-плагином `code_reader` (порт `code`);
- дать зонды для стенда: обнаружение прибора, сырой дамп потока, симулятор
  прибора, лист тестовых QR для подбора размера и дистанции.

Автономная работа с ПЛК (дискретные выходы, Modbus) идёт **мимо** этого
сервиса — там наша система в цепочке не участвует. Сервис описывает и её
настройку в `docs/SETUP.md`, потому что документ один на прибор.

---

## Структура

```
code_reader/
├── interfaces.py        публичный контракт — единственная точка входа извне
├── core/
│   ├── result.py        ReadResult, ReadStatus, parse_packet, split_stream
│   └── sink.py          ResultSink — TCP-сервер приёма
├── plugin/              source-плагин для прототипа (discovery видит Services/)
│   ├── plugin.py        CodeReaderPlugin — приём → produce() → порт code
│   ├── registers.py     параметры приёма + телеметрия для GUI
│   └── config.py        identity + register_bindings
├── tools/               зонды для стенда, запускаются вручную
│   ├── id3000_discover.py    обнаружение через GigE broadcast, версия прошивки
│   ├── id3000_tcp_sink.py    сырой дамп потока (текст + hex)
│   ├── reader_sim.py         симулятор прибора — прогон без железа
│   └── qr_test_sheet.py      лист тестовых QR с точной геометрией
├── docs/
│   └── SETUP.md         ★ все тонкости настройки, снятые с прибора
└── tests/
```

---

## Быстрый старт

### Найти прибор и узнать прошивку

```bash
.venv/Scripts/python.exe Services/code_reader/tools/id3000_discover.py
```

Работает без IDMVS и без `MvCodeReader` SDK — GigE-broadcast, подсеть угадывать
не нужно.

### Снять формат строки с прибора

```bash
.venv/Scripts/python.exe Services/code_reader/tools/id3000_tcp_sink.py --port 5000
```

Печатает каждый пакет текстом и в hex. Терминатор и обрамление видно только во
втором виде — в мануале их нет. Настройка прибора — `docs/SETUP.md`, раздел 4.

### Напечатать тестовые мишени

```bash
.venv/Scripts/python.exe Services/code_reader/tools/qr_test_sheet.py "QR" --sizes 10,15,20,30 --open
```

Каждый код несёт свой размер в содержимом, так что в History сразу видно, какой
габарит прочёлся. Печатать строго 100%, на листе есть контрольная линейка.

### Запустить в прототипе (рецепт `qr_reader_demo`)

```bash
python multiprocess_prototype/run.py qr_reader_demo
# во втором терминале — симулятор прибора, если железа нет:
python Services/code_reader/tools/reader_sim.py --port 5000 --interval 1.0
```

Нода `reader` поднимает приём на 5000, коды видны в инспекторе (`last_code`,
`total_reads`, `no_reads`, `sink_state`) и в дереве состояния
`processes.reader.state.code_reader`. Порт `code` привязывается к потребителю в
редакторе Pipeline. Команды ноды: `start_sink`, `stop_sink`, `get_status`,
`reset_stats`. Команды `trigger` нет: боевой триггер аппаратный (DI_0) и через ПК
не проходит.

### Принимать результаты в коде

```python
from Services.code_reader import ResultSink, ReadStatus

def on_result(result):
    if result.status is ReadStatus.OK:
        print("годен:", result.payload)
    else:
        print("брак:", result.status.value)

with ResultSink(on_result, port=5000) as sink:
    ...  # обработчик вызывается в потоке соединения
```

---

## Что важно знать до первого запуска

- **Формат результата снят с прибора, а не из мануала** — раздела «Set Result
  Format» в документации ID3000 нет. На нашем экземпляре это `QR-30MM;`,
  терминатор `;`, без CR/LF и STX/ETX.
- **TCP не сохраняет границ сообщений.** Резать поток по терминатору
  обязательно; этим занят `split_stream`, и `ResultSink` его использует.
- **Два вида неудачи различимы только если задать им разные тексты.** Завод
  ставит обоим `NoRead`, и тогда «код есть, но не читается» неотличим от «кода
  нет». См. `docs/SETUP.md`, раздел 5.
- **Один порт — один приёмник.** На Windows `SO_REUSEADDR` разрешает двум
  слушателям делить порт, и ядро отдаёт соединение одному из них: приём выглядит
  живым, а кодов нет. `ResultSink` ставит `SO_EXCLUSIVEADDRUSE`, поэтому занятый
  порт даёт понятную ошибку в `last_error`. Забытый `tools/id3000_tcp_sink.py`
  на том же порту — самая вероятная причина «прибор шлёт, а рецепт молчит».
- **Версия железа 2.0/3.0 не установлена** — до неё не подключать ни вход DI_0,
  ни выходы. Кнопка на корпусе прибора и TCP от неё не зависят.

---

## Связанное

- [`docs/SETUP.md`](docs/SETUP.md) — настройка прибора, все тонкости с пометкой
  источника: снято с железа / из мануала / предположение.
- [`docs/diagrams/wiring/id3013-wiring.html`](../../docs/diagrams/wiring/id3013-wiring.html) — монтажные схемы.
- [`plans/qr-code-reader.md`](../../plans/qr-code-reader.md) — план работ, карта регистров Modbus.
- `knowledge/raw/books/id3000-series-um-en-v401/` — официальный мануал (соседний
  проект obsidian).
