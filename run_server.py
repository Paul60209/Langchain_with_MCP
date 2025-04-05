import os
import asyncio
import subprocess
import time
import signal
import threading
import sys
import socket
import psutil

# MCP 伺服器配置
SERVER_CONFIGS = {
    "weather": {
        "path": os.path.join("MCP_Servers", "weather_server.py"),
        "port": 8001,
        "transport": "sse"
    },
    "sql_query": {
        "path": os.path.join("MCP_Servers", "sql_query_server.py"),
        "port": 8002,
        "transport": "sse"
    },
    "ppt_translator": {
        "path": os.path.join("MCP_Servers", "ppt_translator_server.py"),
        "port": 8003,
        "transport": "sse"
    }
}

# 存儲伺服器進程
server_processes = {}
# 存儲伺服器輸出日誌
server_logs = {}
# 是否正在停止伺服器
is_stopping = False

def read_process_output(process, name, output_type):
    """讀取進程的輸出（stdout 或 stderr）並保存到日誌中"""
    if output_type == "stdout":
        stream = process.stdout
    else:
        stream = process.stderr
    
    while True:
        if is_stopping:
            break
            
        line = stream.readline()
        if not line:
            break
        
        line_str = line.strip()
        if line_str:
            log_key = f"{name}_{output_type}"
            if log_key not in server_logs:
                server_logs[log_key] = []
            server_logs[log_key].append(line_str)
            print(f"[{name}] [{output_type}] {line_str}")

def check_and_kill_process_on_port(port):
    """檢查指定端口是否被佔用，如果被佔用則嘗試終止佔用該端口的進程"""
    try:
        # 創建一個socket來嘗試綁定端口
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(1)
        result = sock.connect_ex(('127.0.0.1', port))
        sock.close()
        
        # 如果端口可用（連接失敗），則返回
        if result != 0:
            print(f"端口 {port} 可用。")
            return True
        
        print(f"端口 {port} 被佔用，嘗試終止佔用進程...")
        
        # 查找佔用該端口的進程
        for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
            try:
                for conn in proc.connections(kind='inet'):
                    if conn.laddr.port == port:
                        print(f"發現佔用端口 {port} 的進程: PID={proc.pid}, 名稱={proc.name()}")
                        
                        # 終止進程
                        proc.terminate()
                        print(f"已發送終止信號到進程 {proc.pid}")
                        
                        # 等待進程終止（最多等待5秒）
                        proc.wait(5)
                        print(f"進程 {proc.pid} 已終止")
                        
                        # 再次檢查端口是否可用
                        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                        sock.settimeout(1)
                        result = sock.connect_ex(('127.0.0.1', port))
                        sock.close()
                        
                        if result != 0:
                            print(f"端口 {port} 現在可用。")
                            return True
                        else:
                            print(f"端口 {port} 仍然被佔用，嘗試強制終止進程...")
                            proc.kill()  # 強制終止
                            time.sleep(1)  # 等待操作系統釋放端口
                            return check_and_kill_process_on_port(port)  # 遞歸檢查
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                pass
        
        # 如果找不到具體進程但端口仍被佔用
        print(f"無法找到佔用端口 {port} 的具體進程。")
        return False
    
    except Exception as e:
        print(f"檢查端口 {port} 時出錯: {e}")
        return False

def ensure_ports_available():
    """確保所有配置的端口都可用"""
    print("\n===== 檢查並確保所有端口可用 =====\n")
    
    for name, config in SERVER_CONFIGS.items():
        port = config["port"]
        print(f"檢查 {name} 伺服器的端口 {port}...")
        if check_and_kill_process_on_port(port):
            print(f"{name} 伺服器的端口 {port} 已準備就緒。")
        else:
            print(f"警告: 無法釋放 {name} 伺服器的端口 {port}。")

def start_server(name, config):
    """啟動 MCP 伺服器並返回進程"""
    # 使用配置中指定的端口
    cmd = ["python", config["path"], "--port", str(config["port"])]
    print(f"啟動伺服器: {name} - {' '.join(cmd)}")
    
    # 啟動進程
    process = subprocess.Popen(
        cmd, 
        stdout=subprocess.PIPE, 
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1
    )
    
    # 啟動讀取輸出的線程
    stdout_thread = threading.Thread(
        target=read_process_output, 
        args=(process, name, "stdout"), 
        daemon=True
    )
    stderr_thread = threading.Thread(
        target=read_process_output, 
        args=(process, name, "stderr"), 
        daemon=True
    )
    stdout_thread.start()
    stderr_thread.start()
    
    # 等待一段時間，檢查進程是否成功啟動
    time.sleep(2)
    if process.poll() is not None:
        # 進程已終止，發生了某些錯誤
        print(f"伺服器 {name} 在端口 {config['port']} 啟動失敗")
        return None
    
    print(f"伺服器 {name} 已成功啟動在端口 {config['port']}")
    return process

def stop_server(name):
    """停止指定的 MCP 伺服器"""
    process = server_processes.get(name)
    if process and process.poll() is None:  # 進程仍在運行
        print(f"停止伺服器: {name}")
        try:
            process.terminate()  # 發送 SIGTERM
            for _ in range(50):  # 等待最多 5 秒
                if process.poll() is not None:
                    break
                time.sleep(0.1)
            else:
                print(f"強制終止伺服器: {name}")
                process.kill()  # 發送 SIGKILL
        except Exception as e:
            print(f"停止伺服器 {name} 時出錯: {e}")
        finally:
            if name in server_processes:
                del server_processes[name]

def stop_all_servers():
    """停止所有正在運行的 MCP 伺服器"""
    global is_stopping
    is_stopping = True
    
    for name in list(server_processes.keys()):
        stop_server(name)
    
    print("所有伺服器已停止")

def save_server_config():
    """將伺服器配置保存到文件"""
    config_file = "server_config.txt"
    with open(config_file, "w") as f:
        for name, config in SERVER_CONFIGS.items():
            # 只保存成功啟動的伺服器
            if name in server_processes and server_processes[name] is not None and server_processes[name].poll() is None:
                f.write(f"{name}:{config['port']}:{config['transport']}\n")
    print(f"伺服器配置已保存到 {config_file}")

def start_all_servers():
    """啟動所有 MCP 伺服器"""
    global is_stopping
    is_stopping = False
    
    print("\n===== 正在啟動所有 MCP 伺服器 =====\n")
    
    # 確保之前的伺服器都已停止
    for name in list(server_processes.keys()):
        stop_server(name)
    
    # 清空日誌
    server_logs.clear()
    
    # 確保所有端口可用
    ensure_ports_available()
    
    # 啟動所有伺服器
    for name, config in SERVER_CONFIGS.items():
        print(f"\n--- 啟動 {name} 伺服器 ---")
        server_processes[name] = start_server(name, config)
    
    # 檢查啟動狀態
    failed_servers = []
    for name, process in server_processes.items():
        if process is None or process.poll() is not None:
            failed_servers.append(name)
    
    if failed_servers:
        print(f"\n警告：以下伺服器未能成功啟動: {', '.join(failed_servers)}")
    
    # 顯示已啟動的伺服器和端口
    print("\n===== MCP 伺服器狀態 =====")
    for name, config in SERVER_CONFIGS.items():
        if name in server_processes and server_processes[name] is not None and server_processes[name].poll() is None:
            print(f"- {name}: 運行中 (端口: {config['port']})")
        else:
            print(f"- {name}: 未運行")
    
    # 保存伺服器配置到文件
    save_server_config()
    
    print("\n所有 MCP 伺服器已啟動完成。按 Ctrl+C 停止所有伺服器。")
    print("客戶端可以使用這些伺服器進行連接，並在不停止伺服器的情況下啟動或關閉。")

# 註冊程序終止處理函數
def signal_handler(sig, frame):
    print("\n接收到終止信號，正在關閉所有伺服器...")
    stop_all_servers()
    print("伺服器已安全停止。")
    sys.exit(0)

if __name__ == "__main__":
    # 註冊信號處理器
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    try:
        # 啟動所有伺服器
        start_all_servers()
        
        # 保持主線程運行
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n接收到鍵盤中斷，正在關閉所有伺服器...")
        stop_all_servers()
        print("伺服器已安全停止。")
    except Exception as e:
        print(f"發生錯誤: {e}")
        stop_all_servers() 