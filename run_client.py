import os
import time
import signal
import sys
import subprocess

# 註冊程序終止處理函數
def signal_handler(sig, frame):
    print("\n接收到終止信號，正在關閉客戶端...")
    sys.exit(0)

if __name__ == "__main__":
    # 註冊信號處理器
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    try:
        print("\n===== 啟動 MCP 客戶端 =====")
        print("請確保 MCP 伺服器已經運行（使用 run_server.py）")
        print("客戶端將連接到已經運行的伺服器，並且不會在退出時停止它們")
        print("啟動客戶端...\n")
        
        # 使用subprocess直接執行chainlit命令而不是使用Python API
        subprocess.run(["chainlit", "run", "app.py"])
        
    except KeyboardInterrupt:
        print("\n接收到鍵盤中斷，正在關閉客戶端...")
    except Exception as e:
        print(f"\n發生錯誤: {e}")
    finally:
        print("客戶端已關閉，MCP 伺服器仍在運行") 