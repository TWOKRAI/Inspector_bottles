#!/usr/bin/env python
# -*- coding: utf-8 -*-

MV_OK                                        = 0x00000000  # < \~english Successed, no error | \~russian Успех, нет ошибок | \~chinese 成功，无错误

# 通用错误码定义:范围0x80000000-0x800000FF
# General error codes: range 0x80000000-0x800000FF
# Общие коды ошибок: диапазон 0x80000000-0x800000FF
MV_E_HANDLE                                  = 0x80000000  # < \~english Error or invalid handle | \~russian Ошибка или неверный дескриптор | \~chinese 错误或无效的句柄
MV_E_SUPPORT                                 = 0x80000001  # < \~english Not supported function | \~russian Неподдерживаемая функция | \~chinese 不支持的功能
MV_E_BUFOVER                                 = 0x80000002  # < \~english Buffer overflow | \~russian Переполнение буфера | \~chinese 缓存已满
MV_E_CALLORDER                               = 0x80000003  # < \~english Function calling order error | \~russian Ошибка порядка вызова функций | \~chinese 函数调用顺序错误
MV_E_PARAMETER                               = 0x80000004  # < \~english Incorrect parameter | \~russian Неверный параметр | \~chinese 错误的参数
MV_E_RESOURCE                                = 0x80000006  # < \~english Applying resource failed | \~russian Ошибка выделения ресурсов | \~chinese 资源申请失败
MV_E_NODATA                                  = 0x80000007  # < \~english No data | \~russian Нет данных | \~chinese 无数据
MV_E_PRECONDITION                            = 0x80000008  # < \~english Precondition error, or running environment changed | \~russian Ошибка предусловия или изменение среды выполнения | \~chinese 前置条件有误，或运行环境已发生变化
MV_E_VERSION                                 = 0x80000009  # < \~english Version mismatches | \~russian Несовместимость версий | \~chinese 版本不匹配
MV_E_NOENOUGH_BUF                            = 0x8000000A  # < \~english Insufficient memory | \~russian Недостаточно памяти | \~chinese 传入的内存空间不足
MV_E_ABNORMAL_IMAGE                          = 0x8000000B  # < \~english Abnormal image, maybe incomplete image because of lost packet | \~russian Аномальное изображение, возможно неполное из-за потери пакетов | \~chinese 异常图像，可能是丢包导致图像不完整
MV_E_LOAD_LIBRARY                            = 0x8000000C  # < \~english Load library failed | \~russian Ошибка загрузки библиотеки | \~chinese 动态导入DLL失败
MV_E_NOOUTBUF                                = 0x8000000D  # < \~english No Avaliable Buffer | \~russian Нет доступного буфера | \~chinese 没有可输出的缓存
MV_E_UNKNOW                                  = 0x800000FF  # < \~english Unknown error | \~russian Неизвестная ошибка | \~chinese 未知的错误

# GenICam系列错误:范围0x80000100-0x800001FF
# GenICam series errors: range 0x80000100-0x800001FF
# Ошибки GenICam: диапазон 0x80000100-0x800001FF
MV_E_GC_GENERIC                              = 0x80000100  # < \~english General error | \~russian Общая ошибка | \~chinese 通用错误
MV_E_GC_ARGUMENT                             = 0x80000101  # < \~english Illegal parameters | \~russian Неверные параметры | \~chinese 参数非法
MV_E_GC_RANGE                                = 0x80000102  # < \~english The value is out of range | \~russian Значение вне допустимого диапазона | \~chinese 值超出范围
MV_E_GC_PROPERTY                             = 0x80000103  # < \~english Property | \~russian Свойство | \~chinese 属性
MV_E_GC_RUNTIME                              = 0x80000104  # < \~english Running environment error | \~russian Ошибка среды выполнения | \~chinese 运行环境有问题
MV_E_GC_LOGICAL                              = 0x80000105  # < \~english Logical error | \~russian Логическая ошибка | \~chinese 逻辑错误
MV_E_GC_ACCESS                               = 0x80000106  # < \~english Node accessing condition error | \~russian Ошибка условия доступа к узлу | \~chinese 节点访问条件有误
MV_E_GC_TIMEOUT                              = 0x80000107  # < \~english Timeout | \~russian Таймаут | \~chinese 超时
MV_E_GC_DYNAMICCAST                          = 0x80000108  # < \~english Transformation exception | \~russian Исключение преобразования | \~chinese 转换异常
MV_E_GC_UNKNOW                               = 0x800001FF  # < \~english GenICam unknown error | \~russian Неизвестная ошибка GenICam | \~chinese GenICam未知错误

# GigE_STATUS对应的错误码:范围0x80000200-0x800002FF
# GigE_STATUS corresponding error codes: range 0x80000200-0x800002FF
# Коды ошибок GigE_STATUS: диапазон 0x80000200-0x800002FF
MV_E_NOT_IMPLEMENTED                         = 0x80000200  # < \~english The command is not supported by device | \~russian Команда не поддерживается устройством | \~chinese 命令不被设备支持
MV_E_INVALID_ADDRESS                         = 0x80000201  # < \~english The target address being accessed does not exist | \~russian Целевой адрес не существует | \~chinese 访问的目标地址不存在
MV_E_WRITE_PROTECT                           = 0x80000202  # < \~english The target address is not writable | \~russian Целевой адрес недоступен для записи | \~chinese 目标地址不可写
MV_E_ACCESS_DENIED                           = 0x80000203  # < \~english No permission | \~russian Нет разрешения | \~chinese 设备无访问权限
MV_E_BUSY                                    = 0x80000204  # < \~english Device is busy, or network disconnected | \~russian Устройство занято или сеть отключена | \~chinese 设备忙，或网络断开
MV_E_PACKET                                  = 0x80000205  # < \~english Network data packet error | \~russian Ошибка сетевого пакета данных | \~chinese 网络包数据错误
MV_E_NETER                                   = 0x80000206  # < \~english Network error | \~russian Сетевая ошибка | \~chinese 网络相关错误
MV_E_IP_CONFLICT                             = 0x80000221  # < \~english Device IP conflict | \~russian Конфликт IP-адресов устройства | \~chinese 设备IP冲突

# USB_STATUS对应的错误码:范围0x80000300-0x800003FF
# USB_STATUS corresponding error codes: range 0x80000300-0x800003FF
# Коды ошибок USB_STATUS: диапазон 0x80000300-0x800003FF
MV_E_USB_READ                                = 0x80000300  # < \~english Reading USB error | \~russian Ошибка чтения USB | \~chinese 读usb出错
MV_E_USB_WRITE                               = 0x80000301  # < \~english Writing USB error | \~russian Ошибка записи USB | \~chinese 写usb出错
MV_E_USB_DEVICE                              = 0x80000302  # < \~english Device exception | \~russian Исключение устройства | \~chinese 设备异常
MV_E_USB_GENICAM                             = 0x80000303  # < \~english GenICam error | \~russian Ошибка GenICam | \~chinese GenICam相关错误
MV_E_USB_BANDWIDTH                           = 0x80000304  # < \~english Insufficient bandwidth, this error code is newly added | \~russian Недостаточная пропускная способность (новый код ошибки) | \~chinese 带宽不足  该错误码新增
MV_E_USB_DRIVER                              = 0x80000305  # < \~english Driver mismatch or unmounted drive | \~russian Несовместимость драйверов или непримонтированный диск | \~chinese 驱动不匹配或者未装驱动
MV_E_USB_UNKNOW                              = 0x800003FF  # < \~english USB unknown error | \~russian Неизвестная ошибка USB | \~chinese USB未知的错误

# 升级时对应的错误码:范围0x80000400-0x800004FF
# Error codes corresponding to upgrade: range 0x80000400-0x800004FF
# Коды ошибок при обновлении: диапазон 0x80000400-0x800004FF
MV_E_UPG_FILE_MISMATCH                       = 0x80000400  # < \~english Firmware mismatches | \~russian Несоответствие прошивки | \~chinese 升级固件不匹配
MV_E_UPG_LANGUSGE_MISMATCH                   = 0x80000401  # < \~english Firmware language mismatches | \~russian Несоответствие языка прошивки | \~chinese 升级固件语言不匹配
MV_E_UPG_CONFLICT                            = 0x80000402  # < \~english Upgrading conflicted (repeated upgrading requests during device upgrade) | \~russian Конфликт обновления (повторные запросы во время обновления) | \~chinese 升级冲突（设备已经在升级了再次请求升级即返回此错误）
MV_E_UPG_INNER_ERR                           = 0x80000403  # < \~english Camera internal error during upgrade | \~russian Внутренняя ошибка камеры во время обновления | \~chinese 升级时设备内部出现错误
MV_E_UPG_UNKNOW                              = 0x800004FF  # < \~english Unknown error during upgrade | \~russian Неизвестная ошибка при обновлении | \~chinese 升级时未知错误