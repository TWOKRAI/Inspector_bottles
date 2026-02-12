import os
os.environ['TF_ENABLE_ONEDNN_OPTS'] = '1'
print("ONEDNN activated:", os.environ.get('TF_ENABLE_ONEDNN_OPTS', '0') == '1')  # Должно быть True