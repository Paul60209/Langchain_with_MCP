# import os
# import time
import signal
import sys
import subprocess

# Register process termination handler
def signal_handler(sig, frame):
    print("\nTermination signal received, shutting down client...")
    sys.exit(0)

if __name__ == "__main__":
    # Register signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    try:
        print("\n===== Starting MCP Client =====")
        
        print("Starting client...\n")
        
        # Use subprocess to execute chainlit command directly instead of Python API
        subprocess.run(["chainlit", "run", "app.py"])
        
    except KeyboardInterrupt:
        print("\nKeyboard interrupt received, shutting down client...")
    except Exception as e:
        print(f"\nAn error occurred: {e}")
    finally:
        print("Client has been shut down, MCP servers are still running") 