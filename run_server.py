import os
import subprocess
import time
import signal
import threading
import sys
import socket
import psutil

# MCP Server Configurations
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

# Store server processes
server_processes = {}
# Store server output logs
server_logs = {}
# Flag indicating if servers are being stopped
is_stopping = False

def read_process_output(process, name, output_type):
    """Read process output (stdout or stderr) and save to logs."""
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

def check_and_kill_process_on_port(port):
    """Check if the specified port is occupied, and if so, attempt to terminate the occupying process."""
    try:
        # Create a socket to try binding the port
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(1)
        result = sock.connect_ex(('127.0.0.1', port))
        sock.close()
        
        # If the port is available (connection failed), return
        if result != 0:
            print(f"Port {port} is available.")
            return True
        
        print(f"Port {port} is occupied, attempting to terminate the occupying process...")
        
        # Find the process occupying the port
        for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
            try:
                for conn in proc.connections(kind='inet'):
                    if conn.laddr.port == port:
                        print(f"Found process occupying port {port}: PID={proc.pid}, Name={proc.name()}")
                        
                        # Terminate the process
                        proc.terminate()
                        print(f"Sent termination signal to process {proc.pid}")
                        
                        # Wait for the process to terminate (max 5 seconds)
                        proc.wait(5)
                        print(f"Process {proc.pid} has terminated")
                        
                        # Check again if the port is available
                        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                        sock.settimeout(1)
                        result = sock.connect_ex(('127.0.0.1', port))
                        sock.close()
                        
                        if result != 0:
                            print(f"Port {port} is now available.")
                            return True
                        else:
                            print(f"Port {port} is still occupied, attempting to force kill the process...")
                            proc.kill()  # Force kill
                            time.sleep(1)  # Wait for the OS to release the port
                            return check_and_kill_process_on_port(port)  # Recursive check
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                pass
        
        # If no specific process found but port is still occupied
        print(f"Could not find the specific process occupying port {port}.")
        return False
    
    except Exception as e:
        print(f"Error checking port {port}: {e}")
        return False

def ensure_ports_available():
    """Ensure all configured ports are available."""
    print("\n===== Checking and ensuring all ports are available =====\n")
    
    for name, config in SERVER_CONFIGS.items():
        port = config["port"]
        print(f"Checking port {port} for {name} server...")
        if check_and_kill_process_on_port(port):
            print(f"Port {port} for {name} server is ready.")
        else:
            print(f"Warning: Could not free up port {port} for {name} server.")

def start_server(name, config):
    """Start an MCP server and return the process."""
    # Use the port specified in the config
    cmd = ["python", config["path"], "--port", str(config["port"])]
    print(f"Starting server: {name} - {' '.join(cmd)}")
    
    # Start the process
    process = subprocess.Popen(
        cmd, 
        stdout=subprocess.PIPE, 
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1
    )
    
    # Start threads to read output
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
    
    # Wait a bit and check if the process started successfully
    time.sleep(2)
    if process.poll() is not None:
        # Process terminated, something went wrong
        print(f"Server {name} failed to start on port {config['port']}")
        return None
    
    print(f"Server {name} started successfully on port {config['port']}")
    return process

def stop_server(name):
    """Stop the specified MCP server."""
    process = server_processes.get(name)
    stopped_process = None
    if process and process.poll() is None:  # Process is still running
        print(f"Stopping server: {name}")
        stopped_process = process
        try:
            process.terminate()  # Send SIGTERM
            for _ in range(50):  # Wait up to 5 seconds
                if process.poll() is not None:
                    break
                time.sleep(0.1)
            else:
                print(f"Force stopping server: {name}")
                process.kill()  # Send SIGKILL
        except Exception as e:
            print(f"Error stopping server {name}: {e}")
        finally:
            if name in server_processes:
                del server_processes[name]
    return stopped_process

def stop_all_servers():
    """Stop all running MCP servers."""
    global is_stopping
    is_stopping = True

    print("\nAttempting to stop all servers...")
    processes_to_wait = []
    for name in list(server_processes.keys()):
        process = stop_server(name)
        if process:
            processes_to_wait.append((name, process))

    # Wait for all requested processes to terminate
    if processes_to_wait:
        print("Waiting for server processes to terminate completely...")
        for name, process in processes_to_wait:
            try:
                # Only wait if the process is still running
                if process.poll() is None:
                    process.wait(timeout=5)
                    print(f"Server {name} confirmed terminated.")
                else:
                    print(f"Server {name} was already stopped when checked.")
            except subprocess.TimeoutExpired:
                print(f"Warning: Server {name} did not terminate after timeout. Manual check might be needed.")
            except Exception as e:
                 print(f"Error waiting for server {name} to terminate: {e}")

    print("All server stopping procedures completed.")

def save_server_config():
    """Save the server configuration to a file."""
    config_file = "server_config.txt"
    with open(config_file, "w") as f:
        for name, config in SERVER_CONFIGS.items():
            # Only save successfully started servers
            if name in server_processes and server_processes[name] is not None and server_processes[name].poll() is None:
                f.write(f"{name}:{config['port']}:{config['transport']}\n")
    print(f"Server configuration saved to {config_file}")

def start_all_servers():
    """Start all MCP servers."""
    global is_stopping
    is_stopping = False
    
    print("\n===== Starting all MCP Servers =====\n")
    
    # Ensure previous servers are stopped
    for name in list(server_processes.keys()):
        stop_server(name)
    
    # Clear logs
    server_logs.clear()
    
    # Ensure all ports are available
    ensure_ports_available()
    
    # Start all servers
    for name, config in SERVER_CONFIGS.items():
        print(f"\n--- Starting {name} Server ---")
        server_processes[name] = start_server(name, config)
    
    # Check startup status
    failed_servers = []
    for name, process in server_processes.items():
        if process is None or process.poll() is not None:
            failed_servers.append(name)
    
    if failed_servers:
        print(f"\nWarning: The following servers failed to start: {', '.join(failed_servers)}")
    
    # Display status of started servers and ports
    print("\n===== MCP Server Status =====")
    for name, config in SERVER_CONFIGS.items():
        if name in server_processes and server_processes[name] is not None and server_processes[name].poll() is None:
            print(f"- {name}: Running (Port: {config['port']})")
        else:
            print(f"- {name}: Not running")
    
    # Save server configuration to file
    save_server_config()
    
    print("\nAll MCP servers have completed startup. Press Ctrl+C to stop all servers.")
    print("Client can connect using these servers and can be started or stopped without stopping the servers.")

# Signal handler function
def signal_handler(sig, frame):
    print(f"\nSignal {sig} received, shutting down all servers...")
    stop_all_servers()
    print("Servers have been stopped safely.")
    sys.exit(0)

if __name__ == "__main__":
    # Register signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    try:
        # Start all servers
        start_all_servers()

        # Keep main thread running indefinitely until signal
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        # This block might not be strictly necessary anymore if signals are handled,
        # but kept for robustness in case signal handler somehow fails.
        print("\nKeyboard interrupt received (fallback handling), shutting down all servers...")
        stop_all_servers()
        print("Servers have been stopped safely (fallback handling).")
    except Exception as e:
        print(f"\nUnhandled error in main process: {e}")
        stop_all_servers() # Attempt cleanup on other errors too 