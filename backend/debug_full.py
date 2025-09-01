
import sys, os
print("--- Starting Full Debug ---")

# --- Path Setup ---
backend_path = os.path.dirname(os.path.abspath(__file__))
if backend_path not in sys.path: sys.path.insert(0, backend_path)
project_root = os.path.dirname(backend_path)
if project_root not in sys.path: sys.path.insert(0, project_root)
print("Paths OK")

# --- Imports from main.py ---
try:
    import locale; print("Imported locale")
    import logging; print("Imported logging")
    import signal; print("Imported signal")
    import atexit; print("Imported atexit")
    from core.config import get_config, save_config, get_download_path; print("Imported core.config")
    from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request, Depends, BackgroundTasks, HTTPException, Body, APIRouter; print("Imported FastAPI")
    from contextlib import asynccontextmanager; print("Imported asynccontextmanager")
    from websockets.exceptions import ConnectionClosedError, ConnectionClosedOK; print("Imported websockets.exceptions")
    from fastapi.responses import FileResponse; print("Imported FileResponse")
    from fastapi.staticfiles import StaticFiles; print("Imported StaticFiles")
    from sqlalchemy.orm import Session; print("Imported Session")
    from pydantic import BaseModel, HttpUrl; print("Imported pydantic")
    from core.models import Base, DownloadRequest, StatusEnum, ProxyStatus; print("Imported core.models")
    from core.db import engine, get_db; print("Imported core.db")
    from core.common import convert_size; print("Imported core.common")
    from core.proxy_manager import get_unused_proxies, get_user_proxy_list, mark_proxy_used, reset_proxy_usage, test_proxy; print("Imported core.proxy_manager")
    import requests; print("Imported requests")
    import datetime; print("Imported datetime")
    import random; print("Imported random")
    import lxml.html; print("Imported lxml.html")
    import time; print("Imported time")
    import asyncio; print("Imported asyncio")
    from core.i18n import get_message, load_all_translations, get_translations; print("Imported core.i18n")
    from sqlalchemy import or_, desc, asc; print("Imported sqlalchemy functions")
    import queue; print("Imported queue")
    import cloudscraper; print("Imported cloudscraper")
    import re; print("Imported re")
    from urllib.parse import urlparse, unquote; print("Imported urllib.parse")
    from pathlib import Path; print("Imported pathlib")
    try:
        import tkinter as tk; print("Imported tkinter")
    except ImportError:
        print("tkinter not available")
    import threading; print("Imported threading")
    from concurrent.futures import ThreadPoolExecutor, Future; print("Imported concurrent.futures")
    import weakref; print("Imported weakref")
    import multiprocessing; print("Imported multiprocessing")
    from typing import Optional; print("Imported typing")
    from core.downloader import router as downloader_router; print("Imported downloader router")
    from core.proxy_stats import router as proxy_stats_router; print("Imported proxy_stats router")
    from core.shared import download_manager, status_queue; print("Imported core.shared")
    from logger import log_once; print("Imported logger")
    print("--- All Imports OK ---")

    # --- Global Scope Instantiations ---
    Base.metadata.create_all(bind=engine); print("Base.metadata.create_all OK")
    app = FastAPI(); print("FastAPI app created")
    print("--- Global Scope OK ---")

except Exception as e:
    print(f"AN ERROR OCCURRED: {e}")
    import traceback
    traceback.print_exc()

print("--- Full Debug Finished ---")
