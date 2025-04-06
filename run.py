#!/usr/bin/env python3
"""
運行腳本 - 檢查環境並啟動MCP Chainlit應用
"""
import subprocess
import time

def print_banner():
    print("""
===============================================
            MCP 應用啟動器
===============================================
請選擇要啟動的服務:

1. 僅啟動 MCP 伺服器  (run_server.py)
2. 僅啟動客戶端      (run_client.py)
3. 同時啟動伺服器和客戶端 (兩者)
4. 退出

伺服器會在後台運行，客戶端可以多次啟動和關閉。
關閉客戶端不會停止伺服器。
===============================================
""")

def run_server():
    """啟動 MCP 伺服器"""
    print("\n正在啟動 MCP 伺服器...")
    subprocess.Popen(["python", "run_server.py"])
    print("MCP 伺服器已在背景啟動")

def run_client():
    """啟動客戶端"""
    print("\n正在啟動客戶端...")
    subprocess.run(["python", "run_client.py"])

def main():
    """主函數"""
    print_banner()
    
    while True:
        try:
            choice = input("請輸入選擇 (1-4): ").strip()
            
            if choice == "1":
                run_server()
                break
            elif choice == "2":
                run_client()
                break
            elif choice == "3":
                run_server()
                # 給伺服器一些時間啟動
                time.sleep(5)
                run_client()
                break
            elif choice == "4":
                print("退出程序")
                break
            else:
                print("無效的選擇，請重新輸入")
        except KeyboardInterrupt:
            print("\n程序被中斷")
            break
        except Exception as e:
            print(f"發生錯誤: {e}")
            break

if __name__ == "__main__":
    main() 