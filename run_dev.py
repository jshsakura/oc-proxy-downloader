
import subprocess
import os
import sys
import time
import signal
import platform

# psutil이 없으면 자동 설치
try:
    import psutil
except ImportError:
    subprocess.check_call([sys.executable, '-m', 'pip', 'install', 'psutil'])
    import psutil

def kill_process_tree(pid):
    try:
        parent = psutil.Process(pid)
        children = parent.children(recursive=True)
        for child in children:
            print(f"Killing child process {child.pid}")
            child.kill()
        parent.kill()
    except Exception as e:
        print(f"Error killing process tree: {e}")

def main():
    project_root = os.path.dirname(os.path.abspath(__file__))
    backend_dir = os.path.join(project_root, 'backend')
    frontend_dir = os.path.join(project_root, 'frontend')
    dist_dir = os.path.join(frontend_dir, 'dist')

    # --- Build Frontend if dist does not exist ---
    if not os.path.exists(dist_dir):
        print("--- Building Frontend (dist not found) ---")
        subprocess.check_call("npm install", cwd=frontend_dir, shell=True)
        subprocess.check_call("npm run build", cwd=frontend_dir, shell=True)
        print("--- Frontend build complete ---")
    else:
        print("--- dist folder exists, skipping build ---")

    # --- Start Backend Server FIRST ---
    print("--- Starting Backend Server ---")
    backend_command = [
        sys.executable,
        "-m", "uvicorn",
        "main:app",
        "--reload",
        "--host", "0.0.0.0",
        "--port", "8000"
    ]
    is_windows = platform.system() == "Windows"
    if is_windows:
        backend_process = subprocess.Popen(
            backend_command, cwd=backend_dir,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP
        )
    else:
        backend_process = subprocess.Popen(
            backend_command, cwd=backend_dir,
            start_new_session=True
        )
    print(f"Backend server started with PID: {backend_process.pid}")

    time.sleep(2)

    # --- Start Frontend Dev Server ---
    print("\n--- Starting Frontend Dev Server ---")
    frontend_command = "npm run dev -- --port 3000"
    if is_windows:
        frontend_process = subprocess.Popen(
            frontend_command, cwd=frontend_dir, shell=True,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP
        )
    else:
        frontend_process = subprocess.Popen(
            frontend_command, cwd=frontend_dir, shell=True,
            start_new_session=True
        )
    print(f"Frontend server started with PID: {frontend_process.pid}")

    print("\nBoth servers are running. Press Ctrl+C to stop.")
    try:
        while backend_process.poll() is None and frontend_process.poll() is None:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n--- Shutting down servers (entire process tree) ---")
        kill_process_tree(backend_process.pid)
        kill_process_tree(frontend_process.pid)
        print("Servers have been shut down.")
    finally:
        # Extra kill as fallback
        if backend_process.poll() is None:
            backend_process.kill()
        if frontend_process.poll() is None:
            frontend_process.kill()

if __name__ == "__main__":
    main()
