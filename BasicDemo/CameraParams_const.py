#!/usr/bin/env python
# -*- coding: utf-8 -*-

# \~chinese 设备类型定义    \~english Device Type Definition    \~russian Определения типов устройств
MV_UNKNOW_DEVICE                             = 0x00000000  # < \~chinese 未知设备类型，保留意义       \~english Unknown Device Type, Reserved       \~russian Неизвестный тип устройства, зарезервировано
MV_GIGE_DEVICE                               = 0x00000001  # < \~chinese GigE设备                     \~english GigE Device                         \~russian GigE устройство
MV_1394_DEVICE                               = 0x00000002  # < \~chinese 1394-a/b 设备                \~english 1394-a/b Device                    \~russian 1394-a/b устройство
MV_USB_DEVICE                                = 0x00000004  # < \~chinese USB 设备                     \~english USB Device                         \~russian USB устройство
MV_CAMERALINK_DEVICE                         = 0x00000008  # < \~chinese CameraLink设备               \~english CameraLink Device                 \~russian CameraLink устройство

INFO_MAX_BUFFER_SIZE                         = 64          # < \~chinese 最大的数据信息大小           \~english Maximum data information size      \~russian Максимальный размер информационных данных

MV_MAX_TLS_NUM                               = 8           # < \~chinese 最多支持的传输层实例个数     \~english The maximum number of supported transport layer instances  \~russian Максимальное количество поддерживаемых экземпляров транспортного уровня
MV_MAX_DEVICE_NUM                            = 256         # < \~chinese 最大支持的设备个数           \~english The maximum number of supported devices  \~russian Максимальное количество поддерживаемых устройств

MV_MAX_GENTL_IF_NUM                          = 256         # < \~chinese 最大支持的GenTL数量          \~english The maximum number of GenTL supported  \~russian Максимальное количество поддерживаемых GenTL
MV_MAX_GENTL_DEV_NUM                         = 256         # < \~chinese 最大支持的GenTL设备数量      \~english The maximum number of GenTL devices supported  \~russian Максимальное количество поддерживаемых GenTL устройств

# \~chinese 设备的访问模式    \~english Device Access Mode    \~russian Режимы доступа к устройству
# \~chinese 独占权限，其他APP只允许读CCP寄存器                        \~english Exclusive authority, other APP is only allowed to read the CCP register  \~russian Эксклюзивный доступ, другие приложения могут только читать CCP регистры
MV_ACCESS_Exclusive                          = 1
# \~chinese 可以从5模式下抢占权限，然后以独占权限打开                 \~english You can seize the authority from the 5 mode, and then open with exclusive authority  \~russian Можно перехватить права из режима 5 и открыть с эксклюзивными правами
MV_ACCESS_ExclusiveWithSwitch                = 2
# \~chinese 控制权限，其他APP允许读所有寄存器                         \~english Control authority, allows other APP reading all registers  \~russian Права контроля, другие приложения могут читать все регистры
MV_ACCESS_Control                            = 3
# \~chinese 可以从5的模式下抢占权限，然后以控制权限打开               \~english You can seize the authority from the 5 mode, and then open with control authority  \~russian Можно перехватить права из режима 5 и открыть с правами контроля
MV_ACCESS_ControlWithSwitch                  = 4
# \~chinese 以可被抢占的控制权限打开                                  \~english Open with seized control authority  \~russian Открыть с правами контроля, которые могут быть перехвачены
MV_ACCESS_ControlSwitchEnable                = 5
# \~chinese 可以从5的模式下抢占权限，然后以可被抢占的控制权限打开     \~english You can seize the authority from the 5 mode, and then open with seized control authority  \~russian Можно перехватить права из режима 5 и открыть с правами контроля, которые могут быть перехвачены
MV_ACCESS_ControlSwitchEnableWithKey         = 6
# \~chinese 读模式打开设备，适用于控制权限下                          \~english Open with read mode and is available under control authority  \~russian Открыть в режиме чтения, доступно при правах контроля
MV_ACCESS_Monitor                            = 7

MV_MATCH_TYPE_NET_DETECT                     = 0x00000001  # < \~chinese 网络流量和丢包信息              \~english Network traffic and packet loss information  \~russian Сетевая статистика и информация о потере пакетов
MV_MATCH_TYPE_USB_DETECT                     = 0x00000002  # < \~chinese host接收到来自U3V设备的字节总数 \~english The total number of bytes host received from U3V device  \~russian Общее количество байт, полученных хостом от U3V устройства

# \~chinese GigEVision IP配置    \~english GigEVision IP Configuration    \~russian Конфигурация IP GigEVision
MV_IP_CFG_STATIC                             = 0x05000000  # < \~chinese 静态         \~english Static         \~russian Статический
MV_IP_CFG_DHCP                               = 0x06000000  # < \~chinese DHCP         \~english DHCP         \~russian DHCP
MV_IP_CFG_LLA                                = 0x04000000  # < \~chinese LLA          \~english LLA          \~russian LLA

# \~chinese GigEVision网络传输模式    \~english GigEVision Net Transfer Mode    \~russian Режимы сетевой передачи GigEVision
MV_NET_TRANS_DRIVER                          = 0x00000001  # < \~chinese 驱动         \~english Driver       \~russian Драйвер
MV_NET_TRANS_SOCKET                          = 0x00000002  # < \~chinese Socket       \~english Socket       \~russian Сокет

# \~chinese CameraLink波特率    \~english CameraLink Baud Rates (CLUINT32)    \~russian Скорости передачи CameraLink
MV_CAML_BAUDRATE_9600                        = 0x00000001  # < \~chinese 9600         \~english 9600         \~russian 9600
MV_CAML_BAUDRATE_19200                       = 0x00000002  # < \~chinese 19200        \~english 19200        \~russian 19200
MV_CAML_BAUDRATE_38400                       = 0x00000004  # < \~chinese 38400        \~english 38400        \~russian 38400
MV_CAML_BAUDRATE_57600                       = 0x00000008  # < \~chinese 57600        \~english 57600        \~russian 57600
MV_CAML_BAUDRATE_115200                      = 0x00000010  # < \~chinese 115200       \~english 115200       \~russian 115200
MV_CAML_BAUDRATE_230400                      = 0x00000020  # < \~chinese 230400       \~english 230400       \~russian 230400
MV_CAML_BAUDRATE_460800                      = 0x00000040  # < \~chinese 460800       \~english 460800       \~russian 460800
MV_CAML_BAUDRATE_921600                      = 0x00000080  # < \~chinese 921600       \~english 921600       \~russian 921600
MV_CAML_BAUDRATE_AUTOMAX                     = 0x40000000  # < \~chinese 最大值       \~english Auto Max     \~russian Авто-максимум

# \~chinese 异常消息类型    \~english Exception message type    \~russian Типы исключительных сообщений
MV_EXCEPTION_DEV_DISCONNECT                  = 0x00008001  # < \~chinese 设备断开连接              \~english The device is disconnected          \~russian Устройство отключено
MV_EXCEPTION_VERSION_CHECK                   = 0x00008002  # < \~chinese SDK与驱动版本不匹配       \~english SDK does not match the driver version  \~russian Версия SDK не совпадает с версией драйвера

MAX_EVENT_NAME_SIZE                          = 128         # < \~chinese 设备Event事件名称最大长度 \~english Max length of event name  \~russian Максимальная длина названия события устройства
MV_MAX_XML_SYMBOLIC_NUM                      = 64          # \~chinese 最大XML符号数               \~english Max XML Symbolic Number  \~russian Максимальное количество XML символов
MV_MAX_SYMBOLIC_LEN                          = 64          # \~chinese 最大枚举条目对应的符号长度     \~english Max Enum Entry Symbolic Number  \~russian Максимальная длина символа для элемента перечисления

MV_MAX_SPLIT_NUM                             = 8           # \~chinese 分时曝光时最多将源图像拆分的个数 \~english The maximum number of source image to be split in time-division exposure  \~russian Максимальное количество разделений исходного изображения при экспозиции с разделением времени