
import subprocess
import os
import sys
import time

def main():
    # Get the project root directory
    project_root = os.path.dirname(os.path.abspath(__file__))
    backend_dir = os.path.join(project_root, 'backend')
    frontend_dir = os.path.join(project_root, 'frontend')

    # --- Start Backend Server ---
    print("--- Starting Backend Server ---")
    backend_command = [
        sys.executable,  # Use the current python interpreter
        "-m", "uvicorn",
        "main:app",
        "--reload",
        "--host", "0.0.0.0",
        "--port", "8000"
    ]
    # Use Popen to run the backend process in the background
    backend_process = subprocess.Popen(backend_command, cwd=backend_dir)
    print(f"Backend server started with PID: {backend_process.pid}")

    # A small delay to let the backend start before the frontend
    time.sleep(2)

    # --- Start Frontend Dev Server ---
    print("\n--- Starting Frontend Dev Server ---")
    # Use shell=True on Windows to correctly handle npm commands
    # For Vite, pass arguments after '--'
    frontend_command = "npm run dev -- --port 3000"
    # Use Popen to run the frontend process in the background
    frontend_process = subprocess.Popen(frontend_command, cwd=frontend_dir, shell=True)
    print(f"Frontend server started with PID: {frontend_process.pid}")

    # --- Wait for processes to exit ---
    print("\nBoth servers are running. Press Ctrl+C to stop.")
    try:
        # Wait for either process to exit
        while backend_process.poll() is None and frontend_process.poll() is None:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n--- Shutting down servers ---")
        # Terminate both processes gracefully
        backend_process.terminate()
        frontend_process.terminate()
        print("Servers have been shut down.")
    except Exception as e:
        print(f"An error occurred: {e}")
        backend_process.terminate()
        frontend_process.terminate()
    finally:
        # Ensure processes are killed if they are still running
        if backend_process.poll() is None:
            backend_process.kill()
        if frontend_process.poll() is None:
            frontend_process.kill()

if __name__ == "__main__":
    main()
