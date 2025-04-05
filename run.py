#!/usr/bin/env python3
"""
運行腳本 - 檢查環境並啟動MCP Chainlit應用
"""
import os
import sys
import subprocess
import signal
import asyncio
import time
import chainlit as cl

def check_environment():
    """檢查環境是否滿足運行需求"""
    # 檢查Python版本
    required_python = (3, 8)
    current_python = sys.version_info
    
    if current_python < required_python:
        print(f"錯誤: 需要Python {required_python[0]}.{required_python[1]} 或更高版本")
        return False
    
    # 檢查.env文件
    if not os.path.exists('.env'):
        print("警告: 未找到.env文件，將使用默認配置")
        
    # 檢查MCP_Servers目錄
    if not os.path.exists('MCP_Servers'):
        print("錯誤: 未找到MCP_Servers目錄")
        return False
        
    server_files = [f for f in os.listdir('MCP_Servers') if f.endswith('.py')]
    if not server_files:
        print("錯誤: MCP_Servers目錄中未找到任何Python文件")
        return False
        
    # 檢查依賴項
    try:
        import chainlit
        import langchain
        import langchain_openai
        import mcp
        import langchain_mcp_adapters
    except ImportError as e:
        print(f"錯誤: 缺少依賴項: {e}")
        print("請運行 'pip install -r requirements.txt' 安裝所有依賴項")
        return False
        
    # 檢查應用程序文件
    if not os.path.exists('app.py'):
        print("錯誤: 未找到app.py文件")
        return False
        
    return True

def run_app():
    """運行Chainlit應用"""
    print("正在啟動應用...")
    
    # 使用 subprocess 運行應用，這樣我們可以捕捉到 KeyboardInterrupt
    process = subprocess.Popen(["chainlit", "run", "app.py"])
    
    try:
        # 等待進程完成
        process.wait()
    except KeyboardInterrupt:
        # 發送中斷信號
        print("\n接收到中斷信號，正在關閉應用...")
        process.send_signal(signal.SIGINT)
        # 給應用一些時間關閉
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            # 如果應用沒有及時關閉，則強制關閉
            print("應用沒有及時關閉，強制終止...")
            process.kill()
    
    return process.returncode == 0

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