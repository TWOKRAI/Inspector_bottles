start = false 
drop = false


x = 0
y = 0
iterator = 0

y_delta = 0
delta = 0
back = 0
delta_back = 0
compenc = 0
receive_time = 0
delta_angel = 0
delta_ret = -50
drop = 2

servo_enable = false

Hand = 1
UF = 0
TF = 0
JRC = {0,0,0,1,0,0,0,4}

SetGlobalPoint ("P1", 200, -300, -170, 18.047, 1, UF, TF, JRC)

SetGlobalPoint ("DropRightTop", -120, -270, -147, 18.047, 1, UF, TF, JRC)
SetGlobalPoint ("DropRight", -120, -270, -165, 18.047, 1, UF, TF, JRC)
SetGlobalPoint ("P12Right", 200, -270, -165, 18.047, 1, UF, TF, JRC)
SetGlobalPoint ("R", 300, -300, -170, 18.047, 1, UF, TF, JRC)

SetGlobalPoint ("DropLeftTop", -120, 270, -147, 18.047, 0, UF, TF, JRC)
SetGlobalPoint ("DropLeft", -120, 270, -165, 18.047, 0, UF, TF, JRC)
SetGlobalPoint ("P12Left", 200, 190, -165, 18.047, 0, UF, TF, JRC)
SetGlobalPoint ("L", 473, -50, -170, 18.047, 1, UF, TF, JRC)


SetGlobalPoint ("HOME", 300, -300, -170, 18.047, 1, UF, TF, JRC)
SetGlobalPoint ("OFF", -120, -300, -170, 18.047, 1, UF, TF, JRC)



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



function dropping()
	y_real = RobotY()
	
	if y_real <= -200 then
		if RobotHand() == 0 then 
            WritePoint("P1", "H", 1)
        end
		
        MovP("DropRight", PASS())
        MovP("DropRightTop")
        MovP("P12Right", PASS())
    elseif y_real >= 100 then
    	if RobotHand() == 1 then 
    		WritePoint("P1", "H", 0)
            MovL("L")
        end
    	
        MovP("DropLeft", PASS())
        MovP("DropLeftTop")
        MovP("P12Left", PASS())
    else
        if RobotHand() == 1 then  
            MovP("DropRight", PASS())
            MovP("DropRightTop")
            MovP("P12Right")
        else
            MovP("DropLeft", PASS())
            MovP("DropLeftTop")
            MovP("P12Left", PASS())
        end
    end 
    
    delta_back = back
end


reconnectSocket()
speed_arm = 2000


SpdJ(100)
AccJ(100)
DecJ(100)
SpdL(2000)
AccL(25000)
DecL(25000)

Accur("MAXROUGH")
--SetAccur(1, 100000) 
--SetAccur(2, 100000) 
--SetAccur(3, 20000) 
SetAccur(4, 500000) 

SetOverlapTime(100)	

RobotServoOff()

fir = false


while true do
    get_ready = 0
    time_move_s = 0
    y_shift = 0
    
    rets, err = SocketTest:Receive()
    --TimerOn()

    if rets and type(rets) == "table" then
    	--TimerOn()
    	signal_servo = rets[1]
    	position = tonumber(rets[2])
        shift = tonumber(rets[3]) or 0
        speed_conveyor = tonumber(rets[4]) or 1
        x = tonumber(rets[5]) or 0
        y = tonumber(rets[6]) or 0
        drop = tonumber(rets[7]) or 2
        back = tonumber(rets[8]) or 0
        pr = tonumber(rets[9]) or 1
        do1 = rets[10]
        do2 = rets[11]
      
        servo_on(signal_servo)

        if servo_enable == true then
        	if start ~= true then
                MovP("HOME")
                start = true
            end
        	
            if position == 0 then
                if x ~= 0 and y ~= 0 then
                	WritePoint("P1", "X", x)
                	WritePoint("P1", "Z", -165)
                	
                	x_real = RobotX()
                	y_real = RobotY()
               
                    hypotenuse = math.sqrt(math.pow((x_real - x), 2) + math.pow((y_real - y), 2))
                    time_hypo = hypotenuse / speed_arm
                    delta = time_hypo * speed_conveyor * pr
                    
                    y_delta = y + delta + delta_back
                    delta_back = 0
                    
                    hypotenuse_2 = math.sqrt(math.pow(x, 2) + math.pow(y_delta , 2))
                    
                    if x >= 140 and y_delta <= 460 and hypotenuse_2 < 580 then                         
                        WritePoint("P1", "Y", y_delta) 
                        MovL("P1")
                    
                        WritePoint("P1", "Z", -195)
                        MovP("P1", PASS())
                           
                        if iterator == 0 then
                            WritePoint("P1", "Z", -165)
                        elseif iterator == 1 then 
                            WritePoint("P1", "Z", -165)
                        end
                        
                        MovP("P1", PASS())

                        iterator = iterator + 1
                        
                        if iterator > 1 then
                            if y_delta >= 390 then 
                                WritePoint("P1", "Y", 320)
                                MovL("P1", PASS())
                            end
                            
                            dropping()
                            iterator = 0
                        end
                        
                        get_ready = 1
                        
                    else
                        get_ready = 2
                    end
                            
                    if fir == false then 
                        --DELAY(2)
                        fir = true
                    end
        
                end

            elseif position == 1 then
                MovP("OFF")
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
            RobotX(),
            RobotY(),
            x,
            y,
            y_delta,
            delta,
            delta_hand, 
            timer
        }
    
        local data_to_send = table.concat(data_parts, ",")
        SocketTest:Send(data_to_send)
        
        x = 0
        y = 0
        rets = 'none'
        
    else
        if servo_enable == true and iterator == 1 then 
            dropping()
            iterator = 0
        end
        
        if servo_enable == true and position == 0 and (ABS(RobotX()- 300)> 5 and ABS(RobotY()+ 300) > 5) then
            WritePoint("P1", "H", 1)
            MovP("HOME", PASS())
            fir = false
        end
        
        delta_back = 0
    end
end

RobotServoOff()