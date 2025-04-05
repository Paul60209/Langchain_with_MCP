import base64

def get_file_as_base64(file_path):
    with open(file_path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")
        
# 使用方法
file_path = "/Users/dailiwei/Downloads/test_1_pg.pptx"
base64_content = get_file_as_base64(file_path)
print(base64_content)