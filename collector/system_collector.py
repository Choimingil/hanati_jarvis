from __future__ import annotations

import os
import platform
import socket
from typing import Any

import psutil

from utils.time_utils import now_iso


class SystemCollector:
    """Collect a bounded snapshot of host, process, and network state."""

    def __init__(self, process_limit: int = 20) -> None:
        self.process_limit = max(0, process_limit)

    @staticmethod
    def _processes() -> list[dict[str, Any]]:
        processes: list[dict[str, Any]] = []
        attrs = [
            "pid", "ppid", "name", "status", "cpu_percent",
            "memory_percent", "memory_info", "num_threads",
            "create_time",
        ]
        for process in psutil.process_iter(attrs=attrs, ad_value=None):
            info = process.info
            memory_info = info.get("memory_info")
            processes.append({
                "pid": info.get("pid"),
                "ppid": info.get("ppid"),
                "name": info.get("name"),
                "status": info.get("status"),
                "cpu_percent": info.get("cpu_percent") or 0.0,
                "memory_percent": round(
                    info.get("memory_percent") or 0.0, 2
                ),
                "memory_rss_bytes": (
                    memory_info.rss if memory_info else 0
                ),
                "thread_count": info.get("num_threads") or 0,
                "create_time": info.get("create_time"),
            })
        return processes

    @staticmethod
    def _connections() -> dict[str, Any]:
        by_status: dict[str, int] = {}
        listening_ports: list[int] = []
        access_denied = False
        try:
            connections = psutil.net_connections(kind="inet")
        except (psutil.AccessDenied, PermissionError):
            connections = []
            access_denied = True

        for connection in connections:
            status = connection.status or "NONE"
            by_status[status] = by_status.get(status, 0) + 1
            if status == psutil.CONN_LISTEN and connection.laddr:
                listening_ports.append(connection.laddr.port)

        return {
            "total": len(connections),
            "by_status": by_status,
            "listening_ports": sorted(set(listening_ports)),
            "access_denied": access_denied,
        }

    def collect(self) -> dict[str, Any]:
        memory = psutil.virtual_memory()
        swap = psutil.swap_memory()
        disk = psutil.disk_usage(os.path.abspath(os.sep))
        disk_io = psutil.disk_io_counters()
        net_io = psutil.net_io_counters()
        processes = sorted(
            self._processes(),
            key=lambda item: (
                item["cpu_percent"], item["memory_rss_bytes"]
            ),
            reverse=True,
        )

        return {
            "timestamp": now_iso(),
            "host": {
                "hostname": socket.gethostname(),
                "os": platform.system(),
                "os_release": platform.release(),
                "boot_time": psutil.boot_time(),
            },
            "cpu": {
                "percent": psutil.cpu_percent(interval=None),
                "per_cpu_percent": psutil.cpu_percent(
                    interval=None, percpu=True
                ),
                "logical_count": psutil.cpu_count(),
                "physical_count": psutil.cpu_count(logical=False),
                "load_average": list(os.getloadavg())
                if hasattr(os, "getloadavg") else None,
            },
            "memory": {
                "total_bytes": memory.total,
                "available_bytes": memory.available,
                "used_bytes": memory.used,
                "percent": memory.percent,
                "swap_total_bytes": swap.total,
                "swap_used_bytes": swap.used,
                "swap_percent": swap.percent,
            },
            "disk": {
                "root": {
                    "total_bytes": disk.total,
                    "used_bytes": disk.used,
                    "free_bytes": disk.free,
                    "percent": disk.percent,
                },
                "io": {
                    "read_bytes": disk_io.read_bytes if disk_io else 0,
                    "write_bytes": disk_io.write_bytes if disk_io else 0,
                    "read_count": disk_io.read_count if disk_io else 0,
                    "write_count": disk_io.write_count if disk_io else 0,
                },
            },
            "network": {
                "bytes_sent": net_io.bytes_sent,
                "bytes_received": net_io.bytes_recv,
                "packets_sent": net_io.packets_sent,
                "packets_received": net_io.packets_recv,
                "errors_in": net_io.errin,
                "errors_out": net_io.errout,
                "drops_in": net_io.dropin,
                "drops_out": net_io.dropout,
                "connections": self._connections(),
            },
            "processes": {
                "total": len(processes),
                "returned": min(len(processes), self.process_limit),
                "items": processes[:self.process_limit],
            },
        }
