import os
import subprocess
import time
import signal
import threading
import sys
import socket
import psutil
from mcp_server_config import SERVER_CONFIGS # Import shared config

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
        # Use a context manager for the socket
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(1)
            result = sock.connect_ex(('127.0.0.1', port))
            # No need to explicitly close with context manager
        
        # If the port is available (connection failed), return
        if result != 0:
            # print(f"Port {port} is available.") # Reduce verbosity
            return True
        
        print(f"Port {port} is occupied, attempting to terminate the occupying process...")
        
        # Find the process occupying the port using net_connections
        process_found = False
        for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
            try:
                # Use net_connections instead of connections
                for conn in proc.net_connections(kind='inet'):
                    if conn.laddr.port == port:
                        process_found = True
                        print(f"Found process occupying port {port}: PID={proc.pid}, Name={proc.name()}")
                        
                        # Terminate the process
                        print(f"Sending termination signal (SIGTERM) to process {proc.pid}")
                        proc.terminate()
                        
                        # Wait for the process to terminate (max 5 seconds)
                        try:
                            proc.wait(5)
                            print(f"Process {proc.pid} terminated successfully after SIGTERM.")
                        except psutil.TimeoutExpired:
                            print(f"Process {proc.pid} did not terminate after SIGTERM, attempting SIGKILL...")
                            proc.kill()  # Force kill
                            # Remove the wait after kill as it might timeout unnecessarily
                            # proc.wait(1) # Wait briefly for OS to process kill
                            print(f"Process {proc.pid} sent SIGKILL signal.")
                        
                        # Brief pause to allow OS to potentially release the port after kill
                        time.sleep(0.5)

                        # Check again if the port is available
                        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock_check:
                            sock_check.settimeout(1)
                            result_check = sock_check.connect_ex(('127.0.0.1', port))
                        
                        if result_check != 0:
                            print(f"Port {port} is now available.")
                            return True
                        else:
                            print(f"Warning: Port {port} still occupied after attempting termination.")
                            return False # Port is still occupied
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue # Ignore processes we can't access or that died
            except Exception as e:
                # Log other potential errors during iteration
                print(f"Error checking connections for process {proc.pid}: {e}")
                continue

        # If loop completes and process was found but port still occupied (or never found but occupied)
        if process_found:
             print(f"Could not free up port {port} although process was targeted.")
        else:
            print(f"Port {port} is occupied, but could not find the specific process.")
        return False # Port remains occupied
    
    except Exception as e:
        print(f"Error during check_and_kill_process_on_port for port {port}: {e}")
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
    port = config["port"]
    
    # Final check before starting
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.5) # Quick check
            if sock.connect_ex(('127.0.0.1', port)) == 0:
                print(f"Error starting {name}: Port {port} is still occupied just before launch.")
                return None
    except Exception as e:
         print(f"Error during final port check for {name} on port {port}: {e}")
         return None

    # Use the port specified in the config
    cmd = ["python", config["path"], "--port", str(port)]
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