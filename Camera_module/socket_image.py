import socket
import struct
import threading
import cv2
import numpy as np
import time

from Utils.timer import Timer


class ImageStreamer:
    def __init__(self, host='0.0.0.0', port=5000):
        self.host = host
        self.port = port
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.connection = None
        self.client_address = None
        self.lock = threading.Lock()  
        self.running = False  
        self.server_thread = None 

        self.buffer = b''
        self.frame_size = None


    def start(self):
        self.running = True
        self.socket.bind((self.host, self.port))
        self.socket.listen(1)
        
        self.server_thread = threading.Thread(target=self._accept_connections, daemon=True)
        self.server_thread.start()


    def _accept_connections(self):
        while self.running:
            try:
                connection, addr = self.socket.accept()
                
                with self.lock:
                    if self.connection:
                        try:
                            self.connection.close()
                        except:
                            pass
                    self.connection = connection
                    self.client_address = addr
            except Exception as e:
                if self.running:
                   pass
                
                
    def connect_client(self, ip, port):
        self.socket.connect((ip, port))
        print(f"Подключено к {ip}:{port}")


    def send_frame(self, frame_data):
        with self.lock:
            if not self.connection:
                return
            
            try:
                size = struct.pack('!I', len(frame_data))
                self.connection.sendall(size + frame_data)
            except Exception as e:
                try:
                    self.connection.close()
                except:
                    pass
                self.connection = None


    def read_frame(self):        
        timer = Timer('camera_tcp')
        
        while True:
            if not self.connection:
                return
            
            data = self.connection.recv(4096)
            #print(f"Ожидаемый размер кадра: {data} байт")
            
            timer.start()

            if not data:
                print("Соединение закрыто сервером")
                break
            
            self.buffer += data
            
            if self.frame_size is None:
                if len(self.buffer) >= 4:
                    self.frame_size = struct.unpack('!I', self.buffer[:4])[0]
                    self.buffer = self.buffer[4:]
                    print(f"Ожидаемый размер кадра: {self.frame_size} байт")
                else:
                    continue  # Ждем больше данных

            if len(self.buffer) >= self.frame_size:
                frame_data = self.buffer[:self.frame_size]
                self.buffer = self.buffer[self.frame_size:]
                self.frame_size = None

                try:
                    # Если получен полный кадр
                    frame = cv2.imdecode(np.frombuffer(frame_data, np.uint8), cv2.IMREAD_COLOR)
                    timer.elapsed_time(print_log=True)
                    
                    return frame
                except Exception as e:
                    print(f"Ошибка отображения: {str(e)}")
                    return None


    def send_data(self, data):
        data = self.format_data_for_tcp(data)

        if not self.connection:
            return

        try:
            print(f'Сервер отправил {data}')
            #self.socket.sendall(data.encode('utf-8'))
            self.connection.sendall(data.encode('latin-1'))
        except Exception as e:
            print(f"Произошла ошибка при отправке данных: {e}. Закрытие соединения...")
            self.stop()


    def receive_data(self):
        if not self.connection:
            return

        try:
            data = self.connection.recv(1024)
            #print(f'Сервер получил {data}')

            #data = self.split_message(data.decode('utf-8'))
            data = self.split_message(data.decode('latin-1'))

            return data
        except Exception as e:
            print(f"Произошла ошибка при получении подтверждения: {e}. Закрытие соединения...")
            self.stop()
            
            return None


    @staticmethod
    def format_data_for_tcp(data_list, delimiter=',', end_of_line='\r\n'):
        """
        Преобразует список данных в строку, готовую для отправки по TCP.

        :param data_list: Список данных для отправки.
        :param delimiter: Знак разделения элементов списка.
        :param end_of_line: Символ конца строки.
        :return: Строка, готовая для отправки по TCP.
        """
        formatted_data = delimiter.join(map(str, data_list)) + end_of_line
        #print('formatted_data:', repr(formatted_data), 'time', time.time())
        return formatted_data


    @staticmethod
    def split_message(message, delimiter=',', end_of_line='\r\n'):
        """
        Убирает символы конца строки и разбивает сообщение на список строк на основе указанного разделителя.

        :param message: Сообщение для разбиения.
        :param delimiter: Разделитель для разбиения сообщения.
        :param end_of_line: Символы конца строки для удаления.
        :return: Список строк, полученных из сообщения.
        """
        # Убираем символы конца строки
        cleaned_message = message.strip(end_of_line)
        # Разбиваем сообщение на список
        return cleaned_message.split(delimiter)


    def stop(self):
        self.running = False
        try:
            self.socket.shutdown(socket.SHUT_RDWR)
        except:
            pass
        
        if self.connection:
            self.connection.close()
        self.socket.close()




