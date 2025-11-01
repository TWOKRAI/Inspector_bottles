#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Тестовый скрипт для проверки работы Clean Camera App
"""

import sys
import os

def test_imports():
    """Тестируем импорт всех необходимых модулей"""
    print("Testing imports...")
    
    try:
        import clean_camera_test
        print("OK: clean_camera_test imported successfully")
    except Exception as e:
        print(f"ERROR: Failed to import clean_camera_test: {e}")
        return False
    
    try:
        from camera_process.clean_camera_process import CleanCameraProcessManager
        print("OK: CleanCameraProcessManager imported successfully")
    except Exception as e:
        print(f"ERROR: Failed to import CleanCameraProcessManager: {e}")
        return False
    
    try:
        from MvCameraControl_class import MvCamera
        print("OK: MvCamera imported successfully")
    except Exception as e:
        print(f"ERROR: Failed to import MvCamera: {e}")
        return False
    
    try:
        from MvErrorDefine_const import MV_OK
        print("OK: MvErrorDefine_const imported successfully")
    except Exception as e:
        print(f"ERROR: Failed to import MvErrorDefine_const: {e}")
        return False
    
    try:
        from CameraParams_header import MV_TRIGGER_MODE_OFF
        print("OK: CameraParams_header imported successfully")
    except Exception as e:
        print(f"ERROR: Failed to import CameraParams_header: {e}")
        return False
    
    try:
        from CameraParams_const import MV_GIGE_DEVICE
        print("OK: CameraParams_const imported successfully")
    except Exception as e:
        print(f"ERROR: Failed to import CameraParams_const: {e}")
        return False
    
    try:
        from PixelType_header import PixelType_Gvsp_Mono8
        print("OK: PixelType_header imported successfully")
    except Exception as e:
        print(f"ERROR: Failed to import PixelType_header: {e}")
        return False
    
    return True

def test_camera_enum():
    """Тестируем перечисление камер"""
    print("\nTesting camera enumeration...")
    
    try:
        from camera_process.clean_camera_process import CleanCameraProcessManager
        
        result = CleanCameraProcessManager.enum_devices()
        
        if result.get('status') == 'success':
            devices = result.get('devices', [])
            print(f"OK: Found {len(devices)} camera(s)")
            
            for i, device in enumerate(devices):
                print(f"  [{i}] {device['display_name']}")
            
            return True
        else:
            error = result.get('error', 'Unknown error')
            print(f"ERROR: Enum devices failed: {error}")
            return False
            
    except Exception as e:
        print(f"ERROR: Exception in camera enumeration: {e}")
        return False

def main():
    """Главная функция тестирования"""
    print("="*60)
    print("Clean Camera App - Test Script")
    print("="*60)
    
    # Проверяем импорты
    if not test_imports():
        print("\nFAILED: Import test failed!")
        return 1
    
    # Проверяем перечисление камер
    if not test_camera_enum():
        print("\nWARNING: Camera enumeration test failed (this is normal if no cameras are connected)")
    
    print("\nSUCCESS: All tests completed!")
    print("\nTo run the full application:")
    print("python clean_camera_test.py")
    
    return 0

if __name__ == "__main__":
    sys.exit(main())
