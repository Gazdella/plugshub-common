"""Standard health/readiness probe shapes (SaaS Constitution Article VII §2).

The single source of truth for the fleet-standard ``/health`` (liveness) and ``/ready`` (readiness)
response shapes. Every service imports these so its probes are byte-identical and cannot drift. The
service supplies its own dependency *checks* (which deps to poll); the envelope + status semantics
live here.
"""

import time
from typing import Any, Dict, Tuple

# Process start, for the liveness uptime field (import time ≈ process start).
_START_TIME = time.time()


def liveness(service: str, version: str) -> Dict[str, Any]:
    """Article VII §1 liveness — cheap, no dependency I/O. Standard shape:
    ``status`` / ``service`` / ``version`` / ``uptime_seconds``."""
    return {
        "status": "alive",
        "service": service,
        "version": version,
        "uptime_seconds": round(time.time() - _START_TIME, 1),
    }


def readiness(ready: bool, checks: Dict[str, Any]) -> Tuple[Dict[str, Any], int]:
    """Article VII §1 readiness — the standard ``{ready, checks}`` body plus the authoritative
    status (503 when a hard dependency is down, so a load balancer / probe stops routing)."""
    return {"ready": ready, "checks": checks}, (200 if ready else 503)
