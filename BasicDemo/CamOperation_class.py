# -- coding: utf-8 --
import sys
import threading
import msvcrt
import numpy as np
import time
import sys, os
import datetime
import inspect
import ctypes
import random
from ctypes import *
import cv2
import socket


sys.path.append("../MvImport")

from BasicDemo.CameraParams_header import *
from BasicDemo.MvCameraControl_class import *


# s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
# s.bind(('192.168.1.241', 3201))

# def pass_func(x):
#     pass


# 强制关闭线程
def Async_raise(tid, exctype):
    tid = ctypes.c_long(tid)
    if not inspect.isclass(exctype):
        exctype = type(exctype)
    res = ctypes.pythonapi.PyThreadState_SetAsyncExc(tid, ctypes.py_object(exctype))
    if res == 0:
        raise ValueError("invalid thread id")
    elif res != 1:
        ctypes.pythonapi.PyThreadState_SetAsyncExc(tid, None)
        raise SystemError("PyThreadState_SetAsyncExc failed")


# 停止线程
def Stop_thread(thread):
    Async_raise(thread.ident, SystemExit)


# 转为16进制字符串
def To_hex_str(num):
    chaDic = {10: 'a', 11: 'b', 12: 'c', 13: 'd', 14: 'e', 15: 'f'}
    hexStr = ""
    if num < 0:
        num = num + 2 ** 32
    while num >= 16:
        digit = num % 16
        hexStr = chaDic.get(digit, str(digit)) + hexStr
        num //= 16
    hexStr = chaDic.get(num, str(num)) + hexStr
    return hexStr


# 是否是Mono图像
def Is_mono_data(enGvspPixelType):
    if PixelType_Gvsp_Mono8 == enGvspPixelType or PixelType_Gvsp_Mono10 == enGvspPixelType \
            or PixelType_Gvsp_Mono10_Packed == enGvspPixelType or PixelType_Gvsp_Mono12 == enGvspPixelType \
            or PixelType_Gvsp_Mono12_Packed == enGvspPixelType:
        return True
    else:
        return False


# 是否是彩色图像
def Is_color_data(enGvspPixelType):
    if PixelType_Gvsp_BayerGR8 == enGvspPixelType or PixelType_Gvsp_BayerRG8 == enGvspPixelType \
            or PixelType_Gvsp_BayerGB8 == enGvspPixelType or PixelType_Gvsp_BayerBG8 == enGvspPixelType \
            or PixelType_Gvsp_BayerGR10 == enGvspPixelType or PixelType_Gvsp_BayerRG10 == enGvspPixelType \
            or PixelType_Gvsp_BayerGB10 == enGvspPixelType or PixelType_Gvsp_BayerBG10 == enGvspPixelType \
            or PixelType_Gvsp_BayerGR12 == enGvspPixelType or PixelType_Gvsp_BayerRG12 == enGvspPixelType \
            or PixelType_Gvsp_BayerGB12 == enGvspPixelType or PixelType_Gvsp_BayerBG12 == enGvspPixelType \
            or PixelType_Gvsp_BayerGR10_Packed == enGvspPixelType or PixelType_Gvsp_BayerRG10_Packed == enGvspPixelType \
            or PixelType_Gvsp_BayerGB10_Packed == enGvspPixelType or PixelType_Gvsp_BayerBG10_Packed == enGvspPixelType \
            or PixelType_Gvsp_BayerGR12_Packed == enGvspPixelType or PixelType_Gvsp_BayerRG12_Packed == enGvspPixelType \
            or PixelType_Gvsp_BayerGB12_Packed == enGvspPixelType or PixelType_Gvsp_BayerBG12_Packed == enGvspPixelType \
            or PixelType_Gvsp_YUV422_Packed == enGvspPixelType or PixelType_Gvsp_YUV422_YUYV_Packed == enGvspPixelType:
        return True
    else:
        return False


# Mono图像转为python数组
def Mono_numpy(data, nWidth, nHeight):
    data_ = np.frombuffer(data, count=int(nWidth * nHeight), dtype=np.uint8, offset=0)
    data_mono_arr = data_.reshape(nHeight, nWidth)
    numArray = np.zeros([nHeight, nWidth, 1], "uint8")
    numArray[:, :, 0] = data_mono_arr
    return numArray


# 彩色图像转为python数组
def Color_numpy(data, nWidth, nHeight):
    data_ = np.frombuffer(data, count=int(nWidth * nHeight * 3), dtype=np.uint8, offset=0)
    data_r = data_[0:nWidth * nHeight * 3:3]
    data_g = data_[1:nWidth * nHeight * 3:3]
    data_b = data_[2:nWidth * nHeight * 3:3]

    data_r_arr = data_r.reshape(nHeight, nWidth)
    data_g_arr = data_g.reshape(nHeight, nWidth)
    data_b_arr = data_b.reshape(nHeight, nWidth)
    numArray = np.zeros([nHeight, nWidth, 3], "uint8")

    numArray[:, :, 0] = data_r_arr
    numArray[:, :, 1] = data_g_arr
    numArray[:, :, 2] = data_b_arr
    return numArray


class Rectangle():
    def __init__(self, array=None, x=0, y=0, w=0, h=0, line_width=0):
        self.array = array
        self.x = x
        self.y = y
        self.w = w
        self.h = h
        self.line_width = line_width
        
    def draw_line(self, y_0, y_1, x_0, x_1):
        for i in range(y_0, y_1):
            for j in range(1280 * i + x_0, 1280 * i + x_1):
                self.array[j] = 255

    def draw(self):
        self.draw_line(self.y, self.y + self.h, self.x, self.x + self.line_width)   
        self.draw_line(self.y, self.y + self.line_width, self.x, self.x + self.w + self.line_width) 
        self.draw_line(self.y, self.y + self.h, self.x + self.w, self.x + self.w + self.line_width)   
        self.draw_line(self.y + self.h, self.y + self.h + self.line_width, self.x, self.x + self.w + self.line_width)     


# 相机操作类
class CameraOperation:

    def __init__(self, obj_cam, st_device_list, n_connect_num=0, b_open_device=False, b_start_grabbing=False,
                 h_thread_handle=None,
                 b_thread_closed=False, st_frame_info=None, b_exit=False, b_save_bmp=False, b_save_jpg=False,
                 buf_save_image=None,
                 n_save_image_size=0, n_win_gui_id=0, frame_rate=0, exposure_time=0, gain=0, mask = False,
                #  receipe_dict = {}, receipe = '', mask_min_cap=None, mask_max_cap=None, 
                 mask_min_level=None, mask_max_level=None):

        self.obj_cam = obj_cam
        self.st_device_list = st_device_list
        self.n_connect_num = n_connect_num
        self.b_open_device = b_open_device
        self.b_start_grabbing = b_start_grabbing
        self.b_thread_closed = b_thread_closed
        self.st_frame_info = st_frame_info
        self.b_exit = b_exit
        self.b_save_bmp = b_save_bmp
        self.b_save_jpg = b_save_jpg
        self.buf_save_image = buf_save_image
        self.n_save_image_size = n_save_image_size
        self.h_thread_handle = h_thread_handle
        self.b_thread_closed
        self.frame_rate = frame_rate
        self.exposure_time = exposure_time
        self.gain = gain
        self.buf_lock = threading.Lock()  # 取图和存图的buffer锁
        self.mask = mask
        # self.receipe_dict = receipe_dict
        # self.receipe = receipe
        # self.mask_min_cap = mask_min_cap
        # self.mask_max_cap = mask_max_cap
        # self.mask_min_level = mask_min_level
        # self.mask_max_level = mask_max_level

        self.stOutFrame = ctypes.c_long(0)

    # 打开相机
    def Open_device(self):

        if not self.b_open_device:
            if self.n_connect_num < 0:
                return MV_E_CALLORDER

            # ch:选择设备并创建句柄 | en:Select device and create handle
            nConnectionNum = int(self.n_connect_num)
            stDeviceList = cast(self.st_device_list.pDeviceInfo[int(nConnectionNum)],
                                POINTER(MV_CC_DEVICE_INFO)).contents
            self.obj_cam = MvCamera()
            ret = self.obj_cam.MV_CC_CreateHandle(stDeviceList)
            if ret != 0:
                self.obj_cam.MV_CC_DestroyHandle()
                return ret

            ret = self.obj_cam.MV_CC_OpenDevice()
            if ret != 0:
                return ret
            print("open device successfully!")
            self.b_open_device = True
            self.b_thread_closed = False

            # ch:探测网络最佳包大小(只对GigE相机有效) | en:Detection network optimal package size(It only works for the GigE camera)
            if stDeviceList.nTLayerType == MV_GIGE_DEVICE:
                nPacketSize = self.obj_cam.MV_CC_GetOptimalPacketSize()
                if int(nPacketSize) > 0:
                    ret = self.obj_cam.MV_CC_SetIntValue("GevSCPSPacketSize", nPacketSize)
                    if ret != 0:
                        print("warning: set packet size fail! ret[0x%x]" % ret)
                else:
                    print("warning: set packet size fail! ret[0x%x]" % nPacketSize)

            stBool = c_bool(False)
            ret = self.obj_cam.MV_CC_GetBoolValue("AcquisitionFrameRateEnable", stBool)
            if ret != 0:
                print("get acquisition frame rate enable fail! ret[0x%x]" % ret)

            # ch:设置触发模式为off | en:Set trigger mode as off
            ret = self.obj_cam.MV_CC_SetEnumValue("TriggerMode", MV_TRIGGER_MODE_OFF)
            if ret != 0:
                print("set trigger mode fail! ret[0x%x]" % ret)
            return MV_OK
        
        # data = s.recvfrom(1024)    
        # controller_ip = data[1][0]
        # controller_port = data[1][1]

    # 开始取图
    def Start_grabbing(self, winHandle):
        if not self.b_start_grabbing and self.b_open_device:
            self.b_exit = False
            ret = self.obj_cam.MV_CC_StartGrabbing()
            if ret != 0:
                return ret
            self.b_start_grabbing = True
            print("start grabbing successfully!")
            try:
                thread_id = random.randint(1, 10000)
                self.h_thread_handle = threading.Thread(target=CameraOperation.Work_thread, args=(self, winHandle))
                self.h_thread_handle.start()
                self.b_thread_closed = True
            finally:
                pass
            return MV_OK

        return MV_E_CALLORDER
    
    def Start_grabbing2(self):
        ret = self.obj_cam.MV_CC_StartGrabbing()
        if ret != 0:
            return ret
        self.b_start_grabbing = True
        print("start grabbing successfully!")
        
        # Инициализация структуры для получения кадра
        self.stOutFrame = MV_FRAME_OUT()
        memset(byref(self.stOutFrame), 0, sizeof(self.stOutFrame))
        
        return MV_OK


    def frame_get(self):
        ret = self.obj_cam.MV_CC_GetImageBuffer(self.stOutFrame, 1000)
        if ret != 0:
            print("no data, ret = " + To_hex_str(ret))
            return None

        # Если буфер для сохранения еще не создан, создаем его
        if self.buf_save_image is None:
            self.buf_save_image = (c_ubyte * self.stOutFrame.stFrameInfo.nFrameLen)()
        self.st_frame_info = self.stOutFrame.stFrameInfo

        # Копируем данные
        self.buf_lock.acquire()
        cdll.msvcrt.memcpy(byref(self.buf_save_image), self.stOutFrame.pBufAddr, self.st_frame_info.nFrameLen)
        self.buf_lock.release()

        # Преобразуем в numpy array
        frame = np.frombuffer(self.buf_save_image, dtype=np.uint8)
        # Предполагается, что изображение имеет размер 960x1280 и тип BayerGR8, поэтому конвертируем в BGR
        frame = frame.reshape(960, 1280)
        frame = cv2.cvtColor(frame, cv2.COLOR_BayerGR2BGR)

        # Освобождаем буфер камеры
        self.obj_cam.MV_CC_FreeImageBuffer(self.stOutFrame)

        return frame


    # 停止取图
    def Stop_grabbing(self):
        if self.b_start_grabbing and self.b_open_device:
            # 退出线程
            if self.b_thread_closed:
                Stop_thread(self.h_thread_handle)
                self.b_thread_closed = False
            ret = self.obj_cam.MV_CC_StopGrabbing()
            if ret != 0:
                return ret
            print("stop grabbing successfully!")
            self.b_start_grabbing = False
            self.b_exit = True

            cv2.destroyAllWindows()

            return MV_OK
        else:
            return MV_E_CALLORDER

    # 关闭相机
    def Close_device(self):
        if self.b_open_device:
            # 退出线程
            if self.b_thread_closed:
                Stop_thread(self.h_thread_handle)
                self.b_thread_closed = False
            ret = self.obj_cam.MV_CC_CloseDevice()
            if ret != 0:
                return ret

        # ch:销毁句柄 | Destroy handle
        self.obj_cam.MV_CC_DestroyHandle()
        self.b_open_device = False
        self.b_start_grabbing = False
        self.b_exit = True
        print("close device successfully!")

        return MV_OK

    # 设置触发模式
    def Set_trigger_mode(self, is_trigger_mode):
        if not self.b_open_device:
            return MV_E_CALLORDER

        if not is_trigger_mode:
            ret = self.obj_cam.MV_CC_SetEnumValue("TriggerMode", 0)
            if ret != 0:
                return ret
        else:
            ret = self.obj_cam.MV_CC_SetEnumValue("TriggerMode", 1)
            if ret != 0:
                return ret
            ret = self.obj_cam.MV_CC_SetEnumValue("TriggerSource", 7)
            if ret != 0:
                return ret

        return MV_OK

    # 软触发一次
    def Trigger_once(self):
        if self.b_open_device:
            return self.obj_cam.MV_CC_SetCommandValue("TriggerSoftware")

    # 获取参数
    def Get_parameter(self):
        if self.b_open_device:
            stFloatParam_FrameRate = MVCC_FLOATVALUE()
            memset(byref(stFloatParam_FrameRate), 0, sizeof(MVCC_FLOATVALUE))
            stFloatParam_exposureTime = MVCC_FLOATVALUE()
            memset(byref(stFloatParam_exposureTime), 0, sizeof(MVCC_FLOATVALUE))
            stFloatParam_gain = MVCC_FLOATVALUE()
            memset(byref(stFloatParam_gain), 0, sizeof(MVCC_FLOATVALUE))
            ret = self.obj_cam.MV_CC_GetFloatValue("AcquisitionFrameRate", stFloatParam_FrameRate)
            if ret != 0:
                return ret
            self.frame_rate = stFloatParam_FrameRate.fCurValue

            ret = self.obj_cam.MV_CC_GetFloatValue("ExposureTime", stFloatParam_exposureTime)
            if ret != 0:
                return ret
            self.exposure_time = stFloatParam_exposureTime.fCurValue

            ret = self.obj_cam.MV_CC_GetFloatValue("Gain", stFloatParam_gain)
            if ret != 0:
                return ret
            self.gain = stFloatParam_gain.fCurValue

            return MV_OK

    # 设置参数
    def Set_parameter(self, frameRate, exposureTime, gain):
        if '' == frameRate or '' == exposureTime or '' == gain:
            print('show info', 'please type in the text box !')
            return MV_E_PARAMETER
        if self.b_open_device:
            ret = self.obj_cam.MV_CC_SetEnumValue("ExposureAuto", 0)
            time.sleep(0.2)
            ret = self.obj_cam.MV_CC_SetFloatValue("ExposureTime", float(exposureTime))
            if ret != 0:
                print('show error', 'set exposure time fail! ret = ' + To_hex_str(ret))
                return ret

            ret = self.obj_cam.MV_CC_SetFloatValue("Gain", float(gain))
            if ret != 0:
                print('show error', 'set gain fail! ret = ' + To_hex_str(ret))
                return ret

            ret = self.obj_cam.MV_CC_SetFloatValue("AcquisitionFrameRate", float(frameRate))
            if ret != 0:
                print('show error', 'set acquistion frame rate fail! ret = ' + To_hex_str(ret))
                return ret

            print('show info', 'set parameter success!')

            return MV_OK

    # 取图线程函数
    def Work_thread(self, winHandle):
        stOutFrame = MV_FRAME_OUT()
        memset(byref(stOutFrame), 0, sizeof(stOutFrame))

        # mask_cap_min_receipe = np.array(self.receipe_dict[self.receipe][0].split(', '), np.uint8)
        # mask_cap_max_receipe = np.array(self.receipe_dict[self.receipe][1].split(', '), np.uint8)
        # mask_level_min_receipe = np.array(self.receipe_dict[self.receipe][2].split(', '), np.uint8)
        # mask_level_max_receipe = np.array(self.receipe_dict[self.receipe][3].split(', '), np.uint8)

        # if self.mask == True:
        #     cv2.namedWindow('cap', cv2.WINDOW_NORMAL)
        #     cv2.namedWindow('level', cv2.WINDOW_NORMAL)

        #     cv2.createTrackbar('HL', 'cap', 0, 255, pass_func)
        #     cv2.createTrackbar('SL', 'cap', 0, 255, pass_func)
        #     cv2.createTrackbar('VL', 'cap', 0, 255, pass_func)
        #     cv2.createTrackbar('HM', 'cap', 145, 255, pass_func)
        #     cv2.createTrackbar('SM', 'cap', 255, 255, pass_func)
        #     cv2.createTrackbar('VM', 'cap', 255, 255, pass_func)
            
        #     cv2.createTrackbar('HL', 'level', 0, 255, pass_func)
        #     cv2.createTrackbar('SL', 'level', 0, 255, pass_func)
        #     cv2.createTrackbar('VL', 'level', 0, 255, pass_func)
        #     cv2.createTrackbar('HM', 'level', 95, 255, pass_func)
        #     cv2.createTrackbar('SM', 'level', 255, 255, pass_func)
        #     cv2.createTrackbar('VM', 'level', 255, 255, pass_func)

        while True:
            #data = b'0'
            ret = self.obj_cam.MV_CC_GetImageBuffer(stOutFrame, 1000)

            if 0 == ret:
                # 拷贝图像和图像信息
                if self.buf_save_image is None:
                    self.buf_save_image = (c_ubyte * stOutFrame.stFrameInfo.nFrameLen)()
                self.st_frame_info = stOutFrame.stFrameInfo

                # 获取缓存锁
                self.buf_lock.acquire()
                cdll.msvcrt.memcpy(byref(self.buf_save_image), stOutFrame.pBufAddr, self.st_frame_info.nFrameLen)
                self.buf_lock.release()

                # if self.mask == True:
                #     hl = cv2.getTrackbarPos('HL','cap')
                #     sl = cv2.getTrackbarPos('SL','cap')
                #     vl = cv2.getTrackbarPos('VL','cap')
                #     hm = cv2.getTrackbarPos('HM','cap')
                #     sm = cv2.getTrackbarPos('SM','cap')
                #     vm = cv2.getTrackbarPos('VM','cap')

                #     mask_min_cap = np.array((hl, sl, vl), np.uint8)
                #     mask_max_cap = np.array((hm, sm, vm), np.uint8)
                #     self.mask_min_cap = mask_min_cap
                #     self.mask_max_cap = mask_max_cap

                #     hl = cv2.getTrackbarPos('HL','level')
                #     sl = cv2.getTrackbarPos('SL','level')
                #     vl = cv2.getTrackbarPos('VL','level')
                #     hm = cv2.getTrackbarPos('HM','level')
                #     sm = cv2.getTrackbarPos('SM','level')
                #     vm = cv2.getTrackbarPos('VM','level')

                #     mask_min_level = np.array((hl, sl, vl), np.uint8)
                #     mask_max_level = np.array((hm, sm, vm), np.uint8)
                #     self.mask_min_level = mask_min_level
                #     self.mask_max_level = mask_max_level

                # else:
                #     mask_min_cap = mask_cap_min_receipe
                #     mask_max_cap = mask_cap_max_receipe 

                #     mask_min_level = mask_level_min_receipe
                #     mask_max_level = mask_level_max_receipe

                # frame = np.array(self.buf_save_image)
                # frame = frame.reshape(960, 1280)
                # frame = cv2.cvtColor(frame, cv2.COLOR_BayerGR2BGR)

                # mask_cap = frame[:107, 547:742]
                # mask_cap = cv2.inRange(mask_cap, mask_min_cap, mask_max_cap)
                # mask_level = frame[270:700, 547:742]
                # mask_level = cv2.inRange(mask_level, mask_min_level, mask_max_level)

                # contours, _ = cv2.findContours(mask_cap,cv2.RETR_LIST,cv2.CHAIN_APPROX_SIMPLE)
                # area_max = 0
                # for cnt in contours:
                #     area = cv2.contourArea(cnt)
                #     if area > 4000:
                #         [x,y,w,h] = cv2.boundingRect(cnt)
                #         Rectangle(self.buf_save_image, x+547, y, w, h, 10)
                #         if area > area_max:
                #             area_max = area 
                #             rectangle_max = Rectangle(self.buf_save_image, x+547, y, w, h, 10)

                # if area_max > 0:
                #     rectangle_max.draw()

                # contours, _ = cv2.findContours(mask_level,cv2.RETR_LIST,cv2.CHAIN_APPROX_SIMPLE)
                # level = 700
                # for cnt in contours:
                #     area = cv2.contourArea(cnt)
                #     if area > 200:
                #         [x,y,w,h] = cv2.boundingRect(cnt)
                #         if y < level:
                #             level = y
                #             rectangle_level = Rectangle(self.buf_save_image, x+547, y+270, w, h, 10)

                # if level < 700:
                #     rectangle_level.draw()

                # if area_max > 0 and level < 700:
                #     data = b'1'

                # if self.mask == True:
                #     cv2.imshow('cap', mask_cap)
                #     cv2.imshow('level', mask_level)
                    
                #s.sendto(data, ('192.168.1.241', 62064))

                if cv2.waitKey(1) & 0xFF == ord('q'):
                    break  

                #print("get one frame: Width[%d], Height[%d], nFrameNum[%d]"
                #      % (self.st_frame_info.nWidth, self.st_frame_info.nHeight, self.st_frame_info.nFrameNum))
                # 释放缓存
                self.obj_cam.MV_CC_FreeImageBuffer(stOutFrame)
            else:
                print("no data, ret = " + To_hex_str(ret))
                continue

            # 使用Display接口显示图像
            stDisplayParam = MV_DISPLAY_FRAME_INFO()
            memset(byref(stDisplayParam), 0, sizeof(stDisplayParam))
            stDisplayParam.hWnd = int(winHandle)
            stDisplayParam.nWidth = self.st_frame_info.nWidth
            stDisplayParam.nHeight = self.st_frame_info.nHeight
            stDisplayParam.enPixelType = self.st_frame_info.enPixelType
            stDisplayParam.pData = self.buf_save_image
            stDisplayParam.nDataLen = self.st_frame_info.nFrameLen
            self.obj_cam.MV_CC_DisplayOneFrame(stDisplayParam)

            # 是否退出
            if self.b_exit:
                if self.buf_save_image is not None:
                    del self.buf_save_image
                break

    # 存jpg图像
    def Save_jpg(self):

        if self.buf_save_image is None:
            return

        # 获取缓存锁
        self.buf_lock.acquire()

        file_path = str(self.st_frame_info.nFrameNum) + ".jpg"
        c_file_path = file_path.encode('ascii')
        stSaveParam = MV_SAVE_IMAGE_TO_FILE_PARAM_EX()
        stSaveParam.enPixelType = self.st_frame_info.enPixelType  # ch:相机对应的像素格式 | en:Camera pixel type
        stSaveParam.nWidth = self.st_frame_info.nWidth  # ch:相机对应的宽 | en:Width
        stSaveParam.nHeight = self.st_frame_info.nHeight  # ch:相机对应的高 | en:Height
        stSaveParam.nDataLen = self.st_frame_info.nFrameLen
        stSaveParam.pData = cast(self.buf_save_image, POINTER(c_ubyte))
        stSaveParam.enImageType = MV_Image_Jpeg  # ch:需要保存的图像类型 | en:Image format to save
        stSaveParam.nQuality = 80
        stSaveParam.pcImagePath = ctypes.create_string_buffer(c_file_path)
        stSaveParam.iMethodValue = 2
        ret = self.obj_cam.MV_CC_SaveImageToFileEx(stSaveParam)

        self.buf_lock.release()
        return ret

    # 存BMP图像
    def Save_Bmp(self):

        if 0 == self.buf_save_image:
            return

        # 获取缓存锁
        self.buf_lock.acquire()

        file_path = str(self.st_frame_info.nFrameNum) + ".bmp"
        c_file_path = file_path.encode('ascii')

        stSaveParam = MV_SAVE_IMAGE_TO_FILE_PARAM_EX()
        stSaveParam.enPixelType = self.st_frame_info.enPixelType  # ch:相机对应的像素格式 | en:Camera pixel type
        stSaveParam.nWidth = self.st_frame_info.nWidth  # ch:相机对应的宽 | en:Width
        stSaveParam.nHeight = self.st_frame_info.nHeight  # ch:相机对应的高 | en:Height
        stSaveParam.nDataLen = self.st_frame_info.nFrameLen
        stSaveParam.pData = cast(self.buf_save_image, POINTER(c_ubyte))
        stSaveParam.enImageType = MV_Image_Bmp  # ch:需要保存的图像类型 | en:Image format to save
        stSaveParam.nQuality = 8
        stSaveParam.pcImagePath = ctypes.create_string_buffer(c_file_path)
        stSaveParam.iMethodValue = 2
        ret = self.obj_cam.MV_CC_SaveImageToFileEx(stSaveParam)

        self.buf_lock.release()

        return ret

