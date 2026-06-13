-- =====================================================================
--  Delta SCARA · DRAStudio (Lua/RL) — УНИВЕРСАЛЬНАЯ ПРОГРАММА
--  Объединяет cvt_step4.lua (CVT-трекинг) + robot_vfd_bridge.lua (мост к
--  частотнику INVT GD20) + настройку параметров робота с ПК.
--
--  Одна программа на роботе делает три вещи, диспетчеризуя их по МАРКЕРАМ
--  (ПК ставит флаг в регистр → робот в задаче Motion подхватывает):
--    1) CVT pick-place по координатам {X,Y,E_capture}       — маркер 0x1100
--    2) команда частотнику (пуск/стоп/частота/сброс) по RS-485 — маркер 0x1204
--    3) смена параметров робота (скорость, домашняя позиция)  — маркер 0x1300
--
--  Архитектура AuxTasks (мануал RL стр. 11-4):
--    AuxTasksAdd(Motion, Mirror) — кооперативно, по 15 мс на задачу.
--    Двигаться может ТОЛЬКО первая задача (Motion). Поэтому весь приём
--    маркеров и блокирующий RS-485 (он делает DELAY) — в Motion.
--    Mirror — ПРОХОДНОЙ (стр. 11-6): только зеркалит энкодер, без DELAY/while,
--    чтобы REG_ENC всегда был свежим (ПК читает его как E_capture в кадре).
--
--  ⚠️ Команда частотнику/настройки исполнятся в простое между движениями:
--     пока робот делает pick-place, AuxTasks не отдаёт время другим веткам.
--
--  Связь:
--    ПК (Python pc_robot.py) ──Modbus TCP master──▶ робот (:502, server)
--    робот (этот скрипт) ──RS-485 Modbus RTU (Free Port)──▶ INVT GD20
--
--  НАСТРОЙКА ПРИВОДА INVT GD20 (на самом VFD, один раз):
--    P00.01=2 (RUN=связь) P00.06=8 (частота A=связь)
--    P14.00=1 (адрес=SLAVE) P14.01=4 (19200) P14.02=1 (8E1 RTU)
-- =====================================================================

-- =====================  КАРТА РЕГИСТРОВ  ============================
-- ── CVT: вход задания (ПК пишет, робот читает) ──
local REG_JOB_FLAG = 0x1100    -- W  : МАРКЕР «координаты»: 1 = задание готово, 0 = принято
local REG_X        = 0x1101    -- W  : X в 0.1 мм
local REG_Y        = 0x1102    -- W  : Y в 0.1 мм
local REG_ECAP     = 0x1104    -- DW : E_capture — энкодер в момент кадра (чётный адрес!)
local REG_ABORT    = 0x1106    -- W  : 1 = АВАРИЙНЫЙ СТОП движения (Mirror зовёт MotionStop)
-- ── CVT: выход состояния (робот пишет, ПК читает) ──
local REG_FREE = 0x1110        -- W  : 1 = робот свободен (слот пуст), 0 = занят
local REG_ENC  = 0x1112        -- DW : живой энкодер, Mirror зеркалит каждый слайс (чётный!)
-- ── CVT: эхо принятых/вычисленных координат (робот пишет) ──
local REG_ECHO_X = 0x1120      -- W  : принятый job_x (0.1 мм)
local REG_ECHO_Y = 0x1121      -- W  : принятый job_y
local REG_PX     = 0x1122      -- W  : вычисленный px = job_x + UX*trav (0.1 мм)
local REG_PY     = 0x1123      -- W  : вычисленный py
local REG_TRAV   = 0x1124      -- W  : сдвиг ленты trav (0.1 мм)

-- ── VFD: команда от ПК (робот читает и шлёт в привод по RS-485) ──
local REG_CMD_RUN   = 0x1200   -- W  : 0 = стоп, 1 = пуск
local REG_CMD_DIR   = 0x1201   -- W  : 0 = вперёд, 1 = назад
local REG_CMD_FREQ  = 0x1202   -- W  : частота ×100 (0.01 Гц)
local REG_CMD_RESET = 0x1203   -- W  : 1 = сброс ошибки
local REG_VFD_FLAG  = 0x1204   -- W  : МАРКЕР «команда ПЧ»: 1 = есть новая команда
-- ── VFD: статус привода (робот пишет, ПК читает), блок 0x1210..0x1217 ──
local REG_ST_BASE     = 0x1210
local ST_BLOCK_CNT    = 8
local REG_ST_COMM_ERR = 0x1217
--   0x1210 RUN | 0x1211 частота×100 | 0x1212 ток×10 | 0x1213 шина В
--   0x1214 код ошибки | 0x1215 сырое состояние | 0x1216 heartbeat | 0x1217 счётчик ошибок RS485

-- ── Настройки робота от ПК (робот читает и применяет) ──
local REG_CFG_FLAG   = 0x1300  -- W  : МАРКЕР «параметры робота»: 1 = есть настройки
local REG_CFG_SPD    = 0x1301  -- W  : скорость SPD_MOVE, %
local REG_CFG_HOME_X = 0x1302  -- W  : домашняя X, 0.1 мм
local REG_CFG_HOME_Y = 0x1303  -- W  : домашняя Y, 0.1 мм
local REG_CFG_HOME_Z = 0x1304  -- W  : домашняя Z, 0.1 мм
-- 0x1305… — РЕЗЕРВ под расширение (Z_PICK, GL_PLACE, …)

-- =====================  КАЛИБРОВКА / ГЕОМЕТРИЯ  ====================
local CV        = 1            -- группа конвейера (= CVID в CVT_Initialization)
local FACTOR_MM = 0.144473     -- пульсы → мм (cvtFactor 144473/1000 = 144.473 мкм/пульс)
local UX, UY    = 0, -1        -- лента идёт в −Y → вектор (0,-1)
local XY_SCALE  = 10.0         -- регистр W → мм (0.1 мм)

-- =====================  ТОЧКИ / ТАЙМИНГИ  =========================
local Z_PICK   = -130          -- высота захвата
SPD_MOVE       = 60            -- % скорость (ГЛОБАЛ: меняется настройкой с ПК)
local GRIP_S   = 2             -- отстой захвата, c
local DO_GRIP  = 1             -- DO захвата
local POSTURE  = {0,0,0,0,0,0,0,4}
-- Домашняя позиция по умолчанию (используется и в SetGlobalPoint, и при инициализации
-- CFG-регистров на старте — иначе handle_config прочитает мусор и улетит в (0,0,0)).
local HOME_X0, HOME_Y0, HOME_Z0 = 300, -210, -40
-- Аргументы 4-axis: (Point, Name, X, Y, Z, RZ, Hand, UF, TF, JRC). Hand=1 → ЛЕВАЯ рука.
SetGlobalPoint(90, "GL_HOME",  HOME_X0, HOME_Y0, HOME_Z0, 0, 1, 0, 0, POSTURE)
SetGlobalPoint(91, "GL_PLACE", 450, -300, -90,    0, 1, 0, 0, POSTURE)
-- GL_PICK ОБЪЯВЛЯЕМ здесь (координаты-заглушка); в Motion меняем только X/Y через WritePoint.
SetGlobalPoint(80, "GL_PICK",  300, -210, Z_PICK, 0, 1, 0, 0, POSTURE)

-- =====================  КОНФИГУРАЦИЯ RS-485 / ПРИВОД  ==============
local PORT  = 1                -- номер порта робота (для SCM_*)
local SLAVE = 1                -- адрес привода (P14.00)
-- Modbus-регистры INVT GD20
local VFD_REG_CMD    = 0x2000  -- командное слово
local VFD_REG_FREQ   = 0x2001  -- уставка частоты, 0.01 Гц
local CMD_FWD_RUN    = 0x0001  -- пуск вперёд
local CMD_REV_RUN    = 0x0002  -- пуск назад
local CMD_STOP       = 0x0005  -- стоп
local CMD_FAULT_RST  = 0x0007  -- сброс ошибки
local VFD_REG_STATUS = 0x2100  -- 0x2100 состояние (1=впер,2=назад,3=стоп,4=авария), 0x2103 код ошибки
local VFD_STAT_CNT   = 4
local VFD_REG_MON    = 0x3001  -- 0x3001 частота×100, 0x3002 шина DC В, 0x3004 ток×10
local VFD_MON_CNT    = 5
local STAT_FWD = 1
local STAT_REV = 2
-- Параметры порта RS-485 (Free Port)
local RS485_RATE     = 0x2     -- 19200 (0:4800 1:9600 2:19200 3:38400 4:57600 5:115200)
local RS485_PROTOCOL = 0xD     -- 8E1 freeport (совпадает с 8E1 RTU привода)
local RS485_MODE     = 0x11    -- Modbus Master + RS-485
local RX_TRIES       = 40      -- попыток приёма (×5 мс ≈ 200 мс макс.)

-- =====================  ОБЩЕЕ СОСТОЯНИЕ (глобалы)  =================
have_job = false               -- занят ли робот заданием (делят Motion/Mirror)
heartbeat   = 0
comm_errors = 0


-- =====================  ИНИЦИАЛИЗАЦИЯ CVT  =========================
-- ⚠️ БЕЗ CVT_Initialization функции CVT_GetEncoderPulseCount/CVT_VelIn = -1.
local function initCVT()
  CVT_ChangeMotion()
  local CVID = CV
  CVT_SelectMode(CVID, 2)                          -- 1:со зрением 2:без зрения
  CVT_SetTriggerMode(CVID, 2)                      -- 1:DO trigger 2:DI sensor trigger

  local cvtFactor_num = 144473
  local cvtFactor_den = 1000
  local interval      = 10                         -- Encoder AMF window (ms)
  local trans_ccd_x, trans_ccd_y, rotat_ccd_c = 0, 0, 0
  local vuPix2UmNum, vuPix2UmDen = 10, 1
  local vuAgRatioNum, vuAgRatioDen = 10, 1
  local vuXYExchgFlag = 0
  local cmpstVectorX, cmpstVectorY, cmpstVectorZ = 0, -1000, 0  -- лента в −Y
  local srcType, srcIdx = 1, 1
  local cvtUFIdx = 1
  local NGZoneRadius = 20000                       -- um
  local robotTrigLinePX, robotTrigLinePY = 334631, -381077
  local robotTrigLine = CVT_CalRobotTrigLine(robotTrigLinePX, robotTrigLinePY, cmpstVectorX, cmpstVectorY)
  local zoneEndPX, zoneEndPY = 334631, -200000
  local zoneEndLine = CVT_CalZoneEndLine(zoneEndPX, zoneEndPY, cmpstVectorX, cmpstVectorY)
  local cvtuIdx = 1
  local CV_instSlotIdx = 1
  local instType, instIdx = 2, 1
  cvtFactor_den = cvtFactor_den * interval         -- den *= interval
  local vuIdx = 1
  local CRotatSwFlag = 0
  CVT_SetUserDefineDI(1, 2)

  CVT_Initialization(cvtuIdx, instType, instIdx, srcType, srcIdx,
    cvtFactor_num, cvtFactor_den, interval, cmpstVectorX, cmpstVectorY, cmpstVectorZ, cvtUFIdx,
    trans_ccd_x, trans_ccd_y, rotat_ccd_c, vuIdx, vuPix2UmNum, vuPix2UmDen, vuAgRatioNum, vuAgRatioDen,
    vuXYExchgFlag, CRotatSwFlag, NGZoneRadius, zoneEndLine, robotTrigLine, CV_instSlotIdx)
end

-- =====================  СЫРОЙ Modbus-RTU (Free Port)  ===============
-- XOR 16-бит без побитовых операторов (любая версия Lua).
local function xor16(a, b)
  local res, bit = 0, 1
  for _ = 0, 15 do
    if (a % 2) ~= (b % 2) then
      res = res + bit
    end
    a = math.floor(a / 2)
    b = math.floor(b / 2)
    bit = bit * 2
  end
  return res
end

-- CRC16 Modbus (бит-за-битом). s = строка байтов.
local function crc16(s)
  local crc = 0xFFFF
  for i = 1, #s do
    crc = xor16(crc, string.byte(s, i))
    for _ = 1, 8 do
      if (crc % 2) == 1 then
        crc = xor16(math.floor(crc / 2), 0xA001)
      else
        crc = math.floor(crc / 2)
      end
    end
  end
  return crc
end

-- Добавить CRC (младший байт первым) к телу кадра.
local function with_crc(body)
  local c = crc16(body)
  return body .. string.char(c % 256, math.floor(c / 256))
end

-- Транзакция: слить буфер, отправить req, накопить ответ до expected байт/таймаута.
local function txn(req, expected)
  for _ = 1, 5 do
    SCM_Rx(PORT)                 -- слить мусор
  end
  SCM_Tx(PORT, req)
  local buf = ""
  for _ = 1, RX_TRIES do
    local valid, data = SCM_Rx(PORT)
    if valid == 0 and type(data) == "string" and #data > 0 then
      buf = buf .. data
    end
    if #buf >= expected then
      break
    end
    DELAY(0.005)
  end
  return buf
end

-- Проверка CRC кадра, начинающегося с позиции i, с n байтами до CRC.
local function frame_crc_ok(buf, i, n)
  local sub = string.sub(buf, i, i + n - 1)
  local c = crc16(sub)
  return string.byte(buf, i + n) == (c % 256)
     and string.byte(buf, i + n + 1) == math.floor(c / 256)
end

-- FC03: чтение qty holding-регистров. Возвращает таблицу значений или nil.
local function mb_read(addr, qty)
  local req = with_crc(string.char(
    SLAVE, 0x03, math.floor(addr / 256), addr % 256,
    math.floor(qty / 256), qty % 256))
  local buf = txn(req, 5 + 2 * qty)
  for i = 1, #buf - 1 do
    local a, f = string.byte(buf, i), string.byte(buf, i + 1)
    if a == SLAVE and f == 0x03 then
      local bc = string.byte(buf, i + 2)
      if bc == 2 * qty and #buf >= i + 4 + bc and frame_crc_ok(buf, i, 3 + bc) then
        local out = {}
        for k = 0, qty - 1 do
          out[#out + 1] = string.byte(buf, i + 3 + 2 * k) * 256
                        + string.byte(buf, i + 4 + 2 * k)
        end
        return out
      end
    elseif a == SLAVE and f == 0x83 then
      return nil                 -- исключение привода
    end
  end
  return nil                     -- нет валидного кадра
end

-- FC06: запись одного регистра. Возвращает true при эхо-подтверждении.
local function mb_write(addr, value)
  local req = with_crc(string.char(
    SLAVE, 0x06, math.floor(addr / 256), addr % 256,
    math.floor(value / 256), value % 256))
  local buf = txn(req, 8)
  for i = 1, #buf - 1 do
    if string.byte(buf, i) == SLAVE and string.byte(buf, i + 1) == 0x06 then
      return true
    end
  end
  return false
end

-- =====================  ДРАЙВЕР VFD  ================================
local last_cmd  = nil
local last_freq = nil

local function desired_cmd(run, dir)
  if not run then
    return CMD_STOP
  end
  if dir == 1 then
    return CMD_REV_RUN
  end
  return CMD_FWD_RUN
end

local function vfd_reset_fault()
  mb_write(VFD_REG_CMD, CMD_FAULT_RST)
  DELAY(0.05)
end

-- Опрос: состояние+ошибка (0x2100..0x2103) и мониторинг (0x3001..0x3005).
local function vfd_poll()
  local s = mb_read(VFD_REG_STATUS, VFD_STAT_CNT)
  if not s then
    return nil
  end
  local m = mb_read(VFD_REG_MON, VFD_MON_CNT)
  if not m then
    return nil
  end
  local state = s[1]
  return {
    state    = state,
    fault    = s[4],
    running  = (state == STAT_FWD or state == STAT_REV),
    out_freq = m[1],
    bus_v    = m[2],
    current  = m[4],
  }
end

-- Зеркало статуса привода → регистры для ПК (0x1210..0x1217).
local function publish_status(p)
  heartbeat = (heartbeat + 1) % 32767
  MultiWriteModbus(REG_ST_BASE, ST_BLOCK_CNT, "W", {
    p.running and 1 or 0,   -- 0x1210
    p.out_freq or 0,        -- 0x1211
    p.current  or 0,        -- 0x1212
    p.bus_v    or 0,        -- 0x1213
    p.fault    or 0,        -- 0x1214
    p.state    or 0,        -- 0x1215
    heartbeat,              -- 0x1216
    comm_errors,            -- 0x1217
  })
end

local function publish_comm_error()
  comm_errors = (comm_errors + 1) % 32767
  WriteModbus(REG_ST_COMM_ERR, "W", comm_errors)
end

-- =====================  ОБРАБОТЧИКИ МАРКЕРОВ  ======================
-- Маркер «команда ПЧ»: уставки от ПК (0x1200..0x1203) → привод по RS-485.
local function handle_vfd()
  local c = MultiReadModbus(REG_CMD_RUN, 4, "W")    -- RUN, DIR, FREQ, RESET
  if not c or #c < 4 then
    return
  end
  local run, dir, freq, reset = (c[1] == 1), c[2], c[3], c[4]

  if reset == 1 then
    vfd_reset_fault()
    WriteModbus(REG_CMD_RESET, "W", 0)
    last_cmd = nil
  end
  if freq ~= last_freq then
    if mb_write(VFD_REG_FREQ, freq) then
      last_freq = freq
    end
  end
  local want = desired_cmd(run, dir)
  if want ~= last_cmd then
    if mb_write(VFD_REG_CMD, want) then
      last_cmd = want
    end
  end
end

-- Маркер «параметры робота»: скорость + домашняя позиция. Применяем только в простое.
local function handle_config()
  local spd = ReadModbus(REG_CFG_SPD, "W")
  if spd and spd >= 1 and spd <= 100 then
    SPD_MOVE = spd
  end
  -- домашняя позиция GL_HOME (точка 90) — меняем только X/Y/Z, поза прежняя.
  -- CFG-регистры инициализированы на старте дефолтом → мусора не будет; nil-guard на всякий.
  local hx = ReadModbus(REG_CFG_HOME_X, "W")
  local hy = ReadModbus(REG_CFG_HOME_Y, "W")
  local hz = ReadModbus(REG_CFG_HOME_Z, "W")
  if hx and hy and hz then
    WritePoint(90, "X", hx / XY_SCALE)
    WritePoint(90, "Y", hy / XY_SCALE)
    WritePoint(90, "Z", hz / XY_SCALE)
  end
  print("CFG: SPD_MOVE=" .. SPD_MOVE .. " GL_HOME обновлена")
end

-- Аварийный стоп запрошен с ПК?
local function aborted()
  return ReadModbus(REG_ABORT, "W") == 1
end

-- Снять задание: ОТПУСТИТЬ деталь (при аварии важно!), погасить флаг, освободить слот.
local function clear_job()
  DO(DO_GRIP, 0)                 -- иначе при abort после захвата деталь уедет зажатой
  WriteModbus(REG_ABORT, "W", 0)
  have_job = false
  WriteModbus(REG_FREE, "W", 1)
end

-- Маркер «координаты»: приём задания {X,Y,Ecap} и pick-place.
local function handle_job()
  local job_x   = ReadModbus(REG_X, "W") / XY_SCALE
  local job_y   = ReadModbus(REG_Y, "W") / XY_SCALE
  local job_enc = ReadModbus(REG_ECAP, "DW")        -- энкодер на момент кадра (от ПК)
  WriteModbus(REG_JOB_FLAG, "W", 0)                 -- квитируем приём
  WriteModbus(REG_FREE, "W", 0)                     -- больше не свободен
  have_job = true

  -- guard: лента стоит → энкодер = -1 → trav был бы мусором. Бросаем задание.
  local enc_now = CVT_GetEncoderPulseCount(CV)
  if enc_now < 0 then
    have_job = false
    return
  end

  -- сдвиг ленты от кадра до СЕЙЧАС
  local trav = (enc_now - job_enc) * FACTOR_MM
  local px = job_x + UX * trav
  local py = job_y + UY * trav

  -- обратная связь на ПК: что принято и что вычислено (команда last)
  WriteModbus(REG_ECHO_X, "W", job_x * XY_SCALE)
  WriteModbus(REG_ECHO_Y, "W", job_y * XY_SCALE)
  WriteModbus(REG_PX,     "W", px * XY_SCALE)
  WriteModbus(REG_PY,     "W", py * XY_SCALE)
  WriteModbus(REG_TRAV,   "W", trav * XY_SCALE)

  -- меняем ТОЛЬКО координаты заранее объявленной точки 80 (GL_PICK)
  WritePoint(80, "X", px)
  WritePoint(80, "Y", py)

  -- между шагами проверяем аварию: Mirror зовёт MotionStop → блок. вызов прерывается
  CVT_VelIn(CV)
  MovL("GL_PICK", SPD(SPD_MOVE))                    -- подвод над объектом
  if aborted() then CVT_VelOut(CV); clear_job(); return end
  DO(DO_GRIP, 1)
  DELAY(GRIP_S)
  CVT_VelOut(CV)
  if aborted() then clear_job(); return end

  MovP("GL_PLACE", SPD(SPD_MOVE))                   -- укладка
  if aborted() then clear_job(); return end
  DO(DO_GRIP, 0)
  DELAY(GRIP_S)
  MovP("GL_HOME", SPD(SPD_MOVE))                    -- домой

  clear_job()                                       -- снова свободен
end

-- =====================  ПОТОК 2: MIRROR (проходной)  ==============
-- Зеркалит живой энкодер (ПК читает его в кадре как E_capture) + аварийный стоп.
-- Без while/WAIT/DELAY → REG_ENC всегда свежий. MotionStop из Task2 разрешён
-- (мануал RL стр. 1-51) — прерывает движение, которое исполняет Motion (Task1).
function Mirror()
  WriteModbus(REG_ENC, "DW", CVT_GetEncoderPulseCount(CV))
  if ReadModbus(REG_ABORT, "W") == 1 then
    MotionStop()                                    -- decel = max (выставлен глобально) → почти мгновенно
  end
end

-- =====================  СВЯЗЬ (без движения)  =====================
-- Все опросы и команды, которым НЕ нужно двигать роботом: маркеры ПЧ/настроек,
-- блокирующий RS-485 к приводу, аварийный флаг, статус привода. По одному
-- действию за вызов. Возвращает true ТОЛЬКО если ждёт CVT-задание (надо ехать).
local function communication()
  -- 1) команда частотнику?
  if ReadModbus(REG_VFD_FLAG, "W") == 1 then
    WriteModbus(REG_VFD_FLAG, "W", 0)               -- квитируем сразу
    handle_vfd()
    return false
  end

  -- 2) параметры робота? (только когда нет активного задания)
  if not have_job and ReadModbus(REG_CFG_FLAG, "W") == 1 then
    WriteModbus(REG_CFG_FLAG, "W", 0)
    handle_config()
    return false
  end

  -- 3) новое CVT-задание? → передаём управление движению (флаг гасит handle_job)
  if ReadModbus(REG_JOB_FLAG, "W") == 1 then
    return true
  end

  -- 4) простой: гасим зависший флаг аварии (двигать нечего), опрос привода, «свободен»
  if ReadModbus(REG_ABORT, "W") == 1 then
    WriteModbus(REG_ABORT, "W", 0)
  end
  local p = vfd_poll()
  if p then
    publish_status(p)
  else
    publish_comm_error()
  end
  WriteModbus(REG_FREE, "W", 1)
  return false
end

-- =====================  ПОТОК 1: MOTION  ==========================
-- Единственная задача, которой можно двигаться. Сначала — связь/опросы
-- (communication), и только если ждёт задание — собственно движение.
function Motion()
  if communication() then
    handle_job()
  end
end


-- =====================  СТАРТ  =====================================
Override(25)      -- глобально
SpdJ(100)
SpdL(2000)        -- макс линейная скорость
AccL(25000)       -- макс ускорение
DecL(25000)       -- макс замедление

initCVT()                                           -- полная инициализация CVT-группы

-- Порт → Free Port: 19200, 8E1, Master+RS485, очистить RX.
local rtn = SCM_FreePort(PORT, RS485_RATE, RS485_PROTOCOL, RS485_MODE, 0x1, 0x0, 0x0, 0x00, 0x00)
print("SCM_FreePort rtn = " .. tostring(rtn) .. " (0 = ок)")
DELAY(0.1)

mb_write(VFD_REG_CMD, CMD_STOP)                     -- безопасный старт: привод стоп
mb_write(VFD_REG_FREQ, 0)
last_cmd  = CMD_STOP
last_freq = 0

RobotServoOn()

-- обнулить ВСЕ командные регистры и маркеры
WriteModbus(REG_JOB_FLAG,  "W", 0)
WriteModbus(REG_ABORT,     "W", 0)
WriteModbus(REG_VFD_FLAG,  "W", 0)
WriteModbus(REG_CFG_FLAG,  "W", 0)
WriteModbus(REG_CMD_RUN,   "W", 0)
WriteModbus(REG_CMD_DIR,   "W", 0)
WriteModbus(REG_CMD_FREQ,  "W", 0)
WriteModbus(REG_CMD_RESET, "W", 0)
-- инициализировать CFG-регистры домашней позиции дефолтом (иначе handle_config улетит в 0)
WriteModbus(REG_CFG_SPD,    "W", SPD_MOVE)
WriteModbus(REG_CFG_HOME_X, "W", HOME_X0 * XY_SCALE)
WriteModbus(REG_CFG_HOME_Y, "W", HOME_Y0 * XY_SCALE)
WriteModbus(REG_CFG_HOME_Z, "W", HOME_Z0 * XY_SCALE)
have_job = false
WriteModbus(REG_FREE, "W", 1)                       -- стартуем «свободны»

MovP("GL_HOME", SPD(SPD_MOVE))

print("cvt_universal: старт")
print("enc=" .. CVT_GetEncoderPulseCount(CV))

AuxTasksAdd(Motion, Mirror)                         -- Motion первым (только он двигается)
while 1 do
  AuxTasks()
end

-- =====================================================================
--  РАСШИРЕНИЕ:
--   • Новые настройки робота — дописать регистры с 0x1305, читать в handle_config.
--   • Мгновенный стоп конвейера на ходу — добавить ветку с MotionStop в Motion
--     ДО проверки задания (прервёт текущее движение).
-- =====================================================================
