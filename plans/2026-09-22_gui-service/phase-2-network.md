# Phase 2 — Сеть: кадры и управление по LAN

Часть плана [`plan.md`](plan.md). Цель фазы: Пульт на машине B видит дисплеи и управляет бэкендом
на машине A; дверь вне localhost закрыта токеном **fail-closed**. Modbus-тракт робота/ПЧ уже TCP и
здесь не трогается — сеть добавляется только кадрам и сокету управления.

---

### Task 2.1 — Кадры по сети: промоушен `mjpeg_sink` → `Services/frame_stream`, мост отдаёт дисплеи потоком

**Level:** Middle+ (Sonnet, extended thinking)
**Assignee:** developer
**Goal:** `BridgeGuiProcess` (1.3) умеет отдавать каждый дисплей как MJPEG-поток; `RemoteFrameSource`
выбирает транспорт: SHM по имени, если бэкенд на этой же машине и attach удался, иначе — поток.

**Контекст (сверено по ветке `feat/line-sim` 2026-09-22):** MJPEG-сервер **уже написан** — `Plugins/sim/mjpeg_sink`
(line-sim Task 1.2, `3f4516fe`, с README/STATUS/hazard-тестами), дорога сим → инспектор им и ходит; принимающая
сторона — бэкенд `stream` у `camera_service` на `cv2.VideoCapture(url, CAP_FFMPEG)`. Эта задача — **второй
потребитель** того же сервера, а значит повод для промоушена по правилу «механизм входит в ядро, когда его тянет
приложение»: ядро сервера (энкодер, multipart, «последний кадр побеждает», `client_count`) переезжает в
`Services/frame_stream` **переносом** (git-история, тесты едут с ним), `mjpeg_sink` становится тонким плагином
над ним. Ничего второго не писать. Клиент для Пульта — вопрос этой же задачи: `VideoCapture` копит внутренний
буфер и не отдаёт возраст кадра — для дисплеев нужна семантика «последний кадр, старые в мусор» + `X-Timestamp`;
если сервер `mjpeg_sink` заголовков не шлёт — добавить там, с тестом там. Первая редакция ссылалась на
«line-sim Task 1.1 `Services/frame_stream`» — такой задачи нет.

**Files:**
- НОВЫЙ `Services/frame_stream/` — перенос ядра из `Plugins/sim/mjpeg_sink/plugin.py` (server + тесты);
  `README.md`/`STATUS.md`/`DECISIONS.md` (new-lite: докстринг-контракт `FramePublisher`/`FrameReader`)
- `Plugins/sim/mjpeg_sink/plugin.py` — тонкая обвязка над `Services/frame_stream`; его тесты зелёные (число
  ДО переноса — baseline)
- `multiprocess_prototype/frontend/bridge_process.py` — сервер `frame_stream` внутри моста:
  `/display/<id>.mjpg`, `/display/<id>/snapshot.jpg`, `/health`; включается конфигом
  (`presentation_bridge.yaml`: `stream: {enabled, host, port, jpeg_quality}`)
- `multiprocess_framework/modules/frontend_module/bridge/remote_frame_source.py` — стратегия выбора
  транспорта + клиент потока из `Services/frame_stream`
- Протокол: `capabilities` бэкенда сообщает `frames: {shm: bool, stream_url: str | null}`
- Тесты: `frontend/tests/test_bridge_stream.py`, `frontend_module/tests/test_remote_frame_source_transport.py`

**Steps:**
1. Мост: на подписку `frames.subscribe` с `transport="stream"` — включает энкодинг для дисплея
   (не раньше: без сетевого подписчика JPEG не кодируется — цена без потребителя). Один энкодер на
   дисплей, N клиентов потока читают одно и то же.
2. Возраст кадра — заголовок `X-Timestamp` (монотонное время продюсера из конверта кадра) в каждой
   части multipart — клиент считает возраст, не гадает.
3. `RemoteFrameSource`: порядок выбора — (а) хост бэкенда локальный (`127.0.0.1`/`::1`/собственный IP)
   и `capabilities.frames.shm` → SHM по имени; (б) иначе `stream_url`. Выбор — в лог и в статус-бар
   (2.3 его прочитает). Ручное переопределение `--frames=shm|stream` для отладки.
4. Автор пишет hazard-тесты: (а) клиент потока читает медленнее, чем сервер пишет — сервер не копит
   очередь (последний кадр побеждает, память сервера ограничена); (б) обрыв клиента посреди части
   multipart — сервер не падает, энкодер выключается при нуле подписчиков.

**Acceptance criteria:**
- [ ] На одной машине с `stream.enabled: true` `RemoteFrameSource` выбирает **SHM** (лог/статус
      содержит `transport=shm`), а `curl -s -o /dev/null -w '%{http_code}'
      http://127.0.0.1:<port>/display/main/snapshot.jpg` → `200` и валидный JPEG — оба транспорта живы.
- [ ] С `--frames=stream` на той же машине: дисплей получает ≥ 20 fps при 640×480, `jpeg_quality: 90`
      (счётчик кадров клиента за 30 с / 30); возраст кадра p50 ≤ 2 периода продюсера (по `X-Timestamp`).
- [ ] Без подписчиков потока `cv2.imencode` не вызывается (спай на границе — счётчик энкодера моста
      в `get_status` равен 0 за 10 с работы без клиентов).
- [ ] Два клиента одного потока получают кадры с одинаковыми `seq` (один энкодер), при этом fps
      каждого ≥ 0.9 × fps одного клиента.
- [ ] Обрыв клиента (`kill` curl посреди чтения) — `/health` моста отвечает `200` через 1 с,
      продюсер кадров не заметил (fps по `introspect_router_stats` без изменений).

**Out of scope:** аутентификация потока (2.2 — токен тот же: query/заголовок); выбор кодека сверх
JPEG/PNG; аппаратное кодирование.
**Edge cases:** `jpeg_quality` вне 1..100 — валидация конфига, не тихий OpenCV-дефолт; дисплей моно
(1 канал) — кодируется как есть, форма в дескрипторе честная.
**Dependencies:** Task 1.3; `Plugins/sim/mjpeg_sink` в `main` (merge `feat/line-sim`). **Вся Ф2 — после Ф3
этого плана, по реальной нужде «Пульт на другой машине».**
**Module contract:** new-lite (`Services/frame_stream` — перенос с контрактом) + impl-only.

---

### Task 2.2 — Безопасность двери вне localhost: PSK fail-closed, TLS-опция

**Level:** Senior (Opus) — security-чувствительная
**Assignee:** teamlead; **reviewer в режиме security обязателен**
**Goal:** `SocketChannel` и поток кадров при `bind ≠ 127.0.0.1` требуют pre-shared токен;
без настроенного токена endpoint **не стартует** (fail-closed, громкая ошибка); неверный токен —
соединение закрыто, счётчик. TLS — опция через stdlib `ssl` (самоподписанный сертификат допустим).
`backend_ctl` (driver и MCP) умеют токен.

**Контекст:** README сокета: «localhost dev-tool, аутентификации нет». Пока bind был `127.0.0.1`,
это честно. Сеть меняет класс угрозы: сокет принимает **любые** router-сообщения, включая
`system.*` (рестарт процессов, запись регистров). Минимум для доверенной LAN — PSK; честно: PSK по
открытому TCP перехватываем, поэтому TLS — опция, включаемая одним флагом, и решение «за пределы
цеховой сети» — за владельцем, не за кодом по умолчанию.

**Files:**
- `multiprocess_framework/modules/router_module/channels/socket_channel.py` — handshake: первая
  строка сессии `{"type": "auth", "token": ...}` при `require_auth`; таймаут handshake; счётчики
  `auth_ok/auth_failed`; опция `ssl_context`
- `multiprocess_framework/modules/process_manager_module/process/backend_ctl_endpoint.py` — правило
  fail-closed: `host ∉ {127.0.0.1, ::1}` и токен пуст → endpoint не создаётся, ошибка в лог с
  названием env/поля; источник токена: env `BACKEND_CTL_TOKEN` > `config.token`; TLS: `tls_cert`/`tls_key`
- `multiprocess_framework/modules/router_module/channels/socket_client.py` — `token`, `ssl_context`
- `backend_ctl/driver.py`, `mcp_server_sdk.py`, `endpoint_config.py` — токен из env/аргумента
- `Services/frame_stream` (сервер) — тот же токен заголовком `Authorization: Bearer` / query при
  `require_auth`; мост прокидывает
- `backend_ctl/README.md`, `AGENTS.md` — раздел «Сеть и токен»
- Тесты: `router_module/tests/test_socket_channel_auth.py`, `process_manager_module/tests/
  test_backend_ctl_endpoint.py` (дополнить), `backend_ctl/tests/` (токен в driver)

**Steps:**
1. Handshake до любого router-сообщения; до `auth_ok` входящие строки **не** доходят до `on_inbound`
   (тест: команда до auth — отброшена, счётчик `auth_failed`, сессия закрыта).
2. Сравнение токена — `hmac.compare_digest`. Токен в логи не попадает (тест: grep по логу после
   неудачного handshake — 0 вхождений значения токена).
3. Fail-closed в endpoint: `host` не loopback и токен пуст → `ValueError`/лог уровня ERROR с
   текстом «BACKEND_CTL_TOKEN обязателен при bind <host>»; процесс-менеджер поднимается **без**
   двери (система живёт, дверь — нет).
4. TLS: `ssl.SSLContext(PROTOCOL_TLS_SERVER)` + `load_cert_chain`; клиент — `PROTOCOL_TLS_CLIENT`,
   для самоподписанного — `--tls-ca <cert>` (pinning), без `check_hostname=False` по умолчанию.
5. Автор пишет hazard-тесты: (а) медленный handshake (клиент подключился и молчит) — сессия закрыта
   по таймауту, accept-loop не заблокирован (второй клиент обслуживается параллельно); (б) 50
   неверных токенов подряд — сервер жив, `auth_failed == 50`, легитимный клиент подключается.

**Acceptance criteria:**
- [ ] `SocketChannel(host="0.0.0.0", require_auth=True, token="s")`: клиент с токеном `s` → `auth_ok`,
      команда `ping` отвечает; клиент с токеном `x` → соединение закрыто за ≤ 1 с, `auth_failed == 1`,
      `on_inbound` не вызван ни разу.
- [ ] Endpoint с `host="0.0.0.0"` и пустым `BACKEND_CTL_TOKEN` → endpoint отсутствует (`capabilities`
      недоступны, порт закрыт — `socket.create_connection` падает), в логе ERROR с именем env; система
      при этом стартует и обрабатывает кадры.
- [ ] Endpoint с `host="127.0.0.1"` и пустым токеном — работает как сегодня (обратная совместимость
      dev-пути; тест существующий, не удалять).
- [ ] Клиент, отправивший `send_command` до auth-строки: команда не исполнена (спай на процессе-стабе —
      0 вызовов), сессия закрыта.
- [ ] С `tls_cert/tls_key`: клиент без TLS получает ошибку/закрытие, клиент с `--tls-ca` работает;
      `openssl s_client -connect` подтверждает TLS-рукопожатие (вывод в отчёт задачи).
- [ ] `grep -c "<значение токена>" <лог>` после 10 неверных попыток == 0.
- [ ] Поток кадров с `require_auth`: запрос без `Authorization` → `401`; с верным — `200`.
- [ ] `backend_ctl` driver с `BACKEND_CTL_TOKEN` подключается к защищённому endpoint; MCP-сервер
      `capabilities` работает (live-смоук в отчёт).

**Out of scope:** пользователи/роли, ротация токена, аудит команд оператора (Deferred).
**Edge cases:** токен с пробелами/юникодом — сравнивается байтами UTF-8 без strip; `host="::"` (IPv6
any) — считается не-loopback, тоже fail-closed.
**Dependencies:** Task 1.2 (клиент во фреймворке).
**Module contract:** impl-only. **Rejected:** basic-auth по HTTP для сокета — сокет не HTTP; JWT —
зависимость и сложность без второго участника (нет сервера выдачи).

---

### Task 2.3 — Сквозная приёмка по LAN: Пульт на B ↔ бэкенд на A, числа

**Level:** Middle (Sonnet) — приёмка, не разработка
**Assignee:** developer (снятие чисел), **cto — вердикт по фазе**
**Goal:** доказать числами, что Ф2 работает на двух реальных машинах в одной сети: RTT команды,
возраст кадра, fps дисплея, поведение при отключении кабеля/Wi-Fi. Без чисел фаза не принята.

**Контекст:** до этой задачи всё измерялось на localhost. Сеть добавляет джиттер, MTU, Wi-Fi.
Если под рукой только одна машина — вторая может быть ВМ или Docker с bridge-сетью, но это
записывается явно как ограничение приёмки, не выдаётся за две машины.

**Files:**
- НОВЫЙ `docs/reviews/2026-XX-XX_gui-service-network-acceptance.md` — отчёт с числами
- НОВЫЙ `scripts/pult_probe.py` (или расширение `backend_ctl/probes`) — измеритель RTT/возраста
  кадра, печатает p50/p95/max; переиспользует `SocketClient` и клиент `frame_stream`

**Steps:**
1. Машина A: бэкенд с синтетическим источником, `presentation_bridge.yaml`, `BACKEND_CTL=1`,
   `host=0.0.0.0`, токен, `stream.enabled`. Машина B: Пульт `--connect A:8765 --token ...`.
2. 5 минут работы: `pult_probe` пишет RTT `ping`-команды каждую секунду (p50/p95/max), возраст
   кадра по `X-Timestamp` (p50/p95), fps дисплея; часы машин синхронизировать (NTP) или мерить
   возраст относительным способом (echo-запрос) — назвать выбранный.
3. Отключить сеть на B на 20 с → вернуть. Записать: время до «отключён», время до восстановления,
   восстановились ли подписки и дисплеи без действий оператора.
4. Проверить fail-closed вживую: бэкенд с `host=0.0.0.0` без токена — двери нет; с токеном —
   Пульт без токена отвергнут.
5. Тот же прогон повторить с `--frames=stream` при `jpeg_quality` 75 и 95 — таблица fps/возраст/
   Мбит/с (по `ifstat`/счётчику байт сервера).

**Acceptance criteria:**
- [ ] Отчёт содержит таблицу: RTT p50/p95/max, возраст кадра p50/p95, fps дисплея, Мбит/с — для
      q75 и q95 при 640×480, 5 минут каждая; и одну строку 1280×720 q90 (хотя бы 60 с).
- [ ] RTT p95 команды ≤ 50 мс по проводу (Wi-Fi — записать факт, порог не задаётся).
- [ ] Возраст кадра p50 ≤ 150 мс при 640×480 q90 по проводу.
- [ ] Обрыв сети 20 с: Пульт показал «отключён» ≤ 10 с; после возврата дисплеи ожили ≤ 30 с без
      действий оператора (время в отчёте).
- [ ] Fail-closed воспроизведён вживую: две строки лога (без токена — ERROR, с неверным токеном —
      `auth_failed` растёт) процитированы в отчёте.
- [ ] Отчёт заканчивается разделом «что не проверено» (например: Wi-Fi, IPv6, > 2 клиентов).

**Out of scope:** оптимизация по результатам (если числа плохи — заводится задача, а не правится
на ходу внутри приёмки).
**Edge cases:** две машины недоступны — прогон в ВМ, помечено как ограничение; часы не синхронны —
возраст мерить echo-способом, назвать.
**Dependencies:** Task 2.1, Task 2.2.
**Module contract:** none (приёмка).
