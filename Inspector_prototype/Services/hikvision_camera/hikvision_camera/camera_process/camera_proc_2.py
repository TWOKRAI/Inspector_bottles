# camera_process.py
import multiprocessing as mp
import time
import threading
import queue
import ctypes
from ctypes import *
import numpy as np

from .MvCameraControl_class import MvCamera, MV_CC_DEVICE_INFO_LIST, POINTER, MV_CC_DEVICE_INFO
from .MvCameraControl_class import MV_FRAME_OUT, MV_DISPLAY_FRAME_INFO, MVCC_FLOATVALUE
from .MvCameraControl_class import MV_GIGE_DEVICE, MV_USB_DEVICE
from .MvErrorDefine_const import MV_OK
from .CameraParams_header import *

class CameraProcess():
    """
    Независимый процесс камеры, который работает самостоятельно
    и общается через queue_manager
    """
    def __init__(self, queue_manager, camera_index=0):
        self.queue_manager = queue_manager
        self.camera_index = camera_index
        
        # Состояние камеры
        self.camera = None
        self.is_open = False
        self.is_grabbing = False
        self.stop_event = threading.Event()
        
        # Потоки
        self.command_thread = None
        self.grab_thread = None
        
        # Буферы
        self.buf_save_image = None
        self.st_frame_info = None
        self.buf_lock = threading.Lock()
        
        # Счетчики
        self.frame_counter = 0
        self.frame_id = 0
        
        # Индексная система для памяти (как в backup_worker)
        self.index_memory = [0] * 12
        
        # Устанавливаем событие ready_app для начала передачи кадров
        self.queue_manager.ready_app.set()

        
    def start(self):
        """Запустить процесс камеры"""
        print(f"Camera process started with index {self.camera_index}")
        
        # Запускаем поток для обработки команд
        self.command_thread = threading.Thread(target=self._command_loop)
        self.command_thread.daemon = True
        self.command_thread.start()
        
        # # Сообщаем UI, что процесс готов
        # self.queue_manager.camera_to_ui.put({
        #     'type': 'status',
        #     'status': 'process_ready',
        #     'camera_index': self.camera_index
        # })
        
        # Запускаем поток для освобождения памяти
        self.memory_thread = threading.Thread(target=self._memory_release_loop)
        self.memory_thread.daemon = True
        self.memory_thread.start()
        
        print("Camera process ready, waiting for commands...")
    
    def _command_loop(self):
        """Цикл обработки команд от UI"""
        while not self.stop_event.is_set():
            try:
                # Ждем команду от UI
                command = self.queue_manager.ui_to_camera.get(timeout=1)

                if command:
                    self._handle_command(command)

            except queue.Empty:
                continue
            except Exception as e:
                print(f"Error in command loop: {e}")
                import traceback
                traceback.print_exc()

        print('exit')
    
    def _memory_release_loop(self):
        """Цикл освобождения памяти"""
        while not self.stop_event.is_set():
            try:
                id_memory_delete = self.queue_manager.memory_release_queue.get(timeout=0.05)
                if id_memory_delete is not None and 0 <= id_memory_delete < len(self.index_memory):
                    self.index_memory[id_memory_delete] = 0
            except queue.Empty:
                continue
            except Exception as e:
                print(f"Error in memory release loop: {e}")
    
    def _memory_release_loop(self):
        """Цикл освобождения памяти"""
        while not self.stop_event.is_set():
            try:
                id_memory_delete = self.queue_manager.memory_release_queue.get(timeout=0.05)
                if id_memory_delete is not None and 0 <= id_memory_delete < len(self.index_memory):
                    self.index_memory[id_memory_delete] = 0
            except queue.Empty:
                continue
            except Exception as e:
                print(f"Error in memory release loop: {e}")
    
    def _handle_command(self, command):
        """Обработать команду от UI"""
        cmd_type = command.get('type')
        
        try:
            if cmd_type == 'open':
                self._handle_open()
            elif cmd_type == 'close':
                self._handle_close()
            elif cmd_type == 'start_grabbing':
                self._handle_start_grabbing()
            elif cmd_type == 'stop_grabbing':
                self._handle_stop_grabbing()
            elif cmd_type == 'get_parameters':
                self._handle_get_parameters()
            elif cmd_type == 'set_parameters':
                self._handle_set_parameters(command)
            elif cmd_type == 'enum_devices':
                self._handle_enum_devices()
            elif cmd_type == 'shutdown':
                self._handle_shutdown()
            else:
                self._send_error(f"Unknown command: {cmd_type}")
                
        except Exception as e:
            self._send_error(f"Command {cmd_type} failed: {str(e)}")
    
    def _handle_enum_devices(self):
        """Перечислить доступные камеры"""
        try:
            device_list = MV_CC_DEVICE_INFO_LIST()
            ret = MvCamera.MV_CC_EnumDevices(MV_GIGE_DEVICE | MV_USB_DEVICE, device_list)
            
            if ret != 0:
                self._send_error(f'Enum devices failed: {ret}')
                return
            
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
            
            self.queue_manager.camera_to_ui.put({
                'type': 'enum_devices_response',
                'devices': devices
            })

            print(f'отправил enum_devices_response {devices}')
            
        except Exception as e:
            self._send_error(f"Enum devices exception: {str(e)}")
    
    def _handle_open(self):
        """Открыть камеру"""
        if self.is_open:
            self._send_status("Camera already open")
            return
        
        try:
            # Перечисляем устройства для проверки
            device_list = MV_CC_DEVICE_INFO_LIST()
            ret = MvCamera.MV_CC_EnumDevices(MV_GIGE_DEVICE | MV_USB_DEVICE, device_list)
            
            if ret != 0 or device_list.nDeviceNum == 0:
                self._send_error("No cameras found")
                return
            
            if self.camera_index >= device_list.nDeviceNum:
                self._send_error(f"Camera index {self.camera_index} not available")
                return
            
            # Выбираем устройство
            stDeviceList = cast(
                device_list.pDeviceInfo[self.camera_index],
                POINTER(MV_CC_DEVICE_INFO)
            ).contents
            
            # Создаем хендл
            self.camera = MvCamera()
            ret = self.camera.MV_CC_CreateHandle(stDeviceList)
            if ret != 0:
                self._send_error(f'Create handle failed: {ret}')
                return
            
            # Открываем устройство
            ret = self.camera.MV_CC_OpenDevice()
            if ret != 0:
                self.camera.MV_CC_DestroyHandle()
                self._send_error(f'Open device failed: {ret}')
                return
            
            # Настройка
            if stDeviceList.nTLayerType == MV_GIGE_DEVICE:
                nPacketSize = self.camera.MV_CC_GetOptimalPacketSize()
                if int(nPacketSize) > 0:
                    self.camera.MV_CC_SetIntValue("GevSCPSPacketSize", nPacketSize)
            
            # Устанавливаем continuous mode
            self.camera.MV_CC_SetEnumValue("TriggerMode", MV_TRIGGER_MODE_OFF)
            self.camera.MV_CC_SetBoolValue("AcquisitionFrameRateEnable", True)
            
            self.is_open = True
            self._send_status("Camera opened successfully")
            
        except Exception as e:
            self._send_error(f"Open camera failed: {str(e)}")
    
    def _handle_close(self):
        """Закрыть камеру"""
        try:
            if self.is_grabbing:
                self._handle_stop_grabbing()
            
            if self.is_open and self.camera is not None:
                self.camera.MV_CC_CloseDevice()
                self.camera.MV_CC_DestroyHandle()
                self.camera = None
                self.is_open = False
            
            self._send_status("Camera closed")
            
        except Exception as e:
            self._send_error(f"Close camera failed: {str(e)}")
    
    def _handle_start_grabbing(self):
        """Начать захват кадров"""
        if not self.is_open:
            self._send_error("Camera not open")
            return
        
        if self.is_grabbing:
            self._send_status("Already grabbing")
            return
        
        try:
            ret = self.camera.MV_CC_StartGrabbing()
            if ret != 0:
                self._send_error(f'Start grabbing failed: {ret}')
                return
            
            self.is_grabbing = True
            
            # Запускаем поток захвата
            self.grab_thread = threading.Thread(target=self._grab_loop)
            self.grab_thread.daemon = True
            self.grab_thread.start()
            
            self._send_status("Grabbing started")
            
        except Exception as e:
            self._send_error(f"Start grabbing failed: {str(e)}")
    
    def _handle_stop_grabbing(self):
        """Остановить захват кадров"""
        try:
            if not self.is_grabbing:
                self._send_status("Not grabbing")
                return
            
            # Останавливаем поток захвата
            if self.grab_thread is not None:
                self.grab_thread.join(timeout=2)
                self.grab_thread = None
            
            # Останавливаем захват
            if self.is_open and self.camera is not None:
                self.camera.MV_CC_StopGrabbing()
            
            self.is_grabbing = False
            self._send_status("Grabbing stopped")
            
        except Exception as e:
            self._send_error(f"Stop grabbing failed: {str(e)}")
    
    def _grab_loop(self):
        """Цикл захвата кадров"""
        stOutFrame = MV_FRAME_OUT()
        memset(byref(stOutFrame), 0, sizeof(stOutFrame))
        
        while self.is_grabbing and not self.stop_event.is_set():
            try:
                ret = self.camera.MV_CC_GetImageBuffer(stOutFrame, 1000)
                
                if ret == 0:
                    # Создаем буфер если нужно
                    if self.buf_save_image is None:
                        self.buf_save_image = (c_ubyte * stOutFrame.stFrameInfo.nFrameLen)()
                    
                    self.st_frame_info = stOutFrame.stFrameInfo
                    
                    # Копируем данные
                    self.buf_lock.acquire()
                    cdll.msvcrt.memcpy(
                        byref(self.buf_save_image),
                        stOutFrame.pBufAddr,
                        self.st_frame_info.nFrameLen
                    )
                    self.buf_lock.release()
                    
                    # Конвертируем в numpy array
                    frame = np.array(self.buf_save_image)
                    
                    # Обрабатываем разные форматы
                    if len(frame.shape) == 1:
                        height = self.st_frame_info.nHeight
                        width = self.st_frame_info.nWidth
                        pixel_type = self.st_frame_info.enPixelType
                        
                        frame = frame.reshape(height, width)
                        
                        # Демозаика для Bayer pattern
                        if pixel_type == 17301513:  # PixelType_Gvsp_BayerRG8
                            try:
                                import cv2
                                frame = cv2.cvtColor(frame, cv2.COLOR_BayerRG2RGB)
                            except:
                                pass
                    
                    # Изменяем размер кадра если нужно (для совместимости с памятью)
                    if frame.shape[0] != 720 or frame.shape[1] != 1280:
                        try:
                            import cv2
                            frame = cv2.resize(frame, (1280, 720), interpolation=cv2.INTER_AREA)
                        except:
                            pass
                    
                    # Конвертируем в RGB если нужно
                    if len(frame.shape) == 2:
                        try:
                            import cv2
                            frame = cv2.cvtColor(frame, cv2.COLOR_GRAY2RGB)
                        except:
                            pass
                    elif len(frame.shape) == 3 and frame.shape[2] == 3:
                        # Конвертируем BGR в RGB если нужно
                        try:
                            import cv2
                            frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                        except:
                            pass
                    
                    # Записываем в разделяемую память
                    timestamp = time.time()
                    
                    # Находим свободный индекс
                    id_memory = None
                    for i in range(len(self.index_memory)):
                        if self.index_memory[i] == 0:
                            id_memory = i
                            break
                    
                    if id_memory is not None:
                        if id_memory > 7:
                            # Очищаем очереди если память переполнена
                            self.queue_manager.clear_all_queue()
                            self.queue_manager.clear_all_event()
                            for i in range(len(self.index_memory)):
                                self.index_memory[i] = 0
                            continue
                        
                        # Записываем кадр в память
                        frames = [frame]
                        self.index_memory[id_memory] = 1
                        self.queue_manager.memory_manager.write_images(frames, "camera_data", id_memory)
                        
                        # Отправляем метаданные в очередь для обработки
                        data_frame = {
                            'id_memory': id_memory,
                            'current_time': timestamp,
                            'frame_counter': self.frame_counter,
                            'frame_id': self.frame_id,
                        }
                        
                        self.queue_manager.remove_old_frame_if_full(self.queue_manager.frame_processor_queue)
                        self.queue_manager.frame_processor_queue.put(data_frame)
                        
                        # Также отправляем в display_queue для App
                        self.queue_manager.remove_old_frame_if_full(self.queue_manager.display_queue)
                        self.queue_manager.display_queue.put(data_frame)
                        
                        self.frame_id += 1
                        if self.frame_id > 120:
                            self.frame_id = 0
                    
                    # Также отправляем кадр в очередь для UI SDK (старый способ)
                    try:
                        self.queue_manager.frame_queue.put_nowait(frame)
                    except queue.Full:
                        # Очередь полная, пропускаем кадр
                        pass
                    
                    # Освобождаем буфер
                    self.camera.MV_CC_FreeImageBuffer(stOutFrame)
                    
                    self.frame_counter += 1
                    
                else:
                    time.sleep(0.001)
                    
            except Exception as e:
                print(f"Error in grab loop: {e}")
                time.sleep(0.01)
    
    def _handle_get_parameters(self):
        """Получить параметры камеры"""
        if not self.is_open:
            self._send_error("Camera not open")
            return
        
        try:
            stFloatParam_FrameRate = MVCC_FLOATVALUE()
            memset(byref(stFloatParam_FrameRate), 0, sizeof(MVCC_FLOATVALUE))
            stFloatParam_exposureTime = MVCC_FLOATVALUE()
            memset(byref(stFloatParam_exposureTime), 0, sizeof(MVCC_FLOATVALUE))
            stFloatParam_gain = MVCC_FLOATVALUE()
            memset(byref(stFloatParam_gain), 0, sizeof(MVCC_FLOATVALUE))
            
            # Получаем параметры
            ret = self.camera.MV_CC_GetFloatValue("AcquisitionFrameRate", stFloatParam_FrameRate)
            if ret != 0:
                self._send_error(f'Get frame rate failed: {ret}')
                return
            
            ret = self.camera.MV_CC_GetFloatValue("ExposureTime", stFloatParam_exposureTime)
            if ret != 0:
                self._send_error(f'Get exposure time failed: {ret}')
                return
            
            ret = self.camera.MV_CC_GetFloatValue("Gain", stFloatParam_gain)
            if ret != 0:
                self._send_error(f'Get gain failed: {ret}')
                return
            
            params = {
                'frame_rate': stFloatParam_FrameRate.fCurValue,
                'exposure_time': stFloatParam_exposureTime.fCurValue,
                'gain': stFloatParam_gain.fCurValue
            }
            
            self.queue_manager.camera_to_ui.put({
                'type': 'parameters_response',
                'parameters': params
            })
            
        except Exception as e:
            self._send_error(f"Get parameters failed: {str(e)}")
    
    def _handle_set_parameters(self, command):
        """Установить параметры камеры"""
        if not self.is_open:
            self._send_error("Camera not open")
            return
        
        try:
            frame_rate = command.get('frame_rate')
            exposure_time = command.get('exposure_time')
            gain = command.get('gain')
            
            if None in [frame_rate, exposure_time, gain]:
                self._send_error("Missing parameters")
                return
            
            # Устанавливаем параметры
            self.camera.MV_CC_SetBoolValue("AcquisitionFrameRateEnable", True)
            self.camera.MV_CC_SetEnumValue("ExposureAuto", 0)
            
            time.sleep(0.2)
            
            ret = self.camera.MV_CC_SetFloatValue("ExposureTime", float(exposure_time))
            if ret != 0:
                self._send_error(f'Set exposure time failed: {ret}')
                return
            
            ret = self.camera.MV_CC_SetFloatValue("Gain", float(gain))
            if ret != 0:
                self._send_error(f'Set gain failed: {ret}')
                return
            
            ret = self.camera.MV_CC_SetFloatValue("AcquisitionFrameRate", float(frame_rate))
            if ret != 0:
                self._send_error(f'Set frame rate failed: {ret}')
                return
            
            self._send_status("Parameters set successfully")
            
        except Exception as e:
            self._send_error(f"Set parameters failed: {str(e)}")
    
    def _handle_shutdown(self):
        """Завершить работу процесса"""
        self.stop_event.set()
        
        if self.is_grabbing:
            self._handle_stop_grabbing()
        
        if self.is_open:
            self._handle_close()
        
        self._send_status("Camera process shutdown")
    
    def _send_status(self, message):
        """Отправить статус в UI"""
        self.queue_manager.camera_to_ui.put({
            'type': 'status',
            'status': message
        })
    
    def _send_error(self, error_message):
        """Отправить ошибку в UI"""
        self.queue_manager.camera_to_ui.put({
            'type': 'error',
            'error': error_message
        })

# def camera_process_main(queue_manager, camera_index=0):
#     """
#     Главная функция процесса камеры
#     """
#     process = CameraProcess(queue_manager, camera_index)
#     process.start()
    
#     # Ждем завершения
#     try:
#         while not process.stop_event.is_set():
#             time.sleep(0.1)
#     except KeyboardInterrupt:
#         process.stop_event.set()
    
#     print("Camera process finished")


def main(queue_manager=None):
    process = CameraProcess(queue_manager=queue_manager)
    process.start()
    
    print(f"Camera process {process.camera_index} main thread running...")
    
    # Бесконечный цикл в главном потоке
    try:
        while True:
            if process.stop_event.is_set():
                break
            time.sleep(0.1)
    except KeyboardInterrupt:
        process.stop_event.set()
    except Exception as e:
        print(f"Error in camera process main: {e}")
    
    # Ждем завершения командного потока
    if process.command_thread and process.command_thread.is_alive():
        process.command_thread.join(timeout=3.0)
    
    print("Camera process main thread finished")