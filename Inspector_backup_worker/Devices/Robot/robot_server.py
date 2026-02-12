import socket
import time
from Utils.loging import log_action

from Devices.Robot.robot_module import RobotModule

def start_robot_server_process(host, port, stop_event):
    with socket.socket() as s:
        s.bind((host, port))
        s.listen()
        print(f"Robot server listening on {host}:{port}")

        conn, addr = s.accept()
        with conn:
            print(f"Connected by {addr}")
            while not stop_event.is_set():
                data = conn.recv(1024)
                if not data:
                    break
                message = data.decode('utf-8')
                print(f"Робот получил: {message}")
                
                message_list = RobotModule.split_message(message)
                print(f"Разбитое сообщение: {message_list}")

                #log_action()
                
                servo_on = message_list[0]
                position = message_list[1]
                shift = message_list[2]
                speed_conveyor = message_list[3]
                x_new = message_list[4]
                y_new = message_list[5]
                di1 = message_list[6]
                di2 = message_list[7]

                if x_new != 'none' or y_new != 'none':
                # Задержка перед отправкой подтверждения
                    time.sleep(2)

                # Отправка подтверждения
                conn.sendall("ready".encode('utf-8'))
                print(f"Робот отправил подтверждение")

    print('Робот отключился')
