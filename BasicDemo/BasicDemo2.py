# -*- coding: utf-8 -*-
import sys
from PyQt5.QtWidgets import *
from CamOperation_class import CameraOperation
from MvCameraControl_class import *
from MvErrorDefine_const import *
from CameraParams_header import *
from PyUICBasicDemo import Ui_MainWindow
import ctypes
import csv


# Get device information
def TxtWrapBy(start_str, end, all):
    start = all.find(start_str)
    if start >= 0:
        start += len(start_str)
        end = all.find(end, start)
        if end >= 0:
            return all[start:end].strip()


# Error code to hex
def ToHexStr(num):
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


def convert(par, idx):
    value = ''
    for i in par:
        value = value + str(i) + ', '
    value = value[:len(value) - 2]
    return value


class CameraApp:
    def __init__(self):
        self.deviceList = MV_CC_DEVICE_INFO_LIST()
        self.cam = MvCamera()
        self.nSelCamIndex = 0
        self.obj_cam_operation = None
        self.isOpen = False
        self.isGrabbing = False
        self.isCalibMode = True
        self.mask_iter = 0
        self.mainWindow = None
        self.ui = None
        
    def setup_ui(self, mainWindow, ui):
        self.mainWindow = mainWindow
        self.ui = ui
        
        # Connect signals to slots
        self.ui.bnEnum.clicked.connect(self.enum_devices)
        self.ui.bnOpen.clicked.connect(self.open_device)
        self.ui.bnClose.clicked.connect(self.close_device)
        self.ui.bnStart.clicked.connect(self.start_grabbing)
        self.ui.bnStop.clicked.connect(self.stop_grabbing)

        self.ui.bnSoftwareTrigger.clicked.connect(self.trigger_once)
        self.ui.radioTriggerMode.clicked.connect(self.set_software_trigger_mode)
        self.ui.radioContinueMode.clicked.connect(self.set_continue_mode)

        self.ui.bnGetParam.clicked.connect(self.get_param)
        self.ui.bnSetParam.clicked.connect(self.set_param)
        # self.ui.bnMaskParam.clicked.connect(self.mask_param)
        # self.ui.bnSaveReceipe.clicked.connect(self.save_receipe)

        self.ui.bnSaveImage.clicked.connect(self.save_bmp)
        
        # Initial UI state
        self.enable_controls()

    # bind id to information marker
    def xFunc(self, event):
        self.nSelCamIndex = TxtWrapBy("[", "]", self.ui.ComboDevices.get())

    # Decoding Characters
    def decoding_char(self, c_ubyte_value):
        c_char_p_value = ctypes.cast(c_ubyte_value, ctypes.c_char_p)
        try:
            decode_str = c_char_p_value.value.decode('gbk')  # Chinese characters
        except UnicodeDecodeError:
            decode_str = str(c_char_p_value.value)
        return decode_str

    # enum devices
    def enum_devices(self):
        self.deviceList = MV_CC_DEVICE_INFO_LIST()
        ret = MvCamera.MV_CC_EnumDevices(MV_GIGE_DEVICE | MV_USB_DEVICE, self.deviceList)
        if ret != 0:
            strError = "Enum devices fail! ret = :" + ToHexStr(ret)
            QMessageBox.warning(self.mainWindow, "Error", strError, QMessageBox.Ok)
            return ret

        if self.deviceList.nDeviceNum == 0:
            QMessageBox.warning(self.mainWindow, "Info", "Find no device", QMessageBox.Ok)
            return ret
        print("Find %d devices!" % self.deviceList.nDeviceNum)

        devList = []
        for i in range(0, self.deviceList.nDeviceNum):
            mvcc_dev_info = cast(self.deviceList.pDeviceInfo[i], POINTER(MV_CC_DEVICE_INFO)).contents
            if mvcc_dev_info.nTLayerType == MV_GIGE_DEVICE:
                print("\ngige device: [%d]" % i)
                user_defined_name = self.decoding_char(mvcc_dev_info.SpecialInfo.stGigEInfo.chUserDefinedName)
                model_name = self.decoding_char(mvcc_dev_info.SpecialInfo.stGigEInfo.chModelName)
                print("device user define name: " + user_defined_name)
                print("device model name: " + model_name)

                nip1 = ((mvcc_dev_info.SpecialInfo.stGigEInfo.nCurrentIp & 0xff000000) >> 24)
                nip2 = ((mvcc_dev_info.SpecialInfo.stGigEInfo.nCurrentIp & 0x00ff0000) >> 16)
                nip3 = ((mvcc_dev_info.SpecialInfo.stGigEInfo.nCurrentIp & 0x0000ff00) >> 8)
                nip4 = (mvcc_dev_info.SpecialInfo.stGigEInfo.nCurrentIp & 0x000000ff)
                print("current ip: %d.%d.%d.%d " % (nip1, nip2, nip3, nip4))
                devList.append(
                    "[" + str(i) + "]GigE: " + user_defined_name + " " + model_name + "(" + str(nip1) + "." + str(
                        nip2) + "." + str(nip3) + "." + str(nip4) + ")")
            elif mvcc_dev_info.nTLayerType == MV_USB_DEVICE:
                print("\nu3v device: [%d]" % i)
                user_defined_name = self.decoding_char(mvcc_dev_info.SpecialInfo.stUsb3VInfo.chUserDefinedName)
                model_name = self.decoding_char(mvcc_dev_info.SpecialInfo.stUsb3VInfo.chModelName)
                print("device user define name: " + user_defined_name)
                print("device model name: " + model_name)

                strSerialNumber = ""
                for per in mvcc_dev_info.SpecialInfo.stUsb3VInfo.chSerialNumber:
                    if per == 0:
                        break
                    strSerialNumber = strSerialNumber + chr(per)
                print("user serial number: " + strSerialNumber)
                devList.append("[" + str(i) + "]USB: " + user_defined_name + " " + model_name
                               + "(" + str(strSerialNumber) + ")")

        self.ui.ComboDevices.clear()
        self.ui.ComboDevices.addItems(devList)
        self.ui.ComboDevices.setCurrentIndex(0)

    # open device
    def open_device(self):
        if self.isOpen:
            QMessageBox.warning(self.mainWindow, "Error", 'Camera is Running!', QMessageBox.Ok)
            return MV_E_CALLORDER

        self.nSelCamIndex = self.ui.ComboDevices.currentIndex()
        if self.nSelCamIndex < 0:
            QMessageBox.warning(self.mainWindow, "Error", 'Please select a camera!', QMessageBox.Ok)
            return MV_E_CALLORDER

        print('self.cam, self.deviceList, self.nSelCamIndex', self.cam, self.deviceList, self.nSelCamIndex)
        self.obj_cam_operation = CameraOperation(self.cam, self.deviceList, self.nSelCamIndex)
        ret = self.obj_cam_operation.Open_device()
        if 0 != ret:
            strError = "Open device failed ret:" + ToHexStr(ret)
            QMessageBox.warning(self.mainWindow, "Error", strError, QMessageBox.Ok)
            self.isOpen = False
        else:
            self.set_continue_mode()

            self.get_param()

            self.isOpen = True
            self.enable_controls()

        # with open('receipes.csv') as f:
        #     reader = csv.DictReader(f)

        #     for row in reader:
        #         self.obj_cam_operation.receipe_dict[row['receipe']] = [row['mask_cap_min'], row['mask_cap_max'], 
        #                                     row['mask_level_min'], row['mask_level_max']]
        
        # self.ui.ComboDevices_receipe.clear()
        # self.ui.ComboDevices_receipe.addItems(self.obj_cam_operation.receipe_dict.keys())

    # Start grab image
    def start_grabbing(self):
        self.obj_cam_operation.receipe = self.ui.ComboDevices_receipe.currentText()

        ret = self.obj_cam_operation.Start_grabbing(self.ui.widgetDisplay.winId())
        if ret != 0:
            strError = "Start grabbing failed ret:" + ToHexStr(ret)
            QMessageBox.warning(self.mainWindow, "Error", strError, QMessageBox.Ok)
        else:
            self.isGrabbing = True
            self.enable_controls()

    # Stop grab image
    def stop_grabbing(self):
        ret = self.obj_cam_operation.Stop_grabbing()
        if ret != 0:
            strError = "Stop grabbing failed ret:" + ToHexStr(ret)
            QMessageBox.warning(self.mainWindow, "Error", strError, QMessageBox.Ok)
        else:
            self.isGrabbing = False
            self.enable_controls()

    # Close device
    def close_device(self):
        if self.isOpen:
            self.obj_cam_operation.Close_device()
            self.isOpen = False

        self.isGrabbing = False
        self.enable_controls()

    # set trigger mode
    def set_continue_mode(self):
        ret = self.obj_cam_operation.Set_trigger_mode(False)
        if ret != 0:
            strError = "Set continue mode failed ret:" + ToHexStr(ret) + " mode is " + str(is_trigger_mode)
            QMessageBox.warning(self.mainWindow, "Error", strError, QMessageBox.Ok)
        else:
            self.ui.radioContinueMode.setChecked(True)
            self.ui.radioTriggerMode.setChecked(False)
            self.ui.bnSoftwareTrigger.setEnabled(False)

    # set software trigger mode
    def set_software_trigger_mode(self):
        ret = self.obj_cam_operation.Set_trigger_mode(True)
        if ret != 0:
            strError = "Set trigger mode failed ret:" + ToHexStr(ret)
            QMessageBox.warning(self.mainWindow, "Error", strError, QMessageBox.Ok)
        else:
            self.ui.radioContinueMode.setChecked(False)
            self.ui.radioTriggerMode.setChecked(True)
            self.ui.bnSoftwareTrigger.setEnabled(self.isGrabbing)

    # set trigger software
    def trigger_once(self):
        ret = self.obj_cam_operation.Trigger_once()
        if ret != 0:
            strError = "TriggerSoftware failed ret:" + ToHexStr(ret)
            QMessageBox.warning(self.mainWindow, "Error", strError, QMessageBox.Ok)

    # save image
    def save_bmp(self):
        ret = self.obj_cam_operation.Save_Bmp()
        if ret != MV_OK:
            strError = "Save BMP failed ret:" + ToHexStr(ret)
            QMessageBox.warning(self.mainWindow, "Error", strError, QMessageBox.Ok)
        else:
            print("Save image success")

    # get param
    def get_param(self):
        ret = self.obj_cam_operation.Get_parameter()
        if ret != MV_OK:
            strError = "Get param failed ret:" + ToHexStr(ret)
            QMessageBox.warning(self.mainWindow, "Error", strError, QMessageBox.Ok)
        else:
            self.ui.edtExposureTime.setText("{0:.2f}".format(self.obj_cam_operation.exposure_time))
            self.ui.edtGain.setText("{0:.2f}".format(self.obj_cam_operation.gain))
            self.ui.edtFrameRate.setText("{0:.2f}".format(self.obj_cam_operation.frame_rate))

    # set param
    def set_param(self):
        frame_rate = self.ui.edtFrameRate.text()
        exposure = self.ui.edtExposureTime.text()
        gain = self.ui.edtGain.text()
        ret = self.obj_cam_operation.Set_parameter(frame_rate, exposure, gain)
        if ret != MV_OK:
            strError = "Set param failed ret:" + ToHexStr(ret)
            QMessageBox.warning(self.mainWindow, "Error", strError, QMessageBox.Ok)

        return MV_OK
    
    # def mask_param(self):
    #     if self.mask_iter == 0:
    #         self.obj_cam_operation.mask = True
    #         self.mask_iter += 1
    #     else:
    #         self.obj_cam_operation.mask = False
    #         self.mask_iter = 0 

    # def save_receipe(self):
    #     if not self.obj_cam_operation:
    #         return
            
    #     mask_min_cap = convert(self.obj_cam_operation.mask_min_cap, 0) 
    #     mask_max_cap = convert(self.obj_cam_operation.mask_max_cap, 1)
    #     mask_min_level = convert(self.obj_cam_operation.mask_min_level, 2)
    #     mask_max_level = convert(self.obj_cam_operation.mask_max_level, 3)
        
    #     self.obj_cam_operation.receipe_dict[self.obj_cam_operation.receipe] = [
    #         mask_min_cap, mask_max_cap, mask_min_level, mask_max_level
    #     ]

    #     save_dict_csv = []    

    #     for receipe, values in self.obj_cam_operation.receipe_dict.items():
    #         save_dict_csv.append({
    #             'receipe': receipe,
    #             'mask_cap_min': values[0],
    #             'mask_cap_max': values[1],
    #             'mask_level_min': values[2],
    #             'mask_level_max': values[3]
    #         })

    #     with open('receipes.csv', 'w') as f:
    #         writer = csv.DictWriter(
    #             f, fieldnames=list(save_dict_csv[0].keys()), quoting=csv.QUOTE_NONNUMERIC)
    #         writer.writeheader()

    #         for d in save_dict_csv:
    #             writer.writerow(d)     

    # set enable status
    def enable_controls(self):
        # group, element
        self.ui.groupGrab.setEnabled(self.isOpen)
        self.ui.groupParam.setEnabled(self.isOpen)

        self.ui.bnOpen.setEnabled(not self.isOpen)
        self.ui.bnClose.setEnabled(self.isOpen)

        self.ui.bnStart.setEnabled(self.isOpen and (not self.isGrabbing))
        self.ui.bnStop.setEnabled(self.isOpen and self.isGrabbing)
        self.ui.bnSoftwareTrigger.setEnabled(self.isGrabbing and self.ui.radioTriggerMode.isChecked())

        self.ui.bnSaveImage.setEnabled(self.isOpen and self.isGrabbing)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    mainWindow = QMainWindow()
    ui = Ui_MainWindow()
    ui.setupUi(mainWindow)
    
    # Create camera app instance and setup UI
    camera_app = CameraApp()
    camera_app.setup_ui(mainWindow, ui)
    
    mainWindow.show()
    app.exec_()
    
    # Cleanup
    camera_app.close_device()
    sys.exit()