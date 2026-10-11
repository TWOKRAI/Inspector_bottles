# Интеграция с ПЛК Delta (OPC UA / Modbus TCP): реальность и оценка

**Дата:** 2026-10-08
**Статус:** анализ. Код не писали, план в `plans/` не заведён.
**Зачем документ:** ответ руководству «можем ли и за сколько» и чтобы не повторять разведку.
**Метод:** чтение кода и планов репозитория плюс веб-разведка по Delta (сабагент `web-researcher`).
Ничего не запускалось. Сроки — оценка, а не замер.

## 1. Задача

С контроллера ПЛК по OPC читать параметры, показывать их в GUI на ПК, хранить в БД. Бонус:
сервер, отдающий HTML на телефон.

Ответы владельца на уточняющие вопросы (2026-10-08):

| Вопрос | Ответ |
|---|---|
| Какой ПЛК | Универсально, но пока под **Delta Electronics** (модель владелец ещё не назвал) |
| Число тегов | 30–50 |
| БД | На первое время SQLite достаточно |
| Телефон | Только локальная сеть |

**Уточнение 2026-10-09: ПЛК в проекте не будет.** Источник данных — панель DOP-103WQ (HMI Delta). Разделы про AS228
(4а) сохранены как справка, но актуален раздел 4б: клиент читает панель по Modbus TCP (панель — slave с Mapping Table).
Открытый вопрос: откуда сама панель берёт данные (какие устройства, по какому интерфейсу).

## 2. Что в репозитории уже есть

| Нужно | Что есть |
|---|---|
| Образец драйвера устройства | [`Services/modbus`](../../Services/modbus/STATUS.md): sdk → core → plugin, переподключение, опрос блоков, fake-клиент, тестовый slave |
| Реестр устройств, YAML-протоколы | [`Services/device_hub`](../../Services/device_hub/STATUS.md): процесс `devices`, драйвер `generic_modbus`, GUI-вкладки |
| Доставка значений в GUI | `state_store_module` (реактивное дерево, подписки), виджет `frontend_module/widgets/telemetry_chart.py` |
| Запись в БД | [`Plugins/io/telemetry_sink`](../../Plugins/io/telemetry_sink/README.md) → [`Services/sql`](../../Services/sql/STATUS.md): batch, fork-safe, `retention_days`; адаптер PostgreSQL в коде есть |
| HTTP для телефона | [`Services/phone_gateway`](../../Services/phone_gateway/STATUS.md): stdlib-сервер, IP, QR, тумблер в GUI, проверен вживую. Образец страницы с API — [`Plugins/sim/pult_web`](../../Plugins/sim/pult_web/README.md) |

## 3. Чего нет

1. **OPC UA-клиента.** `asyncua` не установлен. Это осознанно отложено в
   [`plans/storage-stack-embedded-first.md`](../../plans/storage-stack-embedded-first.md) («не делать, пока не названа
   конкретная платформа»). Триггер сработал: появился реальный ПЛК.
2. **Страницы-дашборда** тегов для телефона.
3. **GUI-вкладки** «Теги ПЛК»: таблица, качество сигнала, тренд, настройки подключения.
4. **Истории по тегам.** `telemetry_sink` пишет снимок state по таймеру; нужна своя таблица
   (тег, значение, качество, время) и запись по изменению.
5. **Защиты веб-сервера.** Сейчас всё на localhost. Для телефона нужен bind на LAN, режим «только чтение», токен.

Строка N-5 в [`plans/queue/backlog.md`](../../plans/queue/backlog.md) — это OPC UA **сервер** поверх state_store
(ПЛК читает нас). Наша задача — **клиент**. Это другая задача, она не запланирована.

## 4. Что известно про Delta (веб-разведка)

Официальные PDF Delta не открылись (403/редирект), поэтому часть фактов вторична. «Сниппет» — факт виден только
в выдаче поиска, страницу открыть не удалось.

| Линейка | OPC UA сервер | Источник / оговорка |
|---|---|---|
| **AX-8** | Да, встроенный: чтение/запись/просмотр, Basic256Sha256, пользователь+пароль. ПО — DIADesigner-AX (CODESYS) | [ethercat.org](https://ethercat.org/en/products/6EE56687A72E43DDB0E52D39D3471D79.htm), [engineering-update](https://engineering-update.co.uk/2021/02/25/flexibility-in-motion-with-the-new-delta-ax-8-series/), [DIAStudio FAQ](https://diastudio.deltaww.com/home/faq). Лицензия и версия прошивки — не подтверждены |
| **AX-3** | Да, встроенный. Нужен объект Symbol Configuration. Шифрованное соединение требует CODESYS-аддонов (Security Agent, Matrikon FLEX OPC UA Editor). Хранилище сертификатов: 32 доверенных / 32 издателей / 32 отклонённых. Аутентификация: логин+пароль или анонимно, по умолчанию `Administrator`. Проверка клиентом UaExpert: `opc.tcp://192.168.1.5` | Руководство AX-3 на [manualslib](https://www.manualslib.com/manual/2129521/Delta-Ax-3-Series.html), гл. 8, стр. 24, 294, 297, 300, 303, 304 |
| **AS300** (AS332T/P) | Во встроенных портах CPU **подтверждения нет**. Сервер даёт карта **AS-FOPC02** («OPC-UA Server, Modbus TCP», только для CPU AS300) | Только сниппет [deltaacdrives](https://deltaacdrives.com/delta-as-fopc02-as-series-plc-accessories/); оглавление [руководства AS](https://www.manualslib.com/manual/1897643/Delta-As-Series.html) называет раздел «OPC-UA Slave». ISPSoft ≥ 3.14 — сниппет |
| **AS200, DVP-S/E/SS2/SE, DVP-PM** | **Не подтверждено** — источников про OPC UA не найдено | Для DVP/AS200 рабочий путь — Modbus TCP |
| AS-FFTP01 | Карта для IIoT: OPC-UA, MQTT, Node-RED | Только сниппет Mouser |

Отдельные серверы: «Delta Serial OPC Server» делает не Delta, а OPCTechs. Это OPC **DA**, без UA, по серийному
каналу ([opcti.com](https://opcti.com/Delta-Serial-OPC-Server.aspx)). COMMGR / DIAServer / DIALink — не подтверждено.

**Modbus TCP (запасной и самый дешёвый путь):**

- DVP-SE, AS: порт 502, станция 1 ([proxus.io](https://proxus.io/docs/connecting-data/protocols/delta/), настройки
  стороннего драйвера, не спецификация Delta).
- DVP: `D0` читается по адресу **4096 (0x1000)** как holding-регистр — пример с форума
  [LogicMachine](https://forum.logicmachine.net/showthread.php?pid=5588), модель в нём не указана. Блог
  industrialmonitordirect даёт `D0 = 40001`, смещение 0 — это **противоречит** форуму; ни то ни другое по официальной
  таблице DVP не проверено.
- AS300: официальная таблица — приложение B.1 руководства AS
  ([PDF](https://deltronics.ru/images/manual/AS300_AS200_Modbus_table.pdf), не декодировался). Сниппет: `D0–D29999` →
  `400001–430000`, то есть адрес 0.

**Не подтверждено вообще:** лимиты OPC UA сервера Delta (теги, клиенты), совместимость `asyncua` с Delta, список политик
безопасности. AX-серия построена на CODESYS, поэтому поведение CODESYS-сервера вероятно, но это допущение.

## 4а. Модель владельца: AS228 (серия AS200), уточнение 2026-10-08

Ни один первичный документ Delta не открылся. Всё ниже — **сниппеты** выдачи и описания магазинов, кроме отмеченного.

| Факт | Статус | Источник |
|---|---|---|
| Встроенный Ethernet есть (AS228T-A: Ethernet, 2×RS-485, USB, CANopen; AS228R-A: 1×Ethernet, 2×RS-485, USB, Micro SD, CAN) | сниппет. Один порт или два — источники расходятся | [AS228T-A](https://deltaacdrives.com/delta-as228t-a-as-series-plc/), [AS228R-A](https://www.em.co.za/AS228R-A) |
| Протоколы AS228T-A: Modbus, Modbus TCP, EtherNet/IP, CANopen | сниппет | то же |
| Порт 502 по умолчанию | слабый источник (сторонний блог) | [industrialmonitordirect](https://industrialmonitordirect.com/ru/blogs/knowledgebase/configuring-delta-as-plc-communication-with-universal-robots) |
| `D0–D11999` → holding, старт с 4096 (0x1000); 0- или 1-основа не подтверждена | сниппет из руководства AS | [dicomp.com.br](https://www.dicomp.com.br/downloads/materiais_apoio/datasheet/18864-2.pdf) |
| M/X/Y в Modbus для AS | не подтверждено (статья industrialmonitordirect про DVP, не про AS) | — |
| OPC UA на AS200 | встроенного не найдено; карта AS-FOPC02 — формулировка «только AS300» прямо не подтверждена ни одним источником | [AS-FOPC02](https://deltaacdrives.com/delta-as-fopc02-as-series-plc-accessories/) |
| Лимиты запроса (регистров), число соединений, порядок байт float | не подтверждено | — |

**Вывод по AS228:** вероятный путь — **Modbus TCP по встроенному Ethernet**, без покупки карт; нового кода
протокола не нужно (`Services/modbus`, `device_hub`). Это гипотеза до проверки на железе.

**Кандидаты для чтения целиком** (локально, не через веб-выжимку): AS Operation Manual на
[automatikosbiuras.lt](https://www.automatikosbiuras.lt/app/default/files-module/local/products_files/as200-delta-electronics-operation-manual.pdf),
AS Hardware Manual на [deltronics.ru](https://deltronics.ru/images/manual/AS300_AS200_HM_EN_20180209.pdf),
гайд Weintek по Modbus TCP для AS300/DVP-ES3
([PDF](https://dl.weintek.com/public/PLC_Connect_Guide/DELTA_AS300_DVP_ES3_MODBUS_TCP_IP.pdf)).

**Проверка на стенде (один вечер):** ПК ↔ ПЛК по Ethernet, любым Modbus-клиентом прочитать `D`-регистр с известным
значением; сверить адрес, основу адресации, порядок байт float, число регистров за запрос.

Наглядное сравнение протоколов — [`2026-10-08_opcua-vs-modbus-explainer.html`](2026-10-08_opcua-vs-modbus-explainer.html).

## 4б. Панель DOP-103WQ (HMI Delta), уточнение 2026-10-09

Контекст: в схеме коллег данные опрашивают через сторонний OPC-сервер на ПК, а с панели/контроллера идёт Modbus TCP
(объяснение, зачем так делают, — в переписке сессии; кратко: OPC-сервер на ПК работает шлюзом-переводчиком для чужих
SCADA/MES). Метки: «в источнике» — страница открыта; «сниппет» — виден только в выдаче поиска.

| Факт | Статус | Источник |
|---|---|---|
| DOP-103WQ: **4,3"**, 480×272, Cortex-A8 800 МГц, 512 МБ RAM. (В первом запросе разведчику ошибочно значилось 10,1" — это мой промах, в самой панели не ошибка) | в источнике | [deltathailand](https://www.deltathailand.com/en/products/automation/Industrial-Automation/Control/HMI/Advanced-HMI-DOP-103WQ) |
| Встроенный Ethernet есть (10/100, 1 порт, COM1 RS-232, COM2 RS-422/485 — это сниппет) | «Built-in Ethernet» в источнике; остальное сниппет | то же, [delta-emea](https://www.delta-emea.com/en-gb/products/Touch-Panel-HMI-Human-Machine-Interfaces/4688) |
| Modbus TCP **master**: драйвер Modbus TCP/IP в Communication Settings, IP удалённого устройства в Controller IP | в источнике | [FAQ 2407](https://www.deltaww.com/en-us/FAQ/2407) |
| Modbus TCP **slave** через таблицу «Modbus TCP Mapping Table» (формат Coil/Register, пары «адрес Modbus ↔ адрес панели»). FAQ не называет модель и серию | в источнике, но модель не указана | [FAQ 2088](https://www.deltaww.com/en-US/service-support/faq/2088), [FAQ 2407](https://www.deltaww.com/en-us/FAQ/2407) |
| Включение: DOPSoft → Ethernet → Modbus → TCP/IP, порт 502, IP панели и контроллера в одной подсети, номера станций совпадают | в источнике | FAQ 2088 |
| Адреса LB/LW/RW задаются **вручную** в таблице, фиксированной таблицы соответствия нет | в источнике | FAQ 2088 |
| Лимиты slave (число записей, функции Modbus, число клиентов) | не подтверждено | — |
| **OPC UA у серии DOP-100** заявлен в брошюре Delta «DOP-100 Series» (редакция из RS Online, 2023, 48 стр.): стр. 7 «OPC UA — Supports M2M communication and data transmission among machines from various manufacturers», стр. 9 «Delta's HMI can implement M2M communication… by means of OPC UA… through information modeling». Текст извлечён локально (pypdf в изолированном окружении), 2026-10-09 | **в источнике (серия)**. Метка «M Type Only» на стр. 7, по координатам текста, стоит рядом с блоком Multimedia Functions, а не OPC UA — это вывод по раскладке, не по тексту. DOP-103WQ (тип W) с OPC UA в тексте напрямую не связан | [брошюра RS Online](https://assets.rs-online.com/v1695390379/Datasheets/ef456d47ccf0267a97630ef6c2978199.pdf) (в сессии скачана, локальный путь — в tool-results сессии); [Mouser](https://www.mouser.in/new/delta-electronics/delta-dop-100-hmi-platforms/) (сниппет) |
| Режимы OPC UA **Server / Client**, меню «IIoT → OPC UA Server» в DIAScreen/DOPSoft, лимиты тегов, безопасность, лицензия | **не подтверждено**: в брошюре нет слов «IIoT», «Server», «Client» рядом с OPC UA; эти детали взяты из ответа Google (без ссылки на документ) | — |
| Сетевые функции панели по брошюре (стр. 27) и по странице DOP-103WQ на deltathailand: FTP, e-mail, VNC, Web Monitoring, NTP | в источнике; OPC UA в этом списке нет | [deltathailand](https://www.deltathailand.com/en/products/automation/Industrial-Automation/Control/HMI/Advanced-HMI-DOP-103WQ) |
| Собственный OPC-сервер Delta для панелей (DIAServer / COMMGR / иное), OPC DA или UA, цена | не найдено | — |
| Схема «ПЛК AS ← панель → ПК» (панель читает ПЛК как master и отдаёт ПК как slave) | **вывод из двух фактов, не подтверждённая схема**; совместная работа master+slave в одной панели не проверялась | FAQ 2407 |

**Вывод:** от нашей стороны прослойка «OPC-сервер на ПК» не нужна — `Services/modbus` может читать панель или ПЛК
напрямую по Modbus TCP, а карту адресов даёт таблица панели (задаётся в DOPSoft, правится людьми).

**Не закрыто:** полный список протоколов DOP-103WQ (PDF [даташита](https://deltathailand.com/imgadmins/products/model_pdf_th/20210909105333.pdf)
скачан, но не прочитан), лимиты slave-режима, OPC UA в DOP-100, какая именно 10,1" панель имелась в виду (если имелась).

## 5. Главный вывод

**Решает модель ПЛК:**

| Модель | Путь |
|---|---|
| AX-3 / AX-8 | OPC UA встроенный — нужен новый `Services/opcua` |
| AS300 | OPC UA только с картой AS-FOPC02 (проверить по даташиту); иначе Modbus TCP |
| DVP / AS200 | Modbus TCP, **почти без нового кода** (`Services/modbus` + `generic_modbus` + YAML-карта) |

**Для «универсальности»** закладываем абстракцию «источник тегов» с двумя бэкендами: OPC UA (новый) и Modbus
(существующий). Остальное — состояние в state_store, GUI, история, веб — от протокола не зависит.

## 6. Оценка (рабочие дни, один разработчик с агентами)

| Блок | Дни |
|---|---|
| `Services/opcua`: клиент на `asyncua` по образцу modbus, карта тегов в YAML, переподключение, тестовый сервер на `asyncua`, тесты | 3–4 |
| Абстракция «источник тегов» и плагин, публикация в state | 1–2 |
| GUI-вкладка: таблица, качество, тренд, настройки подключения | 2–3 |
| История тегов в SQLite с ретенцией (на основе telemetry_sink) | 1–2 |
| HTML-дашборд для телефона: bind на LAN, только чтение, токен | 1–2 |
| Стенд с настоящим ПЛК: сертификаты, брандмауэр, отладка | 2–4 |

- Демо на симуляторе OPC UA: ~1–1,5 недели.
- MVP с настоящим ПЛК: ~2–3 недели. Процесс «тестер до кода + ревью после задачи» добавляет 20–30%.
- Если ПЛК только Modbus (DVP/AS200): блок `Services/opcua` отпадает, срок до MVP сокращается примерно на 3–4 дня
  плюс настройка карты.

**Нагрузка на БД (расчёт, не замер):** 50 тегов × 1 Гц = 4,3 млн строк в сутки. При ~40 байтах на строку это порядка
170 МБ/сутки без индексов. Поэтому писать **по изменению** (deadband + максимальный интервал) и задать
`retention_days`. SQLite на 30–50 тегов подходит; триггеры перехода на PostgreSQL — в
[`plans/storage-stack-embedded-first.md`](../../plans/storage-stack-embedded-first.md).

## 7. Технические риски

1. `asyncua` работает на asyncio, процессы фреймворка — на потоках: нужен отдельный поток с event loop (или
   `asyncua.sync`). Не пробовали.
2. Безопасность на стороне ПЛК (Basic256Sha256, сертификаты, доверие) у CODESYS-серверов часто съедает время стенда.
3. Веб-сервер в LAN без аутентификации отдаёт данные производства всем в сети; минимум — токен, режим «только чтение».
4. Таблицы адресов Modbus у Delta различаются между DVP и AS — сверять по официальной таблице, не по форуму.

## 8. Что осталось открытым

- **Модель ПЛК Delta не названа** — от неё зависит весь выбор протокола. Первый вопрос к владельцу.
- Лицензии, версии прошивок, лимиты тегов/клиентов OPC UA Delta не подтверждены; официальные PDF не открылись.
- Совместимость `asyncua` с Delta не проверена — первый шаг на стенде: подключиться UaExpert, потом `asyncua`.
- Адресация `D`-регистров для AS300 и DVP-SE сверена не с официальной таблицей.
- Простота добавления новой Services-вкладки принята по аналогии с phone_gateway/control_panel, не проверена.
- Сроки не калиброваны по реальной скорости прошлых задач проекта.
- Нужен ли запрос в ПЛК на запись — не уточнялся (в задаче только чтение).

## 9. Следующие шаги

1. Узнать модель ПЛК и есть ли на нём OPC UA (или карта AS-FOPC02).
2. Проверить подключение внешним клиентом (UaExpert / Modbus-клиент) с тестовыми тегами.
3. Завести план `plans/plc-tag-gateway.md` (формат Task X.Y) и пересмотреть строку N-5 в бэклоге.
