import os
import sys

def combine_files(source_dir, output_file):
    """
    Рекурсивно обходит директорию, объединяет содержимое файлов
    с расширениями .h, .ino, .cpp, .txt в один файл
    """
    # Поддерживаемые расширения (в нижнем регистре)
    valid_extensions = {'.h', '.ino', '.cpp', '.txt'}
    
    with open(output_file, 'w', encoding='utf-8') as outfile:
        for root, dirs, files in os.walk(source_dir):
            for filename in files:
                # Извлекаем расширение файла
                ext = os.path.splitext(filename)[1].lower()
                
                if ext in valid_extensions:
                    # Полный путь к файлу
                    filepath = os.path.join(root, filename)
                    try:
                        # Читаем содержимое файла
                        with open(filepath, 'r', encoding='utf-8') as infile:
                            content = infile.read()
                        
                        # Формируем относительный путь
                        rel_path = os.path.relpath(filepath, source_dir)
                        
                        # Записываем заголовок и содержимое в выходной файл
                        outfile.write(f"=== Файл: {rel_path} ===\n\n")
                        outfile.write(content)
                        outfile.write("\n\n")
                        
                        print(f"Обработан: {rel_path}")
                    
                    except UnicodeDecodeError:
                        print(f"Ошибка кодировки в файле: {filepath}")
                    except Exception as e:
                        print(f"Ошибка при обработке {filepath}: {str(e)}")

if __name__ == "__main__":
    # Проверяем аргументы командной строки
    if len(sys.argv) != 3:
        print("Использование: python combine_files.py <исходная_папка> <выходной_файл>")
        sys.exit(1)
    
    source_directory = sys.argv[1]
    output_filename = sys.argv[2]
    
    if not os.path.isdir(source_directory):
        print(f"Ошибка: '{source_directory}' не является папкой")
        sys.exit(1)
    
    combine_files(source_directory, output_filename)
    print(f"\nВсе файлы объединены в: {output_filename}")