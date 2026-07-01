# plugshub-common

Shared fleet helpers — the **SaaS Constitution Appendix A** package. A single source of truth for
cross-service standards so they are byte-identical everywhere and cannot drift.

## Modules

- `plugshub_common.health` — Article VII §2 standard `/health` (liveness) + `/ready` (readiness)
  response shapes:
  - `liveness(service, version) -> dict` — `{status, service, version, uptime_seconds}`
  - `readiness(ready, checks) -> (body, status)` — `{ready, checks}` + `200`/`503`

## Usage

```python
from plugshub_common.health import liveness, readiness

# GET /health
return JSONResponse(liveness(SERVICE_NAME, VERSION))

# GET /ready  (service builds its own `checks` + `ready`)
body, status = readiness(ready, checks)
return JSONResponse(body, status_code=status)
```

## Install (services depend on this via git)

```
plugshub-common @ git+https://github.com/Gazdella/plugshub-common.git@v0.1.0
```

Roadmap (Appendix A): the shared logging package (Article IV), the standard exception hierarchy /
error envelope (Article V), and the shared FastAPI health router are the next modules to land here.
