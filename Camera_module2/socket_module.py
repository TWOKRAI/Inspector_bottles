import socket
import struct
import threading
import cv2
import numpy as np

from Utils.timer import Timer


class StreamBase:
    """
    Базовый класс для передачи изображений и параметров по TCP.
    Реализует общую логику отправки/приема данных.
    
    Args:
        host (str): IP-адрес интерфейса
        port (int): Порт для подключения
    """
    HEADER_FORMAT = '!BI'  # [тип:1байт][размер:4байта]
    HEADER_SIZE = 5  # 1 + 4 байта
    IMAGE_TYPE = 0
    PARAMS_TYPE = 1

    def __init__(self, host, port):
        self.host = host
        self.port = port
        self.socket = None
        self.connection = None
        self.lock = threading.Lock()
        self.running = True
        self._init_socket()

        self.timer = Timer('recive frame')

    def _init_socket(self):
        """Инициализация TCP сокета с настройками"""
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.socket.settimeout(1.0)

    def _send_message(self, msg_type, data):
        """
        Отправка сообщения с заголовком [тип+длина] + данные
        
        Args:
            msg_type (int): Тип сообщения (0=изображение, 1=параметры)
            data (bytes): Бинарные данные для отправки
        """
        with self.lock:
            if not self.connection:
                return False
            
            try:
                header = struct.pack(self.HEADER_FORMAT, msg_type, len(data))
                self.connection.sendall(header + data)
                return True
            except (OSError, ConnectionError):
                self._close_connection()
                return False

    def _receive_message(self):
        """
        Прием сообщения по частям. Сначала заголовок, затем тело.
        
        Returns:
            tuple: (msg_type, data) или (None, None) при ошибке
        """
        try:
            # Получение заголовка
            header = self._recv_exact(self.HEADER_SIZE)
            if not header:
                return None, None
                
            # Распаковка заголовка
            msg_type, data_size = struct.unpack(self.HEADER_FORMAT, header)
            
            # Получение данных
            data = self._recv_exact(data_size)

            return (msg_type, data) if data else (None, None)
            
        except (struct.error, ConnectionError):
            return None, None

    def _recv_exact(self, n):
        """
        Получение точно n байт из сокета
        
        Args:
            n (int): Количество байт для получения
            
        Returns:
            bytes: Полученные данные или None при ошибке
        """
        data = bytearray()
        while len(data) < n:
            try:
                chunk = self.connection.recv(n - len(data))
                if not chunk:
                    return None
                data.extend(chunk)
            except socket.timeout:
                if not self.running:
                    return None
                continue
        return bytes(data)

    def send_image(self, frame, quality=95):
        """
        Отправка изображения в формате JPEG
        
        Args:
            frame (numpy.ndarray): Изображение в формате OpenCV
            quality (int): Качество сжатия (1-100)
            
        Returns:
            bool: Успешность отправки
        """
        _, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, quality])
        return self._send_message(self.IMAGE_TYPE, buffer.tobytes())

    def send_params(self, params):
        """
        Отправка параметров в виде строки
        
        Args:
            params (list): Список параметров для отправки
            
        Returns:
            bool: Успешность отправки
        """
        formatted = ','.join(map(str, params)) + '\r\n'
        return self._send_message(self.PARAMS_TYPE, formatted.encode('latin-1'))

    def receive(self):
        """
        Получение сообщения (автоматически определяет тип)
        
        Returns:
            tuple: 
                - Для изображений: (None, numpy.ndarray)
                - Для параметров: (list, None)
                - (None, None) при ошибке
        """
        self.timer.start()
        
        msg_type, data = self._receive_message()
        
        if msg_type == self.IMAGE_TYPE:
            frame = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
            self.timer.elapsed_time(print_log=False)
            return None, frame
            
        elif msg_type == self.PARAMS_TYPE:
            params = data.decode('latin-1').strip('\r\n').split(',')
            return params, None
            
        return None, None

    def _close_connection(self):
        """Безопасное закрытие соединения"""
        if self.connection:
            try:
                self.connection.close()
            except OSError:
                pass
            self.connection = None

    def stop(self):
        """Остановка соединения и освобождение ресурсов"""
        self.running = False
        self._close_connection()
        if self.socket:
            try:
                self.socket.close()
            except OSError:
                pass
            self.socket = None


class StreamServer(StreamBase):
    """Серверная часть для приема подключений"""
    def __init__(self, host='0.0.0.0', port=5000):
        super().__init__(host, port)
        self.client_address = None

    def start(self):
        """Запуск сервера для прослушивания порта"""
        self.socket.bind((self.host, self.port))
        self.socket.listen(1)

    def accept_connection(self):
        """
        Ожидание клиентского подключения (блокирующий вызов)
        
        Returns:
            tuple: (success, client_address) результат подключения
        """
        try:
            self.connection, self.client_address = self.socket.accept()
            return True, self.client_address
        except (OSError, socket.timeout):
            return False, None


class StreamClient(StreamBase):
    """Клиентская часть для подключения к серверу"""
    def connect(self):
        """
        Подключение к серверу
        
        Returns:
            bool: Успешность подключения
        """
        try:
            self.socket.connect((self.host, self.port))
            self.connection = self.socket
            return True
        except (ConnectionRefusedError, TimeoutError):
            return False