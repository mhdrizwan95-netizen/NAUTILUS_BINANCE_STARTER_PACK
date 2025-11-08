import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import InvalidTokenError

from .config import settings

bearer = HTTPBearer(auto_error=False)


def _jwt_options() -> dict:
    return {"require": ["exp"]} if settings.REQUIRE_AUTH else {}


def _decode(token: str) -> dict:
    try:
        if settings.JWT_PUBLIC_KEY:
            return jwt.decode(
                token,
                settings.JWT_PUBLIC_KEY,
                algorithms=[settings.JWT_ALG],
                options=_jwt_options(),
            )
        if settings.JWT_SECRET:
            return jwt.decode(
                token,
                settings.JWT_SECRET,
                algorithms=[settings.JWT_ALG],
                options=_jwt_options(),
            )
        if settings.REQUIRE_AUTH:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Auth required")
        return {"role": "admin"}  # dev-mode permissive
    except InvalidTokenError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")


def require_role(*roles: str):
    def _check(creds: HTTPAuthorizationCredentials = Depends(bearer)):
        if settings.REQUIRE_AUTH and not creds:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing Authorization header",
            )
        payload = _decode(creds.credentials) if creds else {"role": "admin"}
        role = payload.get("role") or payload.get("roles", "")
        allowed = role in roles or (isinstance(role, list) and any(r in roles for r in role))
        if not allowed:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient role")
        return payload

    return _check
