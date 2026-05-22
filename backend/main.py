# -*- coding: utf-8 -*-
"""
OC Proxy Downloader - new architecture
- WebSockets fully removed
- Based on SSE + asyncio
- Modular structure
"""
import sys
import os

# Standalone environment setup (highest priority - before all imports!)
if getattr(sys, 'frozen', False):
    from pathlib import Path
    # Create a config folder in the same directory as the executable
    exe_dir = Path(sys.executable).parent
    config_dir = exe_dir / "config"
    config_dir.mkdir(exist_ok=True)
    os.environ['OC_CONFIG_DIR'] = str(config_dir)
    print(f"Loading OC Proxy Downloader...")
    print(f"[LOG] Standalone config directory: {config_dir}")

# Python path setup (for the Docker environment)
# This code must run before the other modules.
backend_path = os.path.dirname(os.path.abspath(__file__))
if backend_path not in sys.path:
    sys.path.insert(0, backend_path)

import signal
import traceback
import threading
import time
import uvicorn
import atexit
import httpx
import json
import webbrowser
import asyncio
from pathlib import Path
from dotenv import load_dotenv
from utils.logging import setup_logging, replace_print
from core.app_factory import create_app

# Load the .env file
if getattr(sys, 'frozen', False):
    # Standalone: look in the exe directory
    env_path = Path(sys.executable).parent / ".env"
else:
    # Development: look in the root directory
    project_root = Path(__file__).parent.parent
    env_path = project_root / ".env"

if env_path.exists():
    load_dotenv(env_path)
    print(f"[LOG] Loaded .env from: {env_path}")
else:
    print("[INFO] No .env file found")

# Logging setup (after loading .env)
setup_logging()
replace_print()

# Show a loading indicator in the standalone environment
def show_loading():
    """Display loading animation"""
    if not getattr(sys, 'frozen', False):
        return  # Skip in development environment

    import threading
    import time

    loading_chars = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
    stop_loading = threading.Event()

    def loading_animation():
        i = 0
        while not stop_loading.is_set():
            char = loading_chars[i % len(loading_chars)]
            print(f"\r{char} Starting OC Proxy Downloader...", end="", flush=True)
            time.sleep(0.1)
            i += 1

    thread = threading.Thread(target=loading_animation, daemon=True)
    thread.start()
    return stop_loading

# Start loading
loading_stop = show_loading()

# Create the main application (after loading .env)
app = create_app()

# Loading complete
if loading_stop:
    loading_stop.set()
    print("\r✅ OC Proxy Downloader Ready!          ")  # Clear previous text with spaces


def monitor_process_health():
    """Basic process health check - simplified"""
    try:
        # Check only basic status
        return True
    except Exception as e:
        print(f"[LOG] Process monitoring error (ignored): {e}")
        return True


def force_cleanup_threads():
    """Force-clean up all threads - prevents reentrant calls"""
    try:
        print("[LOG] Starting thread cleanup...")

        # A short wait to give a chance for normal shutdown
        time.sleep(0.2)

        # Check the current threads
        active_threads = threading.enumerate()

        # Thread types to clean up
        cleanup_threads = []
        for t in active_threads:
            if (('AnyIO worker thread' in t.name) or
                ('Download' in t.name) or
                ('ThreadPoolExecutor' in str(type(t))) or
                ('_thread' in str(type(t)).lower())) and not t.daemon:
                cleanup_threads.append(t)

        if cleanup_threads:
            print(f"[LOG] Found {len(cleanup_threads)} threads to cleanup")

            # Attempt a forced shutdown (switch to daemon)
            for thread in cleanup_threads:
                try:
                    thread.daemon = True
                    print(f"[LOG] Set daemon=True for {thread.name}")
                except:
                    pass

        print("[LOG] Thread cleanup completed")
    except:
        # Silently ignore on exception (prevents reentrant calls)
        pass


def main():
    """Main server start function"""
    print("=" * 60)
    print("🚀 OC Proxy Downloader v2.0")
    print("   - SSE + asyncio ✅")
    print("=" * 60)

    # Register thread cleanup on exit (prevents multiple registrations)
    atexit.register(force_cleanup_threads)

    # Set up the forced-shutdown handler
    def signal_handler(sig, frame):
        print(f"\n[LOG] 종료 신호 수신 ({sig}) - 즉시 강제 종료...")
        try:
            # Quick cleanup
            sys.exit(0)
        except:
            os._exit(0)  # force exit

    signal.signal(signal.SIGINT, signal_handler)  # Ctrl+C
    signal.signal(signal.SIGTERM, signal_handler)  # shutdown request

    # Also handle Ctrl+Break on Windows
    if hasattr(signal, 'SIGBREAK'):
        signal.signal(signal.SIGBREAK, signal_handler)

    try:
        # Run the dev server - fast-shutdown configuration
        # Per-environment port configuration
        port = int(os.environ.get('OC_PORT', '8888' if getattr(sys, 'frozen', False) else '8000'))

        config = uvicorn.Config(
            app,  # pass the app object directly in the PyInstaller environment
            host="0.0.0.0",
            port=port,
            reload=False,
            log_level="critical",
            loop="asyncio",
            workers=1,
            access_log=False,
            lifespan="on",  # fast startup/shutdown
            timeout_keep_alive=5,  # shorten the connection timeout
            timeout_graceful_shutdown=3,  # shorten the shutdown timeout
        )
        server = uvicorn.Server(config)

        # Additional loading message for standalone only
        if getattr(sys, 'frozen', False):
            print("🌐 Starting web server...")
        else:
            print("[LOG] Starting server - default configuration")

        # Auto-open the browser (only in non-Docker environments)
        if not os.getenv('DOCKER_CONTAINER'):
            def open_browser():
                """Open browser after server starts"""
                time.sleep(2)  # Wait for server start
                try:
                    url = f"http://localhost:{port}"
                    print(f"[LOG] Opening browser: {url}")
                    webbrowser.open(url)
                except Exception as e:
                    print(f"[WARNING] Failed to open browser: {e}")
                    print(f"[INFO] Please manually access http://localhost:{port} in your browser")

            # Open the browser in a separate thread
            browser_thread = threading.Thread(target=open_browser, daemon=True)
            browser_thread.start()
        else:
            print("[INFO] Docker/Standalone environment - Browser auto-open disabled")

        server.run()
    except KeyboardInterrupt:
        print("[LOG] KeyboardInterrupt - Normal shutdown")
    except Exception as fatal_error:
        print(f"[FATAL] Fatal error occurred: {fatal_error}")
        print(f"[FATAL] Please restart the server")
        traceback.print_exc()
    finally:
        force_cleanup_threads()


if __name__ == "__main__":
    main()
