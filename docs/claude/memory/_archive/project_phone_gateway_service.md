---
name: project-phone-gateway-service
description: phone_gateway — always-on сервис «фото+слово/фраза с телефона по WiFi» с тумблером в Services-вкладке; v1 готов (30 тестов, verified live), letter-mode wiring — follow-up
metadata:
  type: project
---

Новый Service `Services/phone_gateway/` + source-плагин `phone_camera` (в `plugin/`).
Зеркалит `Services.hikvision_camera`: ядро (gateway = HTTP-сервер stdlib + imaging
decode/EXIF/letterbox + netinfo local_ip + qr segno-опц SVG/PNG + web HTML) + тонкий
source-плагин. Ветка `feat/phone-gateway-service` (на 2026-06-15 — uncommitted).

**Модель (итог обсуждения с владельцем):** это **отдельный always-on сервис**, не камера.
Процесс `phone_gateway` объявлен в `base.yaml` (protected, `auto_start: false`),
есть в каждом рецепте. HTTP-сервер **включается/выключается** из GUI:
**Services → Телефон** (тумблер Вкл/Выкл) — команды `start_server`/`stop_server`
плагину через `bridge.on_action_command("phone_camera", ...)`. Панель: URL + QR +
статус + последнее слово (URL/QR считаются локально в GUI — та же машина; running и
слово реактивно из state). SHM-слот `camera_9_frame` (не конфликтует с `camera_0`).

**Поток:** телефон в браузере → `fetch` raw body на `POST /frame` (картинка) и
`POST /word` (текст UTF-8, **фраза из нескольких слов** — внутренние пробелы
сохраняются, `" ".join(split())`) — без multipart (cgi удалён в 3.13). `produce()`
отдаёт кадр (`hold_last=True`), слово → `processes.<proc>.state.phone.word`.

**Verified live (qt-mcp + curl):** тумблер «Включить» → сервер up (200 /health) →
статус «включён ✓» реактивно; `POST /word "ГАЙКА"` → GUI-метка «Последнее слово: ГАЙКА»
(кросс-процессно); `POST /frame` 640×480 → 200, кадры до GUI. 27 тестов Service +
3 GUI-секции; 127 существующих не сломаны.

Грабли/решения:
- **один QR не умеет «WiFi+URL» сразу** — разные стандарты; `make_qr_svg/png(url)` vs `make_wifi_qr_svg`
- `cv2.putText` не рисует кириллицу → placeholder-подсказка на латинице
- **cv2.imdecode (OpenCV 4.x) САМ применяет EXIF-ориентацию** → ручной поворот давал двойной (+90° мимо, жалоба владельца); фикс: `IMREAD_IGNORE_ORIENTATION` + один свой поворот (мой EXIF-парсер читает тег верно)
- `local_ip` брал VPN-интерфейс (10.x, маршрут в интернет) вместо WiFi → `local_ips()` со списком кандидатов (192.168 первым), GUI показывает все; телефон не открывал VPN-адрес
- превью фото в панели = base64-миниатюра в state (раз на снимок, гейт по frame_seq, НЕ каждый кадр); bindings зовёт `widget.set_thumb_b64` (getattr-fallback, не только text/value)
- `segno` опционален (нет → QR=None, мягкая деградация; `uv pip install segno` — ставит владелец)
- firewall Windows: разрешить Python (loopback работает без exception)
- discovery `_file_to_module` пропускает `''` в sys.path → в `python -c` не находит; `run.py` вставляет абс. PROJECT_ROOT — в приложении ОК (system.yaml сканирует Plugins+Services)
- GUI-секция живёт в prototype-слое (`frontend/.../services/phone/`), импорт `Services.phone_gateway` ОК (prototype → Services)
- сервер обязан жить в процессе-источнике (фото=SHM-кадр, не гонять по шине IPC)
- `phone_demo.yaml` удалён — phone_gateway теперь always-on в base, отдельный demo конфликтовал бы по порту 8080

Follow-up: прокинуть `phone.word` в распознаватель букв ([[project_letter_angle_training]]);
маршрут фото в обработку рецепта (сейчас источник → gui); опц. HTTPS (если телефон
блокирует камеру в браузере по HTTP); WiFi-QR в GUI; segno в extras pyproject.

**ОБНОВЛЕНИЕ 2026-06-15 (вечер):** владелец сменил направление — телефон стал
**нодой-источником в рецепте** (УБРАНО из base; было always-on). Демо
`recipes/phone_inspect.yaml` (phone_camera → дисплей `phone_view`), нода
`phone_camera` в палитре Pipeline. Панель Services → Телефон теперь по glob
`processes.*.state.phone.*` (находит ноду в любом рецепте); toggle по plugin_name.
Этап 1 ПОДТВЕРЖДЁН вживую: фото с телефона видно в дисплее (phone_inspect активен
через Recipes), правильная ориентация. Этап 2 DONE: **пульт в GUI ПК** (Services →
Телефон) — 3 кнопки: координаты {x_mm,y_mm}→`signal_1`, текст→`signal_2`, триггер→
`signal_3`. Кнопка → `emit_signal` → `produce()` эмитит item `{signal_N: value,
data_type:'signal'}` (без кадра) в chain_targets. Вяжешь порт к потребителю:
`signal_1`→`robot_io` (job_source='signal_1', {x_mm,y_mm}→devices-hub→робот);
`signal_2`→потребитель слова. SourceProducer шлёт items без 'frame' как данные +
поддерживает per-item 'target'. 42 теста. Триггер — GUI-кнопки (телефон-кнопки позже).
Грабля: live-скриншот пульта не снял (клики qt-mcp по дереву Services мимо узла
«Телефон» — подрезан внизу), но виджет qtbot-проверен (строится+эмитит), путь команды =
рабочий тумблер.
**Грабля дисплеев:** раскладка дисплеев НЕ грузится из YAML при `run.py` (берётся
персистентная от прошлого рецепта) → показ фото через активацию рецепта в GUI
(Recipes → выбрать → Загрузить) ИЛИ вязку в Pipeline-редакторе; кадр без дисплея →
лог `on_frame неизвестный slot_id 'main'` (безобиден).

**ОБНОВЛЕНИЕ 2026-06-16 (стабильность подключения):** две правки (ветка
`feat/pult-control-panel`, uncommitted).
1. **Переподключение телефона рвалось** из-за keep-alive: телефон держал
   HTTP/1.1-соединение, после WiFi-power-save оно молча умирало, а POST не
   идемпотентен (браузер не делает авто-ретрай) → «Сеть недоступна». Фикс в
   `gateway.py`: каждый ответ `Connection: close` + `close_connection=True` +
   `timeout=20` на handler → каждый запрос по свежему соединению. + try/except
   OSError в `_start_server` (порт занят старым процессом → понятная ошибка).
2. **Адрес/QR показывал НЕ WiFi** (проводной Ethernet `192.168.x`), т.к.
   `netinfo._priority` ранжировал только по диапазону IP, а Ethernet и WiFi оба
   `192.168.*`. Фикс: ранжирование по ТИПУ адаптера через **psutil** (имена
   интерфейсов): `_iface_rank` WiFi(0)<проводной(1)<виртуальный(2), затем
   `_priority` как тай-брейк. Новое API `local_endpoints()→[(имя_адаптера,ip)]`,
   `local_ips()` поверх него. GUI (`services/phone/`) подписывает каждый адрес
   именем адаптера + авто-обновляет адрес/QR по QTimer(4с) при смене WiFi
   (`_maybe_refresh_address`, QR пересоздаётся только при реальной смене).
   Грабли: WiFi-адаптер Windows по-русски = «Беспроводная сеть» (ловится хинтом
   "беспровод"); VPN-адаптер может называться именем профиля (не ловится virtual-
   хинтами, но уходит вниз по IP-диапазону 10.x).
3. **Доп. грабля (реальный кейс владельца):** WiFi-адаптер ПК был воткнут в
   ЧУЖУЮ сеть с CGNAT-адресом `100.73.10.92` (диапазон 100.64.0.0/10), а телефон
   — в роутере `192.168.1.x` (= Ethernet ПК `192.168.1.240`). WiFi-first отдавал
   QR на 100.x → телефон не доставал. Фикс: `_addr_usability` демоутит CGNAT
   100.64/10 и APIPA 169.254/16 НИЖЕ нормального LAN (ключ сортировки стал
   `(usability, iface_rank, priority)`) → QR теперь на 192.168.1.240.
   **VERIFIED LIVE 2026-06-16:** приём с телефона заработал после (а) `netsh
   advfirewall firewall add rule ... localport=8080` (вход.8080 был закрыт —
   netstat показал connections ТОЛЬКО с localhost = корневая причина «на ПК
   открывается, с телефона нет»), (б) использования LAN-адреса 192.168.1.240.
   48 тестов phone_gateway+секция.

**ОБНОВЛЕНИЕ 2026-06-17 (корень = брандмауэр, НЕ адрес; правка адреса откачена):**
Симптом «не работает/не подключается». Я ошибочно полез менять адрес, владелец
вернул: **«верни как было вчера когда заработало»**.
1. **НАСТОЯЩИЙ корень = снова брандмауэр.** netsh-правило 2026-06-16 НЕ
   сохранилось (живая проверка: `netsh advfirewall firewall show rule name=all
   dir=in | findstr 8080` пусто; 8080 не слушался). Фикс (владелец, ОТ АДМИНА):
   `netsh advfirewall firewall add rule name="Phone Gateway 8080" dir=in
   action=allow protocol=TCP localport=8080`. **ПЕРВЫМ ДЕЛОМ при «с телефона
   нет» — проверять это правило, не трогать адрес.**
2. **Адрес НЕ менять.** Я сменил было дефолт netinfo на «WiFi первым»
   (`100.73.28.67`) по словам владельца «только вайфай» — ОШИБКА: физически
   телефон в сети `192.168.1.x` (домашний роутер = Ethernet ПК `192.168.1.240`),
   а WiFi ПК `100.73.x` — ДРУГАЯ сеть, телефон туда не попадает. Правка откачена
   `git checkout HEAD -- netinfo.py test_netinfo.py`; вернулось вчерашнее
   `(addr_usability, iface_rank, priority)` → PRIMARY = 192.168.1.240. Это и есть
   рабочее. Урок: при «не работает телефон» НЕ менять эвристику адреса на слово
   «вайфай» — сперва брандмауэр, потом проверить, в какой подсети реально телефон
   (`ipconfig` ПК vs WiFi телефона); рабочий адрес = тот, чья подсеть совпадает с
   подсетью телефона (вчера и сегодня это 192.168.1.x через Ethernet ПК).
