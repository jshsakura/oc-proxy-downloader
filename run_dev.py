
import subprocess
import os
import sys
import time
import signal
import platform
import atexit
import threading
import queue

# psutil이 없으면 자동 설치
try:
    import psutil
except ImportError:
    subprocess.check_call([sys.executable, '-m', 'pip', 'install', 'psutil'])
    import psutil

# 전역 프로세스 리스트
backend_process = None
frontend_process = None
shutdown_requested = False

def kill_process_tree(pid):
    try:
        if not psutil.pid_exists(pid):
            print(f"Process {pid} already dead")
            return
        
        parent = psutil.Process(pid)
        children = parent.children(recursive=True)
        
        # 먼저 자식 프로세스들을 정리
        for child in children:
            try:
                print(f"Terminating child process {child.pid}")
                child.terminate()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        
        # 자식들이 종료될 시간을 준다
        gone, alive = psutil.wait_procs(children, timeout=3)
        
        # 여전히 살아있는 프로세스들은 강제 종료
        for proc in alive:
            try:
                print(f"Force killing child process {proc.pid}")
                proc.kill()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        
        # 부모 프로세스 정리
        try:
            print(f"Terminating parent process {parent.pid}")
            parent.terminate()
            parent.wait(timeout=3)
        except psutil.TimeoutExpired:
            print(f"Force killing parent process {parent.pid}")
            parent.kill()
            
    except (psutil.NoSuchProcess, psutil.AccessDenied) as e:
        print(f"Process {pid} access error: {e}")
    except Exception as e:
        print(f"Error killing process tree: {e}")

def signal_handler(signum, frame):
    """시그널 핸들러"""
    global shutdown_requested
    print(f"\n--- Signal {signum} received, initiating shutdown ---")
    shutdown_requested = True
    cleanup_and_exit()

def read_backend_output(stream, prefix):
    """백엔드 출력을 읽어서 프린트하는 함수"""
    try:
        while True:
            try:
                line = stream.readline()
                if not line:  # EOF
                    break
                # 모든 줄을 출력 (빈 줄 포함)
                try:
                    clean_line = line.rstrip()
                    if clean_line or line.strip():  # 빈 줄이 아니거나 공백만 있는 줄
                        print(f"{prefix} {clean_line}", flush=True)
                except UnicodeEncodeError:
                    # 인코딩 문제가 있는 경우 UTF-8로 강제 변환
                    try:
                        clean_line = line.rstrip().encode('utf-8', 'replace').decode('utf-8')
                        print(f"{prefix} {clean_line}", flush=True)
                    except:
                        print(f"{prefix} [인코딩 오류가 있는 출력]", flush=True)
            except UnicodeDecodeError as e:
                print(f"[ENCODING-ERROR] {prefix} {e}", flush=True)
                continue
            except Exception as e:
                print(f"[ERROR] Reading {prefix}: {e}", flush=True)
                break
    except Exception as e:
        print(f"[ERROR] {prefix} stream reader error: {e}", flush=True)
    finally:
        print(f"{prefix} Stream ended", flush=True)

def cleanup_and_exit():
    """정리 작업 후 종료"""
    global backend_process, frontend_process, shutdown_requested
    
    if shutdown_requested:
        return
    shutdown_requested = True
    
    print("--- Cleaning up processes ---")
    
    # 백엔드 프로세스 종료
    if backend_process and backend_process.poll() is None:
        print("Shutting down backend server...")
        try:
            # 먼저 정상 종료 신호 보내기
            backend_process.terminate()
            backend_process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            print("Backend didn't terminate gracefully, force killing...")
            kill_process_tree(backend_process.pid)
        except Exception as e:
            print(f"Error terminating backend: {e}")
            kill_process_tree(backend_process.pid)
        
    # 프론트엔드 프로세스 종료
    if frontend_process and frontend_process.poll() is None:
        print("Shutting down frontend server...")
        try:
            frontend_process.terminate()
            frontend_process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            print("Frontend didn't terminate gracefully, force killing...")
            kill_process_tree(frontend_process.pid)
        except Exception as e:
            print(f"Error terminating frontend: {e}")
            kill_process_tree(frontend_process.pid)
    
    # 포트 8000과 3000을 사용하는 모든 프로세스 강제 종료
    try:
        import psutil
        for proc in psutil.process_iter(['pid', 'name', 'connections']):
            try:
                for conn in proc.info['connections'] or []:
                    if conn.laddr.port in [8000, 3000]:
                        print(f"Force killing process {proc.info['pid']} ({proc.info['name']}) using port {conn.laddr.port}")
                        psutil.Process(proc.info['pid']).kill()
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                pass
    except Exception as e:
        print(f"Error killing port processes: {e}")
    
    print("All processes cleaned up. Exiting.")
    sys.exit(0)

def main():
    global backend_process, frontend_process
    
    # 시그널 핸들러 등록
    signal.signal(signal.SIGINT, signal_handler)  # Ctrl+C
    if hasattr(signal, 'SIGTERM'):
        signal.signal(signal.SIGTERM, signal_handler)  # 종료 시그널
    
    # atexit 핸들러 등록 (프로그램 종료 시 정리)
    atexit.register(cleanup_and_exit)
    
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
    
    # Python 버퍼링 비활성화 및 UTF-8 인코딩 환경 변수 설정
    backend_env = os.environ.copy()
    backend_env["PYTHONUNBUFFERED"] = "1"
    backend_env["PYTHONIOENCODING"] = "utf-8"
    backend_env["PYTHONUTF8"] = "1"  # Python 3.7+ UTF-8 모드 강제 활성화
    backend_env["LC_ALL"] = "C.UTF-8"
    backend_env["LANG"] = "C.UTF-8"
    
    backend_command = [
        sys.executable,
        "-u",  # unbuffered 옵션 추가
        "-m", "uvicorn",
        "main:app",
        "--host", "0.0.0.0",
        "--port", "8000",
        "--log-level", "debug",  # debug로 변경하여 더 자세한 로그 출력
        "--access-log"  # 액세스 로그도 활성화
    ]
    is_windows = platform.system() == "Windows"
    if is_windows:
        backend_process = subprocess.Popen(
            backend_command, cwd=backend_dir,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,  # stderr를 별도로 캡처
            text=True,
            bufsize=0,  # 완전 무버퍼링
            encoding='utf-8',  # 명시적 UTF-8 인코딩
            errors='replace',  # 인코딩 오류 시 대체 문자 사용
            env=backend_env
        )
    else:
        backend_process = subprocess.Popen(
            backend_command, cwd=backend_dir,
            start_new_session=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,  # stderr를 별도로 캡처
            text=True,
            bufsize=0,  # 완전 무버퍼링
            encoding='utf-8',  # 명시적 UTF-8 인코딩
            errors='replace',  # 인코딩 오류 시 대체 문자 사용
            env=backend_env
        )
    print(f"Backend server started with PID: {backend_process.pid}")

    # 백엔드 출력을 읽는 스레드 시작 (stdout과 stderr 모두)
    backend_stdout_thread = threading.Thread(target=read_backend_output, args=(backend_process.stdout, "[BACKEND-OUT]"), daemon=True)
    backend_stderr_thread = threading.Thread(target=read_backend_output, args=(backend_process.stderr, "[BACKEND-ERR]"), daemon=True)
    backend_stdout_thread.start()
    backend_stderr_thread.start()
    
    print("--- Backend log readers started ---")
    print("--- Waiting for backend to initialize ---")
    time.sleep(3)  # 더 오래 대기
    
    # 백엔드가 정상적으로 시작되었는지 테스트
    try:
        import requests
        test_response = requests.get("http://localhost:8000/docs", timeout=5)
        if test_response.status_code == 200:
            print("[OK] Backend server is responding")
        else:
            print(f"[WARN] Backend server responded with status: {test_response.status_code}")
    except Exception as e:
        print(f"[ERROR] Backend server test failed: {e}")

    time.sleep(1)

    # --- Start Frontend Dev Server ---
    print("\n--- Starting Frontend Dev Server ---")
    if is_windows:
        frontend_command = ["cmd", "/c", "npm", "run", "dev", "--", "--port", "3000", "--host", "0.0.0.0"]
        frontend_process = subprocess.Popen(
            frontend_command, cwd=frontend_dir,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
            stdout=subprocess.DEVNULL,  # 프론트엔드 로그 숨김
            stderr=subprocess.DEVNULL   # 프론트엔드 에러 로그도 숨김
        )
    else:
        frontend_command = ["npm", "run", "dev", "--", "--port", "3000", "--host", "0.0.0.0"]
        frontend_process = subprocess.Popen(
            frontend_command, cwd=frontend_dir,
            start_new_session=True,
            stdout=subprocess.DEVNULL,  # 프론트엔드 로그 숨김
            stderr=subprocess.DEVNULL   # 프론트엔드 에러 로그도 숨김
        )
    print(f"Frontend server started with PID: {frontend_process.pid}")

    print("\nBoth servers are running. Press Ctrl+C to stop.")
    
    try:
        while not shutdown_requested:
            # 프로세스가 죽었는지 확인
            if backend_process.poll() is not None:
                print("[ERROR] Backend process died unexpectedly")
                print(f"Backend exit code: {backend_process.returncode}")
                break
            if frontend_process.poll() is not None:
                print("[ERROR] Frontend process died unexpectedly")
                print(f"Frontend exit code: {frontend_process.returncode}")
                break
            
            time.sleep(1)
            
    except KeyboardInterrupt:
        # 이미 signal_handler에서 처리되지만, 혹시 모를 경우를 대비
        print("\n--- KeyboardInterrupt caught in main loop ---")
        cleanup_and_exit()
    except Exception as e:
        print(f"\n--- Unexpected error in main loop: {e} ---")
        cleanup_and_exit()
    
    # 정상 종료 시에도 정리
    cleanup_and_exit()

if __name__ == "__main__":
    main()
