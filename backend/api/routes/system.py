# -*- coding: utf-8 -*-
import time
import asyncio
import psutil
from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(prefix="/api", tags=["system"])
_PROCESS = psutil.Process()
# Prime both CPU counters so later interval=None calls return a delta (non-blocking)
# instead of needing a blocking sample window.
_PROCESS.cpu_percent(interval=None)
psutil.cpu_percent(interval=None)

# Stats are polled every few seconds by every open tab. Cache briefly so a burst
# of concurrent polls is served from one computation instead of recomputing each.
_STATS_TTL_SEC = 2.0
_stats_cache = {"ts": 0.0, "data": None}
_stats_lock = asyncio.Lock()


class ClientError(BaseModel):
    msg: str = ""
    src: str = ""
    line: int = 0
    col: int = 0
    stack: str = ""


@router.post("/log-error")
async def log_client_error(err: ClientError):
    with open("/tmp/client-errors.log", "a") as f:
        f.write(f"\n=== CLIENT ERROR ===\n")
        f.write(f"msg={err.msg}\n")
        f.write(f"src={err.src}:{err.line}:{err.col}\n")
        if err.stack:
            f.write(f"stack={err.stack}\n")
    return {"ok": True}


@router.get("/system/stats")
async def get_system_stats():
    # Serve from cache when fresh (coalesces bursts of concurrent polls).
    now = time.monotonic()
    if _stats_cache["data"] is not None and (now - _stats_cache["ts"]) < _STATS_TTL_SEC:
        return _stats_cache["data"]
    async with _stats_lock:
        now = time.monotonic()
        if _stats_cache["data"] is not None and (now - _stats_cache["ts"]) < _STATS_TTL_SEC:
            return _stats_cache["data"]
        data = _collect_system_stats()
        _stats_cache["data"] = data
        _stats_cache["ts"] = now
        return data


def _collect_system_stats():
    # interval=None → non-blocking (delta since the last call); NEVER use a
    # blocking interval here — this runs on the event loop and a 0.5s sample
    # froze every request. All other psutil calls below are fast syscalls.
    cpu_percent = psutil.cpu_percent(interval=None)
    cpu_count = psutil.cpu_count(logical=True)
    cpu_count_physical = psutil.cpu_count(logical=False)
    process_cpu_percent = _PROCESS.cpu_percent(interval=None)
    process_mem = _PROCESS.memory_info()

    mem = psutil.virtual_memory()
    disk = psutil.disk_usage("/")

    net = psutil.net_io_counters()

    load_avg_1, load_avg_5, load_avg_15 = psutil.getloadavg()

    uptime_seconds = int(time.time() - int(psutil.boot_time()))

    return {
        "cpu": {
            "percent": cpu_percent,
            "count_logical": cpu_count,
            "count_physical": cpu_count_physical,
            "load_avg_1": round(load_avg_1, 2),
            "load_avg_5": round(load_avg_5, 2),
            "load_avg_15": round(load_avg_15, 2),
        },
        "memory": {
            "total": mem.total,
            "used": mem.used,
            "available": mem.available,
            "percent": mem.percent,
        },
        "disk": {
            "total": disk.total,
            "used": disk.used,
            "free": disk.free,
            "percent": disk.percent,
        },
        "network": {
            "bytes_sent": net.bytes_sent,
            "bytes_recv": net.bytes_recv,
            "packets_sent": net.packets_sent,
            "packets_recv": net.packets_recv,
        },
        "process": {
            "cpu_percent": process_cpu_percent,
            "rss": process_mem.rss,
        },
        "uptime": uptime_seconds,
    }
