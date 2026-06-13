-- =====================================================================
--  Delta SCARA · DRAStudio (Lua/RL) — мост «ПК ⇄ робот ⇄ INVT GD20».
--  Связь с приводом — СЫРОЙ Modbus-RTU через Free Port (SCM_Tx/SCM_Rx),
--  проверено на железе. Сами строим кадры FC03/FC06 + CRC16, поэтому
--  НЕ зависим ни от RSmaster, ни от настройки протокола в GUI проекта.
--
--    ПК (Python, pymodbus)  ──Modbus TCP (master)──▶  Робот (:502, slave)
--                                                        │ внутр. регистры
--                                                        ▼
--    Робот (этот скрипт) ──RS-485 Modbus RTU (Free Port)──▶ INVT GD20
--
--  ПК НЕ говорит с приводом напрямую: ПК пишет уставки во внутренние
--  Modbus-регистры робота (0x1200…) по TCP, робот их читает и шлёт в привод;
--  ответ привода зеркалит в 0x1210… — ПК читает оттуда.
--
--  ─────────────────────────────────────────────────────────────────
--  НАСТРОЙКА ПРИВОДА INVT GD20 (на самом VFD, один раз):
--    P00.01 = 2   — команды RUN = связь (Modbus)
--    P00.06 = 8   — источник частоты A = связь (Modbus)
--    P14.00 = 1   — адрес привода (= SLAVE ниже)
--    P14.01 = 4   — 19200 бод
--    P14.02 = 1   — 8/E/1 RTU
--  Порт RS-485 робота настраивает САМ скрипт (SCM_FreePort) — GUI не нужен.
--  Полярность A/B: 485+ ↔ A+, 485- ↔ B-, плюс общий GND.
--  ─────────────────────────────────────────────────────────────────
-- =====================================================================

-- =====================  КОНФИГУРАЦИЯ  ================================
local PORT  = 1                  -- номер порта робота (для SCM_*)
local SLAVE = 1                  -- адрес привода (P14.00)

-- ----- Modbus-регистры INVT GD20 -----
local VFD_REG_CMD    = 0x2000    -- командное слово (перечисление)
local VFD_REG_FREQ   = 0x2001    -- уставка частоты, 0.01 Гц
local CMD_FWD_RUN    = 0x0001    -- пуск вперёд
local CMD_REV_RUN    = 0x0002    -- пуск назад
local CMD_STOP       = 0x0005    -- стоп
local CMD_FAULT_RST  = 0x0007    -- сброс ошибки

local VFD_REG_STATUS = 0x2100    -- 0x2100 состояние (1=впер,2=назад,3=стоп,4=авария), 0x2103 код ошибки
local VFD_STAT_CNT   = 4
local VFD_REG_MON    = 0x3001    -- 0x3001 частота(×100), 0x3002 шина DC(В), 0x3003 Uвых(В), 0x3004 ток(×10), 0x3005 об/мин
local VFD_MON_CNT    = 5
local STAT_FWD = 1
local STAT_REV = 2

-- ----- Внутренние регистры робота (Modbus TCP с ПК), все «W» = 16 бит -----
-- ПК ПИШЕТ команды:
local REG_CMD_RUN   = 0x1200     -- 0 = стоп, 1 = пуск
local REG_CMD_DIR   = 0x1201     -- 0 = вперёд, 1 = назад
local REG_CMD_FREQ  = 0x1202     -- частота ×100 (0.01 Гц)
local REG_CMD_RESET = 0x1203     -- 1 = сброс ошибки
local CMD_BLOCK_CNT = 4

-- Робот ПИШЕТ статус (блок 0x1210..0x1217):
local REG_ST_BASE     = 0x1210
local ST_BLOCK_CNT    = 8
local REG_ST_COMM_ERR = 0x1217
--   0x1210 RUN | 0x1211 частота×100 | 0x1212 ток×10 | 0x1213 шина В
--   0x1214 код ошибки | 0x1215 сырое состояние | 0x1216 heartbeat | 0x1217 счётчик ошибок RS485

local LOOP_DELAY_S = 0.05

-- ----- Параметры порта RS-485 (Free Port) -----
local RS485_RATE     = 0x2       -- 19200 (0:4800 1:9600 2:19200 3:38400 4:57600 5:115200)
local RS485_PROTOCOL = 0xD       -- 8E1 freeport (совпадает с 8E1 RTU привода)
local RS485_MODE     = 0x11      -- Modbus Master + RS-485
local RX_TRIES       = 40        -- попыток приёма (×5 мс ≈ 200 мс макс.)

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

-- =====================  МОСТ К ПК  ==================================
local last_cmd  = nil
local last_freq = nil
local heartbeat = 0
local comm_errors = 0

local function read_pc_commands()
  local c = MultiReadModbus(REG_CMD_RUN, CMD_BLOCK_CNT, "W")
  if not c or #c < CMD_BLOCK_CNT then
    return nil
  end
  return { run = (c[1] == 1), dir = c[2], freq = c[3], reset = c[4] }
end

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

-- =====================  ИНИЦИАЛИЗАЦИЯ  ==============================
local function init()
  -- Порт → Free Port: 19200, 8E1, Master+RS485, очистить RX.
  local rtn = SCM_FreePort(PORT, RS485_RATE, RS485_PROTOCOL, RS485_MODE, 0x1, 0x0, 0x0, 0x00, 0x00)
  print("SCM_FreePort rtn = " .. tostring(rtn) .. " (0 = ок)")
  DELAY(0.1)

  mb_write(VFD_REG_CMD, CMD_STOP)     -- безопасный старт: стоп
  mb_write(VFD_REG_FREQ, 0)
  WriteModbus(REG_CMD_RUN,   "W", 0)  -- обнулить команды ПК
  WriteModbus(REG_CMD_DIR,   "W", 0)
  WriteModbus(REG_CMD_FREQ,  "W", 0)
  WriteModbus(REG_CMD_RESET, "W", 0)
  last_cmd  = CMD_STOP
  last_freq = 0
end

-- =====================  ГЛАВНЫЙ ЦИКЛ  ==============================
local function main()
  init()
  while true do
    -- 1) уставки от ПК → привод
    local cmd = read_pc_commands()
    if cmd then
      if cmd.reset == 1 then
        vfd_reset_fault()
        WriteModbus(REG_CMD_RESET, "W", 0)
        last_cmd = nil
      end
      if cmd.freq ~= last_freq then
        if mb_write(VFD_REG_FREQ, cmd.freq) then
          last_freq = cmd.freq
        end
      end
      local want = desired_cmd(cmd.run, cmd.dir)
      if want ~= last_cmd then
        if mb_write(VFD_REG_CMD, want) then
          last_cmd = want
        end
      end
    end

    -- 2) статус привода → зеркало для ПК
    local p = vfd_poll()
    if p then
      publish_status(p)
    else
      publish_comm_error()
    end

    DELAY(LOOP_DELAY_S)
  end
end

main()
