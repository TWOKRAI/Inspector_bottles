# -*- coding: utf-8 -*-
"""
Чистый процесс камеры БЕЗ обработки изображения
Использует оригинальную логику из BasicDemo.py
"""

import multiprocessing as mp
import threading
import numpy as np
import time
import ctypes
from ctypes import *
import queue
import cv2

from .MvCameraControl_class import MvCamera, MV_CC_DEVICE_INFO_LIST, POINTER, MV_CC_DEVICE_INFO
from .MvCameraControl_class import MV_FRAME_OUT, MV_DISPLAY_FRAME_INFO, MVCC_FLOATVALUE
from .MvCameraControl_class import MV_GIGE_DEVICE, MV_USB_DEVICE
from .MvErrorDefine_const import MV_OK, MV_E_CALLORDER, MV_E_PARAMETER
from .CameraParams_header import *

from Utils.fps_module import FrameFPS


class CameraManager:
    """
    Чистый менеджер для управления процессом камеры БЕЗ обработки
    """
    
    def __init__(self, queue_manager):
        self.process = None

        self.queue_manager = queue_manager
        
        # self.cmd_queue = mp.Queue()  # Очередь команд к камере
        # self.response_queue = mp.Queue()  # Очередь ответов от камеры
        # self.frame_queue = mp.Queue(maxsize=2)  # Очередь кадров (маленький буфер)

        self.cmd_queue =  self.queue_manager.cmd_queue  # Очередь команд к камере
        self.response_queue = self.queue_manager.response_queue  # Очередь ответов от камеры
        self.frame_queue = self.queue_manager.frame_queue  # Очередь кадров (маленький буфер)
        
        self.is_running = False

        
    @staticmethod
    def enum_devices():
        """
        Перечислить доступные камеры (без запуска процесса)
        Возвращает список словарей с информацией о камерах
        """
        try:
            device_list = MV_CC_DEVICE_INFO_LIST()
            ret = MvCamera.MV_CC_EnumDevices(MV_GIGE_DEVICE | MV_USB_DEVICE, device_list)
            
            if ret != 0:
                return {'status': 'error', 'error': f'Enum devices failed: {ret}'}
            
            if device_list.nDeviceNum == 0:
                return {'status': 'success', 'devices': []}
            
            devices = []
            for i in range(device_list.nDeviceNum):
                mvcc_dev_info = cast(device_list.pDeviceInfo[i], POINTER(MV_CC_DEVICE_INFO)).contents
                
                device_info = {
                    'index': i,
                    'type': 'Unknown',
                    'user_name': '',
                    'model_name': '',
                    'serial': ''
                }
                
                if mvcc_dev_info.nTLayerType == MV_GIGE_DEVICE:
                    device_info['type'] = 'GigE'
                    
                    # Декодируем имена
                    try:
                        user_name = ctypes.cast(
                            mvcc_dev_info.SpecialInfo.stGigEInfo.chUserDefinedName,
                            ctypes.c_char_p
                        ).value.decode('gbk')
                    except:
                        user_name = str(mvcc_dev_info.SpecialInfo.stGigEInfo.chUserDefinedName)
                    
                    try:
                        model_name = ctypes.cast(
                            mvcc_dev_info.SpecialInfo.stGigEInfo.chModelName,
                            ctypes.c_char_p
                        ).value.decode('gbk')
                    except:
                        model_name = str(mvcc_dev_info.SpecialInfo.stGigEInfo.chModelName)
                    
                    # IP адрес
                    nip1 = ((mvcc_dev_info.SpecialInfo.stGigEInfo.nCurrentIp & 0xff000000) >> 24)
                    nip2 = ((mvcc_dev_info.SpecialInfo.stGigEInfo.nCurrentIp & 0x00ff0000) >> 16)
                    nip3 = ((mvcc_dev_info.SpecialInfo.stGigEInfo.nCurrentIp & 0x0000ff00) >> 8)
                    nip4 = (mvcc_dev_info.SpecialInfo.stGigEInfo.nCurrentIp & 0x000000ff)
                    
                    device_info['user_name'] = user_name
                    device_info['model_name'] = model_name
                    device_info['serial'] = f"{nip1}.{nip2}.{nip3}.{nip4}"
                    device_info['display_name'] = f"[{i}] GigE: {user_name} {model_name} ({nip1}.{nip2}.{nip3}.{nip4})"
                    
                elif mvcc_dev_info.nTLayerType == MV_USB_DEVICE:
                    device_info['type'] = 'USB'
                    
                    # Декодируем имена
                    try:
                        user_name = ctypes.cast(
                            mvcc_dev_info.SpecialInfo.stUsb3VInfo.chUserDefinedName,
                            ctypes.c_char_p
                        ).value.decode('gbk')
                    except:
                        user_name = str(mvcc_dev_info.SpecialInfo.stUsb3VInfo.chUserDefinedName)
                    
                    try:
                        model_name = ctypes.cast(
                            mvcc_dev_info.SpecialInfo.stUsb3VInfo.chModelName,
                            ctypes.c_char_p
                        ).value.decode('gbk')
                    except:
                        model_name = str(mvcc_dev_info.SpecialInfo.stUsb3VInfo.chModelName)
                    
                    # Serial number
                    serial = ""
                    for per in mvcc_dev_info.SpecialInfo.stUsb3VInfo.chSerialNumber:
                        if per == 0:
                            break
                        serial = serial + chr(per)
                    
                    device_info['user_name'] = user_name
                    device_info['model_name'] = model_name
                    device_info['serial'] = serial
                    device_info['display_name'] = f"[{i}] USB: {user_name} {model_name} ({serial})"
                
                devices.append(device_info)
            
            return {'status': 'success', 'devices': devices}
            
        except Exception as e:
            return {'status': 'error', 'error': str(e)}
        
    def start_process(self, camera_index=0):
        """Запустить процесс камеры"""
        if self.is_running:
            print("Camera process already running")
            return False
        
        # Создаем процесс
        self.process = mp.Process(
            target=self._camera_worker_process,  # Используем метод класса
            args=(
                camera_index,
                self.queue_manager  # Передаем менеджер очередей
            )
        )
        self.process.start()
        self.is_running = True
            
        # # Создаем процесс
        # self.process = mp.Process(
        #     target=clean_camera_worker_process,
        #     args=(
        #         camera_index,
        #         self.cmd_queue,
        #         self.response_queue,
        #         self.frame_queue
        #     )
        # )
        # self.process.start()
        # self.is_running = True
        
        # Ждем ответа об инициализации
        try:
            response = self.response_queue.get(timeout=10)
            if response['status'] == 'initialized':
                print("Camera process started successfully")
                return True
            else:
                print(f"Camera initialization failed: {response.get('error', 'Unknown error')}")
                return False
        except queue.Empty:
            print("Timeout waiting for camera initialization")
            return False
    
    def _camera_worker_process(self, camera_index, queue_manager):
        """
        Рабочий процесс для камеры БЕЗ обработки
        """
        worker = CleanCameraWorker(
            camera_index,
            queue_manager,
            queue_manager.cmd_queue,      # Берем из менеджера
            queue_manager.response_queue, # Берем из менеджера  
            queue_manager.frame_queue     # Берем из менеджера
        )
        worker.run()

    def send_command(self, command, **kwargs):
        """Отправить команду камере"""
        cmd = {'command': command, **kwargs}
        #self.cmd_queue.put(cmd)
        self.cmd_queue.put(cmd)
        
    def get_response(self, timeout=5):
        """Получить ответ от камеры"""
        try:
            return self.response_queue.get(timeout=timeout)
        except queue.Empty:
            return {'status': 'timeout'}
    
    def open_camera(self):
        """Открыть камеру"""
        self.send_command('open')
        return self.get_response()
    
    def start_grabbing(self):
        """Начать захват кадров"""
        self.send_command('start_grab')
        response = self.get_response()
        
        if response.get('status') == 'success':
            print("Grabbing started successfully")
            
        return response
    
    def stop_grabbing(self):
        """Остановить захват кадров"""
        self.send_command('stop_grab')
        response = self.get_response()
        
        return response
    
    def close_camera(self):
        """Закрыть камеру"""
        self.send_command('close')
        return self.get_response()
    
    def get_frame(self, timeout=1.0):
        """
        Получить текущий кадр из очереди
        Возвращает numpy array или None если кадр не готов
        """
        try:
            frame = self.queue_manager.frame_queue.get(timeout=timeout)
            return frame
        except queue.Empty:
            return None
    
    def get_camera_parameters(self):
        """Получить параметры камеры"""
        self.send_command('get_params')
        return self.get_response()
    
    def set_camera_parameters(self, frame_rate, exposure_time, gain):
        """Установить параметры камеры"""
        self.send_command('set_params', frame_rate=frame_rate, exposure_time=exposure_time, gain=gain)
        return self.get_response()
    
    def stop_process(self):
        """Остановить процесс камеры"""
        if not self.is_running:
            return
            
        self.send_command('shutdown')
        
        # Ждем завершения процесса
        if self.process is not None:
            self.process.join(timeout=5)
            if self.process.is_alive():
                print("Force terminating camera process")
                self.process.terminate()
                self.process.join()
            
        self.is_running = False
        print("Camera process stopped")
    
    def __del__(self):
        """Деструктор - закрываем ресурсы"""
        self.stop_process()


def clean_camera_worker_process(camera_index, queue_manager, cmd_queue, response_queue, frame_queue):
    """
    Чистый рабочий процесс для камеры БЕЗ обработки
    """
    worker = CleanCameraWorker(camera_index, queue_manager, cmd_queue, response_queue, frame_queue)
    worker.run()


class CleanCameraWorker:
    """
    Чистый класс для работы с камерой БЕЗ обработки
    Использует ТОЛЬКО оригинальную логику из BasicDemo.py
    """
    
    def __init__(self, camera_index, queue_manager, cmd_queue, response_queue, frame_queue):
        self.camera_index = camera_index

        self.queue_manager = queue_manager
        
        self.cmd_queue = cmd_queue
        self.response_queue = response_queue
        self.frame_queue = frame_queue
        
        # Инициализация камеры
        self.device_list = None
        self.camera = None
        self.is_open = False
        self.is_grabbing = False
        
        # Поток для захвата изображений
        self.grab_thread = None
        self.stop_grab_event = threading.Event()
        
        # Буфер для изображений
        self.buf_save_image = None
        self.st_frame_info = None
        self.buf_lock = threading.Lock()

        self.frame_counter = 0

        self.frame_fps = FrameFPS()

        
    def run(self):
        """Основной цикл работы процесса"""
        try:
            # Перечисляем устройства
            self.enum_devices()
            
            # Отправляем сообщение об инициализации
            self.response_queue.put({'status': 'initialized'})
                
            # Обрабатываем команды
            while True:
                try:
                    cmd = self.cmd_queue.get(timeout=0.1)
                    
                    if cmd['command'] == 'shutdown':
                        print("Shutting down camera worker")
                        break
                    elif cmd['command'] == 'open':
                        self.handle_open()
                    elif cmd['command'] == 'close':
                        self.handle_close()
                    elif cmd['command'] == 'start_grab':
                        self.handle_start_grab()
                    elif cmd['command'] == 'stop_grab':
                        self.handle_stop_grab()
                    elif cmd['command'] == 'get_params':
                        self.handle_get_params()
                    elif cmd['command'] == 'set_params':
                        self.handle_set_params(cmd.get('frame_rate'), cmd.get('exposure_time'), cmd.get('gain'))
                    else:
                        self.response_queue.put({'status': 'error', 'error': f'Unknown command: {cmd["command"]}'})
                        
                except queue.Empty:
                    continue
                    
        except Exception as e:
            print(f"Error in camera worker: {e}")
            import traceback
            traceback.print_exc()
        finally:
            # Очистка ресурсов
            self.cleanup()
    
    def enum_devices(self):
        """Перечислить доступные камеры"""
        self.device_list = MV_CC_DEVICE_INFO_LIST()
        ret = MvCamera.MV_CC_EnumDevices(MV_GIGE_DEVICE | MV_USB_DEVICE, self.device_list)
        if ret != 0:
            raise Exception(f"Failed to enumerate devices: {ret}")
        if self.device_list.nDeviceNum == 0:
            raise Exception("No devices found")
        print(f"Found {self.device_list.nDeviceNum} camera(s)")
    
    def handle_open(self):
        """Открыть камеру"""
        try:
            if self.is_open:
                self.response_queue.put({'status': 'error', 'error': 'Camera already open'})
                return
            
            # Выбираем устройство
            if self.camera_index >= self.device_list.nDeviceNum:
                self.response_queue.put({'status': 'error', 'error': 'Invalid camera index'})
                return
            
            stDeviceList = cast(
                self.device_list.pDeviceInfo[self.camera_index],
                POINTER(MV_CC_DEVICE_INFO)
            ).contents
            
            # Создаем хендл
            self.camera = MvCamera()
            ret = self.camera.MV_CC_CreateHandle(stDeviceList)
            if ret != 0:
                self.response_queue.put({'status': 'error', 'error': f'Create handle failed: {ret}'})
                return
            
            # Открываем устройство
            ret = self.camera.MV_CC_OpenDevice()
            if ret != 0:
                self.camera.MV_CC_DestroyHandle()
                self.response_queue.put({'status': 'error', 'error': f'Open device failed: {ret}'})
                return
            
            print("Camera opened successfully")
            self.is_open = True
            
            # Настройка пакетов для GigE камер
            if stDeviceList.nTLayerType == MV_GIGE_DEVICE:
                nPacketSize = self.camera.MV_CC_GetOptimalPacketSize()
                if int(nPacketSize) > 0:
                    self.camera.MV_CC_SetIntValue("GevSCPSPacketSize", nPacketSize)
            
            # Устанавливаем continuous mode (trigger off)
            self.camera.MV_CC_SetEnumValue("TriggerMode", MV_TRIGGER_MODE_OFF)
            
            # ВАЖНО: Включаем AcquisitionFrameRateEnable для контроля FPS
            ret = self.camera.MV_CC_SetBoolValue("AcquisitionFrameRateEnable", True)
            if ret != 0:
                print(f"Warning: Set AcquisitionFrameRateEnable failed: {ret}")
            
            print("Camera opened and configured successfully")
            self.response_queue.put({'status': 'success'})
            
        except Exception as e:
            self.response_queue.put({'status': 'error', 'error': str(e)})
    
    def handle_close(self):
        """Закрыть камеру"""
        try:
            if self.is_grabbing:
                self.handle_stop_grab()
            
            if self.is_open and self.camera is not None:
                self.camera.MV_CC_CloseDevice()
                self.camera.MV_CC_DestroyHandle()
                self.is_open = False
                print("Camera closed successfully")
            
            self.response_queue.put({'status': 'success'})
            
        except Exception as e:
            self.response_queue.put({'status': 'error', 'error': str(e)})
    
    def handle_start_grab(self):
        """Начать захват кадров"""
        try:
            if not self.is_open:
                self.response_queue.put({'status': 'error', 'error': 'Camera not open'})
                return
            
            if self.is_grabbing:
                self.response_queue.put({'status': 'error', 'error': 'Already grabbing'})
                return
            
            # Начинаем захват
            ret = self.camera.MV_CC_StartGrabbing()
            if ret != 0:
                self.response_queue.put({'status': 'error', 'error': f'Start grabbing failed: {ret}'})
                return
            
            self.is_grabbing = True
            self.stop_grab_event.clear()
            
            # Запускаем поток захвата
            self.grab_thread = threading.Thread(target=self.grab_loop)
            self.grab_thread.start()
            
            print("Started grabbing")
            self.response_queue.put({'status': 'success'})
            
        except Exception as e:
            self.response_queue.put({'status': 'error', 'error': str(e)})
    
    def handle_stop_grab(self):
        """Остановить захват кадров"""
        try:
            if not self.is_grabbing:
                self.response_queue.put({'status': 'error', 'error': 'Not grabbing'})
                return
            
            # Останавливаем поток
            self.stop_grab_event.set()
            if self.grab_thread is not None:
                self.grab_thread.join(timeout=2)
            
            # Останавливаем захват
            if self.is_open and self.camera is not None:
                self.camera.MV_CC_StopGrabbing()
            
            self.is_grabbing = False
            
            print("Stopped grabbing")
            self.response_queue.put({'status': 'success'})
            
        except Exception as e:
            self.response_queue.put({'status': 'error', 'error': str(e)})
    
    def handle_get_params(self):
        """Получить параметры камеры"""
        try:
            if not self.is_open:
                self.response_queue.put({'status': 'error', 'error': 'Camera not open'})
                return
            
            # Получаем параметры камеры используя оригинальную логику
            stFloatParam_FrameRate = MVCC_FLOATVALUE()
            memset(byref(stFloatParam_FrameRate), 0, sizeof(MVCC_FLOATVALUE))
            stFloatParam_exposureTime = MVCC_FLOATVALUE()
            memset(byref(stFloatParam_exposureTime), 0, sizeof(MVCC_FLOATVALUE))
            stFloatParam_gain = MVCC_FLOATVALUE()
            memset(byref(stFloatParam_gain), 0, sizeof(MVCC_FLOATVALUE))
            
            # Проверяем статус AcquisitionFrameRateEnable
            try:
                stBool = c_bool(False)
                ret = self.camera.MV_CC_GetBoolValue("AcquisitionFrameRateEnable", stBool)
                if ret != 0:
                    print(f"Warning: Get AcquisitionFrameRateEnable failed: {ret}")
                else:
                    print(f"AcquisitionFrameRateEnable: {stBool.value}")
            except Exception as e:
                print(f"Error checking AcquisitionFrameRateEnable: {e}")
            
            # Получаем Frame Rate
            ret = self.camera.MV_CC_GetFloatValue("AcquisitionFrameRate", stFloatParam_FrameRate)
            if ret != 0:
                self.response_queue.put({'status': 'error', 'error': f'Get frame rate failed: {ret}'})
                return
            
            # Получаем Exposure Time
            ret = self.camera.MV_CC_GetFloatValue("ExposureTime", stFloatParam_exposureTime)
            if ret != 0:
                self.response_queue.put({'status': 'error', 'error': f'Get exposure time failed: {ret}'})
                return
            
            # Получаем Gain
            ret = self.camera.MV_CC_GetFloatValue("Gain", stFloatParam_gain)
            if ret != 0:
                self.response_queue.put({'status': 'error', 'error': f'Get gain failed: {ret}'})
                return
            
            # Формируем ответ
            params = {
                'frame_rate': stFloatParam_FrameRate.fCurValue,
                'exposure_time': stFloatParam_exposureTime.fCurValue,
                'gain': stFloatParam_gain.fCurValue
            }
            
            print(f"Current camera parameters:")
            print(f"  Frame Rate: {params['frame_rate']:.2f} FPS")
            print(f"  Exposure Time: {params['exposure_time']:.2f} us")
            print(f"  Gain: {params['gain']:.2f} dB")
            self.response_queue.put({'status': 'success', 'parameters': params})
            
        except Exception as e:
            self.response_queue.put({'status': 'error', 'error': str(e)})
    
    def handle_set_params(self, frame_rate, exposure_time, gain):
        """Установить параметры камеры"""
        try:
            if not self.is_open:
                self.response_queue.put({'status': 'error', 'error': 'Camera not open'})
                return
            
            if frame_rate is None or exposure_time is None or gain is None:
                self.response_queue.put({'status': 'error', 'error': 'Invalid parameters'})
                return
            
            print(f"Setting parameters: Frame Rate={frame_rate}, Exposure={exposure_time}, Gain={gain}")
            
            # ВАЖНО: Включаем AcquisitionFrameRateEnable для контроля FPS
            ret = self.camera.MV_CC_SetBoolValue("AcquisitionFrameRateEnable", True)
            if ret != 0:
                print(f"Warning: Set AcquisitionFrameRateEnable failed: {ret}")
            else:
                print("SUCCESS: AcquisitionFrameRateEnable set to True")
            
            # Отключаем автоматическую экспозицию
            ret = self.camera.MV_CC_SetEnumValue("ExposureAuto", 0)
            if ret != 0:
                print(f"Warning: Set ExposureAuto failed: {ret}")
            
            time.sleep(0.2)  # Небольшая задержка как в оригинале
            
            # Устанавливаем Exposure Time
            ret = self.camera.MV_CC_SetFloatValue("ExposureTime", float(exposure_time))
            if ret != 0:
                error_msg = f'Set exposure time failed: {ret}'
                print(f"Error: {error_msg}")
                self.response_queue.put({'status': 'error', 'error': error_msg})
                return
            
            # Устанавливаем Gain
            ret = self.camera.MV_CC_SetFloatValue("Gain", float(gain))
            if ret != 0:
                error_msg = f'Set gain failed: {ret}'
                print(f"Error: {error_msg}")
                self.response_queue.put({'status': 'error', 'error': error_msg})
                return
            
            # Устанавливаем Frame Rate
            ret = self.camera.MV_CC_SetFloatValue("AcquisitionFrameRate", float(frame_rate))
            if ret != 0:
                error_msg = f'Set frame rate failed: {ret}'
                print(f"Error: {error_msg}")
                self.response_queue.put({'status': 'error', 'error': error_msg})
                return
            
            print(f"SUCCESS: Camera parameters set - Frame Rate={frame_rate}, Exposure={exposure_time}, Gain={gain}")
            self.response_queue.put({'status': 'success'})
            
        except Exception as e:
            error_msg = f"Exception in set_params: {str(e)}"
            print(f"Error: {error_msg}")
            self.response_queue.put({'status': 'error', 'error': error_msg})
    
    def grab_loop(self):
        """Цикл захвата кадров - использует ТОЛЬКО оригинальную логику"""
        stOutFrame = MV_FRAME_OUT()
        memset(byref(stOutFrame), 0, sizeof(stOutFrame))
        
        while not self.stop_grab_event.is_set():
            try:
                ret = self.camera.MV_CC_GetImageBuffer(stOutFrame, 1000)

                timestamp = time.time()
                self.frame_counter += 1
                
                if ret == 0:
                    # Сохраняем информацию о кадре
                    if self.buf_save_image is None:
                        self.buf_save_image = (c_ubyte * stOutFrame.stFrameInfo.nFrameLen)()
                    
                    self.st_frame_info = stOutFrame.stFrameInfo
                    
                    # Копируем данные в буфер
                    self.buf_lock.acquire()
                    cdll.msvcrt.memcpy(
                        byref(self.buf_save_image),
                        stOutFrame.pBufAddr,
                        self.st_frame_info.nFrameLen
                    )
                    self.buf_lock.release()
                    
                    # ОТЛАДОЧНАЯ ИНФОРМАЦИЯ (только при первом кадре)
                    if not hasattr(self, '_first_frame_logged'):
                        print(f"RAW Frame info: {self.st_frame_info.nWidth}x{self.st_frame_info.nHeight}, pixel_type: {self.st_frame_info.enPixelType}")
                        print(f"Frame length: {self.st_frame_info.nFrameLen} bytes")
                        self._first_frame_logged = True
                    
                    # ИСПОЛЬЗУЕМ ТОЛЬКО ОРИГИНАЛЬНУЮ ЛОГИКУ: frame = np.array(self.buf_save_image)
                    frame = np.array(self.buf_save_image)
                    
                    # Если это одномерный массив (Bayer pattern), reshape и демозаика
                    if len(frame.shape) == 1:
                        # Получаем размеры из информации о кадре
                        height = self.st_frame_info.nHeight
                        width = self.st_frame_info.nWidth
                        pixel_type = self.st_frame_info.enPixelType
                        
                        # Reshape в двумерный массив
                        frame = frame.reshape(height, width)
                        
                        # Проверяем, это ли Bayer pattern
                        if pixel_type == 17301513:  # PixelType_Gvsp_BayerRG8
                            # Применяем простую демозаику
                            frame = self.simple_bayer_demosaic(frame)
                            if not hasattr(self, '_demosaic_logged'):
                                print(f"Applied Bayer demosaic: {frame.shape}")
                                self._demosaic_logged = True
                        else:
                            if not hasattr(self, '_reshape_logged'):
                                print(f"Reshaped 1D to 2D: {frame.shape}")
                                self._reshape_logged = True
                    
                    # Отправляем в очередь (если есть место)
                    try:
                        #cv2.imwrite('frame_test.jpg', frame)

                        self.frame_queue.put_nowait(frame)
                        frames = [frame]
                        id_memory = 1 
                        self.queue_manager.memory_manager.write_images(frames, "camera_data", id_memory)

                        self.frame_fps.update()

                        self.frame_fps.get_fps()

                        data_frame = {
                            'id_memory': id_memory,
                            'current_time': timestamp,
                            'time_send': timestamp,
                            'height': height,
                            'width': width,
                            'frame_counter': self.frame_counter,
                        }

                        self.queue_manager.remove_old_if_full(self.queue_manager.input_processing)

                        data_frame['time_send'] = time.time()
                        self.queue_manager.input_processing.put(data_frame)

                    except queue.Full:
                        # Очередь полная, пропускаем кадр
                        pass
                    
                    # Освобождаем буфер камеры
                    self.camera.MV_CC_FreeImageBuffer(stOutFrame)
                    
                else:
                    # Таймаут или ошибка - это нормально, продолжаем
                    time.sleep(0.001)
                    
            except Exception as e:
                print(f"Error in grab loop: {e}")
                time.sleep(0.01)
        
        print("Grab loop finished")
    
    def simple_bayer_demosaic(self, bayer_image):
        """
        Простая демозаика для Bayer RG8 pattern
        """
        try:
            import cv2
            
            # Конвертируем Bayer RG8 в RGB используя OpenCV
            rgb_image = cv2.cvtColor(bayer_image, cv2.COLOR_BayerRG2RGB)
            
            return rgb_image
            
        except Exception as e:
            print(f"Error in demosaic: {e}")
            # Fallback - возвращаем как монохромное
            return bayer_image
    
    def cleanup(self):
        """Очистка ресурсов при завершении"""
        try:
            if self.is_grabbing:
                self.handle_stop_grab()
            
            if self.is_open:
                self.handle_close()
            
        except Exception as e:
            print(f"Error in cleanup: {e}")


if __name__ == "__main__":
    """
    Пример использования чистого процесса камеры
    """
    import cv2
    
    # Создаем менеджер
    manager = CameraManager()
    
    # Запускаем процесс камеры
    if manager.start_process(camera_index=0):
        print("Camera process started")
        
        # Открываем камеру
        response = manager.open_camera()
        print(f"Open camera: {response}")
        
        if response.get('status') == 'success':
            # Начинаем захват
            response = manager.start_grabbing()
            print(f"Start grabbing: {response}")
            
            if response.get('status') == 'success':
                # Захватываем кадры
                print("Press 'q' to quit")
                
                while True:
                    frame = manager.get_frame(timeout=1.0)
                    
                    if frame is not None:
                        # Отображаем кадр
                        cv2.imshow("Camera", frame)
                        
                        if cv2.waitKey(1) & 0xFF == ord('q'):
                            break
                    else:
                        print("No frame")
                
                cv2.destroyAllWindows()
                
                # Останавливаем захват
                manager.stop_grabbing()
            
            # Закрываем камеру
            manager.close_camera()
        
        # Останавливаем процесс
        manager.stop_process()
    
    print("Done")
