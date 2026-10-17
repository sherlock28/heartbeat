import asyncio
import time
from dataclasses import dataclass
from typing import Optional

from icmplib import ICMPLibError, async_ping


@dataclass
class CheckResult:
    ok: bool
    latency_ms: Optional[float] = None
    error: Optional[str] = None


async def check_icmp(host: str, timeout: float, privileged: bool = True) -> CheckResult:
    try:
        result = await async_ping(host, count=1, timeout=timeout, privileged=privileged)
    except ICMPLibError as exc:
        return CheckResult(False, error=f"ICMP: {exc.__class__.__name__}: {exc}")
    except OSError as exc:
        return CheckResult(False, error=f"ICMP: {exc}")
    if result.is_alive:
        return CheckResult(True, latency_ms=round(result.avg_rtt, 2))
    return CheckResult(False, error="Sin respuesta a ping")


async def check_tcp(host: str, port: int, timeout: float) -> CheckResult:
    start = time.perf_counter()
    try:
        _, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout=timeout)
    except asyncio.TimeoutError:
        return CheckResult(False, error=f"Timeout conectando a {host}:{port}")
    except OSError as exc:
        return CheckResult(False, error=f"TCP {host}:{port}: {exc.strerror or exc}")
    latency = (time.perf_counter() - start) * 1000
    writer.close()
    try:
        await asyncio.wait_for(writer.wait_closed(), timeout=1)
    except (OSError, asyncio.TimeoutError):
        pass
    return CheckResult(True, latency_ms=round(latency, 2))


async def run_check(check_type: str, host: str, port: Optional[int], timeout: float, privileged: bool = True) -> CheckResult:
    try:
        if check_type == "tcp":
            if not port:
                return CheckResult(False, error="Chequeo TCP sin puerto configurado")
            return await check_tcp(host, port, timeout)
        return await check_icmp(host, timeout, privileged)
    except Exception as exc:  # un chequeo nunca debe tumbar el monitor
        return CheckResult(False, error=f"Error inesperado: {exc!r}")
