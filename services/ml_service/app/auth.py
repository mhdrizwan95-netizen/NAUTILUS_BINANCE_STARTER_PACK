"""Authentication for ML service."""

import os
from functools import wraps
from typing import Callable

from fastapi import HTTPException, Request


def require_role(*allowed_roles: str) -> Callable:
    """Dependency that checks for required API roles.
    
    In production, this should validate JWT tokens or API keys.
    For now, allows all requests in dev mode.
    """
    async def dependency(request: Request):
        # Dev mode: always allow
        if os.getenv("ML_SERVICE_AUTH_DISABLED", "true").lower() in ("1", "true", "yes"):
            return
        
        # Check for API key in header
        api_key = request.headers.get("X-API-Key", "")
        expected_key = os.getenv("ML_SERVICE_API_KEY", "")
        
        if expected_key and api_key != expected_key:
            raise HTTPException(status_code=401, detail="Invalid or missing API key")
        
        # Check role from header (simplified, production should use JWT)
        role = request.headers.get("X-Role", "admin")
        if role not in allowed_roles:
            raise HTTPException(status_code=403, detail=f"Role {role} not in {allowed_roles}")
    
    return dependency
