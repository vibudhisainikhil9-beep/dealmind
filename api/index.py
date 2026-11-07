import sys
import os
from starlette.middleware.base import BaseHTTPMiddleware
from fastapi import Request

# Ensure backend directory is in sys.path
root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
backend_dir = os.path.join(root_dir, "backend")

if root_dir not in sys.path:
    sys.path.insert(0, root_dir)
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from backend.main import app

class VercelQueryPathMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        target_path = request.query_params.get("__path__")
        if target_path:
            clean_subpath = target_path.split("?")[0].strip("/")
            request.scope["path"] = f"/api/{clean_subpath}"
        return await call_next(request)

app.add_middleware(VercelQueryPathMiddleware)

__all__ = ["app"]
