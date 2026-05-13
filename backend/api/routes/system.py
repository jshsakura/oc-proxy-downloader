# -*- coding: utf-8 -*-
import time
import psutil
from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(prefix="/api", tags=["system"])


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
    cpu_percent = psutil.cpu_percent(interval=0.5)
    cpu_count = psutil.cpu_count(logical=True)
    cpu_count_physical = psutil.cpu_count(logical=False)

    mem = psutil.virtual_memory()
    disk = psutil.disk_usage("/")

    net = psutil.net_io_counters()

    load_avg_1, load_avg_5, load_avg_15 = psutil.getloadavg()

    uptime_seconds = int(psutil.boot_time())
    import time
    uptime_seconds = int(time.time() - uptime_seconds)

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
        "uptime": uptime_seconds,
    }
