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

class VercelPathMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # Vercel sends the original requested path in headers
        original_path = (
            request.headers.get("x-matched-path")
            or request.headers.get("x-invoke-path")
            or request.headers.get("x-forwarded-uri")
        )
        if original_path and request.scope["path"] in ["/api/index.py", "/api/index"]:
            # Strip query params if any
            clean_path = original_path.split("?")[0]
            request.scope["path"] = clean_path
        return await call_next(request)

app.add_middleware(VercelPathMiddleware)

@app.api_route("/api/index.py", methods=["GET", "POST"])
async def vercel_debug_fallback(request: Request):
    headers = dict(request.headers)
    matched = headers.get("x-matched-path") or headers.get("x-invoke-path") or "/"
    if matched in ["/", "/index.html"]:
        from backend.main import serve_index
        return serve_index()
    elif matched in ["/app", "/app.html"]:
        from backend.main import serve_app
        return serve_app()
    elif "/api/deals" in matched:
        from backend.main import get_deals
        return get_deals()
    return {
        "status": "dealmind_engine_online",
        "matched_path": matched,
        "headers": headers
    }

