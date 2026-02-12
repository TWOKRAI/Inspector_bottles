-- start = false 
-- drop = false

-- speed_arm = 5000

-- x = 0
-- y = 0
-- iterator = 0

-- y_delta = 0
-- delta = 0
-- delta_back = 0
-- compenc = 0
-- receive_time = 0

-- servo_enable = false

-- Hand = 1
-- UF = 0
-- TF = 0
-- JRC = {0,0,0,1,0,0,0,4}

-- SetGlobalPoint ("P1", 200, -300, -170, 18.047, 1, UF, TF, JRC)

-- SetGlobalPoint ("P12Right", 120, -270, -170, 18.047, 1, UF, TF, JRC)
-- SetGlobalPoint ("DropRightTop", -128, -270, -160, 18.047, 1, UF, TF, JRC)
-- SetGlobalPoint ("DropRight", -128, -270, -170, 18.047, 1, UF, TF, JRC)

-- SetGlobalPoint ("P12Left", 120, 270, -170, 18.047, 0, UF, TF, JRC)
-- SetGlobalPoint ("DropLeftTop", -114, 270, -160, 18.047, 0, UF, TF, JRC)
-- SetGlobalPoint ("DropLeft", -114, 270, -170, 18.047, 0, UF, TF, JRC)

-- SetGlobalPoint ("HOME", 300, -300, -170, 18.047, 1, UF, TF, JRC)


-- function servo_on(signal)
--     if servo_enable == false and signal == 'True' then
--             RobotServoOn()
--             servo_enable = true
--         end

--         if servo_enable == true and signal == 'False' then
--             RobotServoOff()
--             servo_enable = false
--         end
-- end


-- function reconnectSocket()
--     SocketTest = SocketClass("192.168.1.90", 502, ",", "\r\n", nil, 0.01, 10)
--     --SocketTest:Send('ready')
-- end


-- hand = 1
-- delta_hand = 0
    
-- function change_hand(y)
--     if hand == 1 then
--         if y >= 120 then
--             WritePoint("P1", "H", 0)
--             hand = 0
--             delta_hand = 70
--         end
--     else
--         if y <= -210 then
--             WritePoint("P1", "H", 1)
--             hand = 1
--             delta_hand = 70
--         end
--     end
-- end


-- function dropping()
-- 	if hand == 1 then
--         MovP("DropRight", PASS())
--         MovP("DropRightTop")
--         --MovP("P12Right", PASS())
--     else
--         MovP("DropLeft", PASS())
--         MovP("DropLeftTop")
--         --MovP("P12Left", PASS())
--         --MovP("P12Left")
--     end 
-- end


-- reconnectSocket()

-- SpdJ(100)
-- AccJ(100)
-- DecJ(100)
-- SpdL(5000)
-- AccL(25000)
-- DecL(25000)

-- Accur("MAXROUGH")
-- SetOverlapTime(100)	

-- RobotServoOff()


-- while true do
--     get_ready = 0
--     time_move_s = 0
--     y_shift = 0
    
--     local status, rets = pcall(SocketTest.Receive, SocketTest)
                    
--     if status == False then 
--     	reconnectSocket()
--     end

--     if rets and type(rets) == "table" then
--     	signal_servo = rets[1]
--         shift = tonumber(rets[3]) or 0
--         speed_conveyor = tonumber(rets[4]) or 1
--         x = tonumber(rets[5]) or 0
--         y = tonumber(rets[6]) or 0
--         lengh = tonumber(rets[7])or 0
--         back = tonumber(rets[8])or 0
      
--         servo_on(signal_servo)

--         if servo_enable == true then
--         	if start ~= true then
--                 MovP("HOME")
--                 start = true
--             end
        	
--             position = tonumber(rets[2])

--             if position == 0 then
--                 if x ~= 0 and y ~= 0 then
--                 	WritePoint("P1", "X", x)
--                 	WritePoint("P2", "Z", -170)
                	
--                 	x_real = RobotX()
--                 	y_real = RobotY()
               
--                     hypotenuse = math.sqrt(math.pow((x_real - x), 2) + math.pow((y_real - y), 2))
--                     time_hypo = hypotenuse / speed_arm
--                     delta = time_hypo * speed_conveyor * lengh / 100
                    
--                     if shift > 0 then
--                         compenc = delta / shift * 1000
--                     else
--                         compenc = 0
--                     end

--                     y_delta = y + delta + compenc + delta_back
                    
--                     change_hand(y_delta)
                    
--                     y_delta = y_delta + delta_hand
--                     delta_hand = 0   
                    
--                     hypotenuse_2 = math.sqrt(math.pow(x, 2) + math.pow(y_delta , 2))
                    
--                     if x >= 140 and y_delta <= 490 and hypotenuse_2 < 590 then                         
--                         WritePoint("P1", "Y", y_delta) 
                        
--                         if lengh > 0 and y_delta <= -200 then
--                         	MovP("P1")
--                             WritePoint("P1", "Y", y_delta + lengh)
--                             MovL("P1", SPD(speed_conveyor))
--                             WritePoint("P1", "Y", y_delta + lengh + 30)
--                         else
--                             MovP("P1", PASS())
--                         end

--                         WritePoint("P1", "Z", -200)
--                         MovP("P1", PASS())
                           
--                         if iterator == 0 then
--                             WritePoint("P1", "Z", -170)
--                         elseif iterator == 1 then 
--                             WritePoint("P1", "Z", -167)
--                         end
                        
--                         MovP("P1", PASS())

--                         get_ready = 1

--                         iterator = iterator + 1
                        
--                         delta_back = 0

--                         if iterator > 1 then
--                         	if y_delta >= 390 then 
--                         		WritePoint("P1", "Y", 320)
--                         		MovP("P1", PASS())
--                         	end
                        	
--                         	dropping()
--                             iterator = 0
--                             delta_back = back
--                         end
--                     else
--                         get_ready = 2
--                     end
--                 else
--                     if iterator == 1 then 
--                         dropping()
--                         iterator = 0
--                     end
--                 end

--             elseif position == 1 then
--                 MovP("HOME", PASS())
--             elseif position == 2 then
--                 MovP("HOME", PASS())
--             end         
--         end

--         if rets[7] == "True" then
--             DO(1, "ON")
--         else
--             DO(1, "OFF")
--         end

--         if rets[8] == "True" then
--             DO(2, "ON")
--         else
--             DO(2, "OFF")
--         end
           
--         local data_parts = {
--             get_ready,
--             x,
--             y,
--             y_delta,
--             delta,
--             compenc,
--             delta_back
--         }
    
--         local data_to_send = table.concat(data_parts, ",")
--         SocketTest:Send(data_to_send)
        
--         x = 0
--         y = 0
--         rets = 'none'
--     end
-- end

-- RobotServoOff()





start = false 
drop = false

speed_arm = 5000

x = 0
y = 0
iterator = 0

y_delta = 0
delta = 0
delta_back = 0
compenc = 0
receive_time = 0
delta_angel = 0
delta_ret = -50

servo_enable = false

Hand = 1
UF = 0
TF = 0
JRC = {0,0,0,1,0,0,0,4}

SetGlobalPoint ("P1", 200, -300, -170, 18.047, 1, UF, TF, JRC)

SetGlobalPoint ("DropRightTop", -120, -270, -147, 18.047, 1, UF, TF, JRC)
SetGlobalPoint ("DropRight", -120, -270, -165, 18.047, 1, UF, TF, JRC)
SetGlobalPoint ("P12Right", 120, -270, -165, 18.047, 1, UF, TF, JRC)

SetGlobalPoint ("DropLeftTop", -120, 270, -147, 18.047, 0, UF, TF, JRC)
SetGlobalPoint ("DropLeft", -120, 270, -165, 18.047, 0, UF, TF, JRC)
SetGlobalPoint ("P12Left", 120, 270, -165, 18.047, 0, UF, TF, JRC)

SetGlobalPoint ("HOME", 300, -300, -170, 18.047, 1, UF, TF, JRC)


function servo_on(signal)
    if servo_enable == false and signal == 'True' then
            RobotServoOn()
            servo_enable = true
        end

        if servo_enable == true and signal == 'False' then
            RobotServoOff()
            servo_enable = false
        end
end


function reconnectSocket()
    SocketTest = SocketClass("192.168.1.90", 502, ",", "\r\n", nil, 0.01, 1)
    --SocketTest:Send('ready')
    RobotServoOn()
    DELAY(1)
    RobotServoOff()
end

hand = 1
delta_hand = 0
    
function change_hand(y)
    if hand == 1 then
        if y >= 0 then
            WritePoint("P1", "H", 0)
            hand = 0
            --delta_hand = 75
        end
    else
        if y < 0 then
            WritePoint("P1", "H", 1)
            hand = 1
            --delta_hand = 75
        end
    end
end


function dropping()
	if hand == 1 then
        MovP("DropRight", PASS())
        MovP("DropRightTop")
        MovP("P12Right", PASS())
    else
        MovP("DropLeft", PASS())
        MovP("DropLeftTop")
        MovP("P12Left", PASS())
    end 
end


function calculateRotationAngle(x1, y1, x2, y2)
    -- Вычисляем начальный угол для первой точки
    local theta1 = math.atan2(y1, x1)

    -- Вычисляем конечный угол для второй точки
    local theta2 = math.atan2(y2, x2)

    -- Вычисляем разницу углов
    local deltaTheta = theta2 - theta1

    -- Нормализуем угол в диапазоне [-π, π]
    deltaTheta = (deltaTheta + math.pi) % (2 * math.pi) - math.pi

    -- Преобразуем радианы в градусы
    local deltaThetaDegrees = deltaTheta * 180 / math.pi

    return ABS(deltaThetaDegrees)
end



reconnectSocket()

SpdJ(100)
AccJ(100)
DecJ(100)
SpdL(5000)
AccL(25000)
DecL(25000)

Accur("MAXROUGH")
SetAccur(1, 40000) 
SetAccur(2, 40000) 
SetOverlapTime(100)	

RobotServoOff()


while true do
    get_ready = 0
    time_move_s = 0
    y_shift = 0
--[[
        
    if rets == nil then 
    	reconnectSocket()
    end
    ]]
    
    rets, err = SocketTest:Receive()
--[[
                        local status, rets = pcall(SocketTest.Receive, SocketTest)
                                   ]]
     


    if rets and type(rets) == "table" then
    	TimerOn()
    	signal_servo = rets[1]
        shift = tonumber(rets[3]) or 0
        speed_conveyor = tonumber(rets[4]) or 1
        x = tonumber(rets[5]) or 0
        y = tonumber(rets[6]) or 0
        lengh = tonumber(rets[7])or 0
        back = tonumber(rets[8])or 0
      
        servo_on(signal_servo)

        if servo_enable == true then
        	if start ~= true then
                MovP("HOME")
                start = true
            end
        	
            position = tonumber(rets[2])

            if position == 0 then
                if x ~= 0 and y ~= 0 then
                	WritePoint("P1", "X", x)
                	WritePoint("P2", "Z", -165)
                	
                	x_real = RobotX()
                	y_real = RobotY()
               
                    hypotenuse = math.sqrt(math.pow((x_real - x), 2) + math.pow((y_real - y), 2))
                    time_hypo = hypotenuse / speed_arm
                    delta = time_hypo * speed_conveyor * lengh / 100
                    
                    y_delta = y + delta + shift + delta_back 
                    delta_ret = 0
                    
                    change_hand(y_delta)
                    --delta_hand = calculateRotationAngle(x, y_delta, x_real, y_real)       
                    
                    --y_delta = y_delta + delta_hand
                    
                    hypotenuse_2 = math.sqrt(math.pow(x, 2) + math.pow(y_delta , 2))
  
                    if x >= 140 and y_delta <= 450 and hypotenuse_2 < 590 then                         
                        WritePoint("P1", "Y", y_delta) 
                        MovP("P1")
                        timer = TimerRead()
                        
                        delta_conv = timer * speed_conveyor / 1000
                        --y_real2 = RobotY()
                        
                        y_delta2 = y_delta * 2 - y + delta_conv 
                        
                        hypotenuse_3 = math.sqrt(math.pow(x, 2) + math.pow(y_delta2 , 2))
                        
                        if hypotenuse_3 < 590 then  
                            WritePoint("P1", "Y", y_delta2 + delta_ret) 
                            MovP("P1", PASS())
                            
--[[
                                                if lengh > 0 and y_delta <= -200 then
                        	MovP("P1")
                            WritePoint("P1", "Y", y_delta + lengh)
                            MovL("P1", SPD(speed_conveyor))
                            WritePoint("P1", "Y", y_delta + lengh + 30)
                        else
                            MovP("P1")
                            --MovP("P1")
                        end
                        ]]
                        
                            WritePoint("P1", "Z", -195)
                            MovP("P1", PASS())
                               
                            if iterator == 0 then
                                WritePoint("P1", "Z", -165)
                            elseif iterator == 1 then 
                                WritePoint("P1", "Z", -165)
                            end
                            
                            MovP("P1", PASS())

                            get_ready = 1

                            iterator = iterator + 1
                            
                            delta_back = 0

                            if iterator > 1 then
                                if y_delta >= 390 then 
                                    WritePoint("P1", "Y", 320)
                                    MovP("P1", PASS())
                                end
                                
                                dropping()
                                iterator = 0
                                delta_back = back
                            end
                        else
                            get_ready = 2
                        end
                    else
                        get_ready = 2
                    end
                else
                    if iterator == 1 then 
                        dropping()
                        iterator = 0
                    end
                end

            elseif position == 1 then
                MovP("HOME")
            elseif position == 2 then
                MovP("HOME")
            end         
        end

        if rets[7] == "True" then
            DO(1, "ON")
        else
            DO(1, "OFF")
        end

        if rets[8] == "True" then
            DO(2, "ON")
        else
            DO(2, "OFF")
        end
           
        local data_parts = {
            get_ready,
            x,
            y,
            y_delta,
            delta,
            delta_hand
        }
    
        local data_to_send = table.concat(data_parts, ",")
        SocketTest:Send(data_to_send)
        
        x = 0
        y = 0
        rets = 'none'
    else
        if servo_enable == true and RobotX()~= 300 and RobotY()~= 300 then
            MovP("HOME")
            delta_ret = -50
        end
    end
end

RobotServoOff()





start = false 
drop = false


x = 0
y = 0
iterator = 0

y_delta = 0
delta = 0
delta_back = 0
compenc = 0
receive_time = 0
delta_angel = 0
delta_ret = -50

servo_enable = false

Hand = 1
UF = 0
TF = 0
JRC = {0,0,0,1,0,0,0,4}

SetGlobalPoint ("P1", 200, -300, -170, 18.047, 1, UF, TF, JRC)

SetGlobalPoint ("DropRightTop", -120, -270, -147, 18.047, 1, UF, TF, JRC)
SetGlobalPoint ("DropRight", -120, -270, -165, 18.047, 1, UF, TF, JRC)
SetGlobalPoint ("P12Right", 120, -270, -165, 18.047, 1, UF, TF, JRC)

SetGlobalPoint ("DropLeftTop", -120, 270, -147, 18.047, 0, UF, TF, JRC)
SetGlobalPoint ("DropLeft", -120, 270, -165, 18.047, 0, UF, TF, JRC)
SetGlobalPoint ("P12Left", 120, 270, -165, 18.047, 0, UF, TF, JRC)

SetGlobalPoint ("HOME", 300, -300, -170, 18.047, 1, UF, TF, JRC)


function servo_on(signal)
    if servo_enable == false and signal == 'True' then
            RobotServoOn()
            servo_enable = true
        end

        if servo_enable == true and signal == 'False' then
            RobotServoOff()
            servo_enable = false
        end
end


function reconnectSocket()
    SocketTest = SocketClass("192.168.1.90", 502, ",", "\r\n", nil, 0.01, 1)
    --SocketTest:Send('ready')
    RobotServoOn()
    DELAY(1)
    RobotServoOff()
end

hand = 1
delta_hand = 0
    
function change_hand(y)
    if hand == 1 then
        if y >= 0 then
            WritePoint("P1", "H", 0)
            hand = 0
            --delta_hand = 75
        end
    else
        if y < 0 then
            WritePoint("P1", "H", 1)
            hand = 1
            --delta_hand = 75
        end
    end
end


function dropping()
	if hand == 1 then
        MovP("DropRight", PASS())
        MovP("DropRightTop")
        MovP("P12Right", PASS())
    else
        MovP("DropLeft", PASS())
        MovP("DropLeftTop")
        MovP("P12Left", PASS())
    end 
end


function calculateRotationAngle(x1, y1, x2, y2)
    -- Вычисляем начальный угол для первой точки
    local theta1 = math.atan2(y1, x1)

    -- Вычисляем конечный угол для второй точки
    local theta2 = math.atan2(y2, x2)

    -- Вычисляем разницу углов
    local deltaTheta = theta2 - theta1

    -- Нормализуем угол в диапазоне [-π, π]
    deltaTheta = (deltaTheta + math.pi) % (2 * math.pi) - math.pi

    -- Преобразуем радианы в градусы
    local deltaThetaDegrees = deltaTheta * 180 / math.pi

    return ABS(deltaThetaDegrees)
end



reconnectSocket()
speed_arm = 5000


SpdJ(100)
AccJ(100)
DecJ(100)
SpdL(5000)
AccL(25000)
DecL(25000)

Accur("MAXROUGH")
SetAccur(1, 600000) 
SetAccur(2, 600000) 
SetAccur(3, 20000) 
SetAccur(4, 20000) 

SetOverlapTime(100)	


RobotServoOff()


while true do
    get_ready = 0
    time_move_s = 0
    y_shift = 0
--[[
        
    if rets == nil then 
    	reconnectSocket()
    end
    ]]
    
    rets, err = SocketTest:Receive()
--[[
                        local status, rets = pcall(SocketTest.Receive, SocketTest)
                                   ]]
     


    if rets and type(rets) == "table" then
    	TimerOn()
    	signal_servo = rets[1]
        shift = tonumber(rets[3]) or 0
        speed_conveyor = tonumber(rets[4]) or 1
        x = tonumber(rets[5]) or 0
        y = tonumber(rets[6]) or 0
        lengh = tonumber(rets[7])or 0
        back = tonumber(rets[8])or 0
        do1 = rets[9]
        do2 = rets[10]
      
        servo_on(signal_servo)

        if servo_enable == true then
        	if start ~= true then
                MovP("HOME")
                start = true
            end
        	
            position = tonumber(rets[2])

            if position == 0 then
                if x ~= 0 and y ~= 0 then
                	WritePoint("P1", "X", x)
                	WritePoint("P2", "Z", -165)
                	
                	x_real = RobotX()
                	y_real = RobotY()
               
                    hypotenuse = math.sqrt(math.pow((x_real - x), 2) + math.pow((y_real - y), 2))
                    time_hypo = hypotenuse / speed_arm
                    delta = time_hypo * speed_conveyor * lengh / 100
                    
                    y_delta = y + delta + delta_back 
                    delta_ret = 0
                    
                    change_hand(y_delta)
                    --delta_hand = calculateRotationAngle(x, y_delta, x_real, y_real)       
                    
                    --y_delta = y_delta + delta_hand
                    
                    hypotenuse_2 = math.sqrt(math.pow(x, 2) + math.pow(y_delta , 2))
  
                    if x >= 140 and y_delta <= 450 and hypotenuse_2 < 590 then                         
                        WritePoint("P1", "Y", y_delta) 
                        MovP("P1", PASS())
                        MovP("P1")
                        timer = TimerRead()
                        
                        delta_conv = timer * speed_conveyor / 1000
                        --y_real2 = RobotY()
                        
                        delta_conv2 = delta_conv - shift

                        y_delta2 = y_delta * 2 - y + delta_conv2--+ delta_ret
                        
                        hypotenuse_3 = math.sqrt(math.pow(x, 2) + math.pow(y_delta2 , 2))
                        
                        if hypotenuse_3 < 590 then  
                            WritePoint("P1", "Y", y_delta2) 
                            MovP("P1", PASS())
                        
                            WritePoint("P1", "Z", -195)
                            MovP("P1", PASS())
                               
                            if iterator == 0 then
                                WritePoint("P1", "Z", -165)
                            elseif iterator == 1 then 
                                WritePoint("P1", "Z", -165)
                            end
                            
                            MovP("P1", PASS())

                            get_ready = 1

                            iterator = iterator + 1
                            
                            delta_back = 0

                            if iterator > 1 then
                                if y_delta >= 390 then 
                                    WritePoint("P1", "Y", 320)
                                    MovP("P1", PASS())
                                end
                                
                                dropping()
                                iterator = 0
                                delta_back = back
                            end
                        else
                            get_ready = 2
                        end
                    else
                        get_ready = 2
                    end
                else
                    if iterator == 1 then 
                        dropping()
                        iterator = 0
                    end
                end

            elseif position == 1 then
                MovP("HOME")
            elseif position == 2 then
                MovP("HOME")
            end         
        end

        if do1 == "True" then
            DO(1, "ON")
        else
            DO(1, "OFF")
        end

        if do2 == "True" then
            DO(2, "ON")
        else
            DO(2, "OFF")
        end
           
        local data_parts = {
            get_ready,
            x,
            y,
            y_delta,
            delta,
            delta_hand
        }
    
        local data_to_send = table.concat(data_parts, ",")
        SocketTest:Send(data_to_send)
        
        x = 0
        y = 0
        rets = 'none'
    else
        if servo_enable == true and RobotX()~= 300 and RobotY()~= 300 then
            MovP("HOME", PASS())
            delta_ret = -50
        end
    end
end

RobotServoOff()