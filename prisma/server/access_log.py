import logging
import time

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

_log = logging.getLogger("prisma.access")


class AccessLogMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        t0 = time.monotonic()
        response = await call_next(request)
        elapsed_ms = (time.monotonic() - t0) * 1000
        _log.info("%s %s %d %.0fms", request.method, request.url.path, response.status_code, elapsed_ms)
        return response
