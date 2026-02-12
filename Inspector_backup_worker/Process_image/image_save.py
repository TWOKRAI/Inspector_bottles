# import os
# import cv2

# class ImageSaver:
#     def __init__(self):
#         self.folder_dict = {}

#     def initialize_last_numbers(self, folder_paths, prefix='image', extension='.jpg'):
#         for folder_path in folder_paths:
#             key = (folder_path, prefix, extension)
#             self.folder_dict[key] = self.find_last_number_in_folder(folder_path, prefix, extension)

#     def save_image_with_incremental_number(self, image, folder_path, prefix='image', extension='.jpg'):
#         # Нормализация расширения
#         if not extension.startswith('.'):
#             extension = f".{extension}"
        
#         key = (folder_path, prefix, extension)
#         if not os.path.exists(folder_path):
#             os.makedirs(folder_path)
        
#         last_number = self.folder_dict.get(key, 0)
#         new_file_name = f"{prefix}{last_number + 1}{extension}"
#         new_file_path = os.path.join(folder_path, new_file_name)
        
#         try:
#             cv2.imwrite(new_file_path, image)
#             self.folder_dict[key] = last_number + 1
#             return True
#         except Exception as e:
#             print(f"Ошибка сохранения: {e}")
#             return False

#     def find_last_number_in_folder(self, folder_path, prefix, extension):
#         if not os.path.exists(folder_path):
#             return 0
        
#         max_number = 0
#         for file in os.listdir(folder_path):
#             file_lower = file.lower()
#             ext_lower = extension.lower()
#             if file_lower.startswith(prefix.lower()) and file_lower.endswith(ext_lower):
#                 suffix = file[len(prefix):-len(extension)]
#                 try:
#                     number = int(suffix)
#                     max_number = max(max_number, number)
#                 except ValueError:
#                     continue
#         return max_number


import os
import cv2
import re

class ImageSaver:
    def __init__(self):
        self.folder_dict = {}

    def initialize_last_numbers(self, folder_paths, prefix='image', extension='.jpg', number_suffix='_n', add_suffix='_p'):
        for folder_path in folder_paths:
            key = (folder_path, prefix, extension, number_suffix, add_suffix)
            self.folder_dict[key] = self.find_last_number_in_folder(folder_path, prefix, extension, number_suffix, add_suffix)

    def save_image_with_incremental_number(self, image, folder_path, prefix='image', add='', extension='.jpg', number_suffix='_n', add_suffix='_p'):
        if not extension.startswith('.'):
            extension = f".{extension}"
        
        key = (folder_path, prefix, extension, number_suffix, add_suffix)
        if not os.path.exists(folder_path):
            os.makedirs(folder_path)
        
        if key not in self.folder_dict:
            self.folder_dict[key] = self.find_last_number_in_folder(folder_path, prefix, extension, number_suffix, add_suffix)
        
        last_number = self.folder_dict[key]
        new_file_name = f"{prefix}{number_suffix}{last_number + 1}{add_suffix}{add}{extension}"
        new_file_path = os.path.join(folder_path, new_file_name)
        
        try:
            cv2.imwrite(new_file_path, image)
            self.folder_dict[key] = last_number + 1
            return True
        except Exception as e:
            print(f"Ошибка сохранения: {e}")
            return False

    def find_last_number_in_folder(self, folder_path, prefix, extension, number_suffix, add_suffix):
        if not os.path.exists(folder_path):
            return 0
        
        max_number = 0
        pattern_str = rf'^{re.escape(prefix)}{re.escape(number_suffix)}(\d+){re.escape(add_suffix)}.*{re.escape(extension)}$'
        pattern = re.compile(pattern_str, re.IGNORECASE)
        
        for file in os.listdir(folder_path):
            match = pattern.match(file)
            if match:
                try:
                    number = int(match.group(1))
                    max_number = max(max_number, number)
                except ValueError:
                    continue
        return max_number