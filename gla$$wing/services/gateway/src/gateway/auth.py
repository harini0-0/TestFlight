"""Tenant comes from the token. A client-supplied tenant id is not authority."""

from __future__ import annotations

import os
from dataclasses import dataclass

import jwt
from fastapi import HTTPException

DEV_SECRET = os.environ.get("DEV_JWT_SECRET", "glasswing-local-dev-jwt-secret!!")
ROLES = {"org_admin", "procurement_manager", "ap_analyst", "auditor", "connector"}


@dataclass
class Principal:
    sub: str
    tenant_id: str
    role: str
    scope: str = ""


def issue_dev_token(sub: str, tenant_id: str, role: str) -> str:
    if role not in ROLES:
        raise ValueError("unknown role")
    return jwt.encode(
        {"sub": sub, "tenant_id": tenant_id, "role": role, "iss": "glasswing-dev"},
        DEV_SECRET,
        algorithm="HS256",
    )


def decode_bearer(token: str) -> Principal:
    jwks_url = os.environ.get("COGNITO_JWKS_URL")
    try:
        if jwks_url:
            signing_key = jwt.PyJWKClient(jwks_url).get_signing_key_from_jwt(token)
            payload = jwt.decode(token, signing_key.key, algorithms=["RS256"], options={"verify_aud": False})
        else:
            payload = jwt.decode(token, DEV_SECRET, algorithms=["HS256"])
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=401, detail="invalid token") from exc
    tenant_id = payload.get("tenant_id") or payload.get("custom:tenant_id")
    role = payload.get("role") or payload.get("custom:role") or "auditor"
    if not tenant_id:
        raise HTTPException(status_code=401, detail="token has no tenant")
    return Principal(sub=str(payload.get("sub")), tenant_id=str(tenant_id), role=str(role))


def reject_client_tenant(principal: Principal, body: dict | None) -> None:
    if body and body.get("tenant_id") and body["tenant_id"] != principal.tenant_id:
        raise HTTPException(status_code=403, detail="tenant id is taken from the token")


def require_role(principal: Principal, *roles: str) -> None:
    if principal.role == "org_admin":
        return
    if principal.role not in roles:
        raise HTTPException(status_code=403, detail="role cannot perform this action")
