#!/usr/bin/env python3
"""
Run Script - Check environment and start the MCP Chainlit application
"""
import subprocess
import time

def print_banner():
    print("""
===============================================
            MCP Application Launcher
===============================================
Please select the service to start:

1. Start MCP Servers only  (run_server.py)
2. Start Client only       (run_client.py)
3. Start Servers and Client (Both)
4. Exit

Servers will run in the background. Client can be started and stopped multiple times.
Closing the client does not stop the servers.
===============================================
""")

def run_server():
    """Start the MCP servers."""
    print("\nStarting MCP Servers...")
    subprocess.Popen(["python", "run_server.py"])
    print("MCP Servers started in the background.")

def run_client():
    """Start the client."""
    print("\nStarting Client...")
    subprocess.run(["python", "run_client.py"])

def main():
    """Main function."""
    print_banner()
    
    while True:
        try:
            choice = input("Enter your choice (1-4): ").strip()
            
            if choice == "1":
                run_server()
                break
            elif choice == "2":
                run_client()
                break
            elif choice == "3":
                run_server()
                # Give servers some time to start
                time.sleep(5)
                run_client()
                break
            elif choice == "4":
                print("Exiting program.")
                break
            else:
                print("Invalid choice, please enter again.")
        except KeyboardInterrupt:
            print("\nProgram interrupted.")
            break
        except Exception as e:
            print(f"An error occurred: {e}")
            break

if __name__ == "__main__":
    main() 