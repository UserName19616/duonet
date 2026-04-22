# src/server/api/messages/deps.py
"""
Зависимости (dependencies) для API сообщений.
Содержит функции для извлечения токена и текущего пользователя.
"""

from typing import Optional

from fastapi import Depends, Header, HTTPException, status

from src.common.identity.account import AccountManager


def get_auth_token(authorization: Optional[str] = Header(None)) -> str:
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authorization header",
        )
    if not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authorization header format",
        )
    return authorization[7:]


def get_current_public_id(
    token: str = Depends(get_auth_token),
    account_manager: AccountManager = None,
) -> str:
    if account_manager is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="AccountManager not configured in dependency",
        )
    payload = account_manager.verify_token(token)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
        )
    return payload["sub"]


def get_current_account_id(
    token: str = Depends(get_auth_token),
    account_manager: AccountManager = None,
) -> bytes:
    if account_manager is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="AccountManager not configured in dependency",
        )
    payload = account_manager.verify_token(token)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
        )
    account_id_hex = payload.get("account_id")
    if not account_id_hex:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token: missing account_id",
        )
    return bytes.fromhex(account_id_hex)


def create_dependencies(account_manager: AccountManager):
    def _get_current_public_id(token: str = Depends(get_auth_token)) -> str:
        payload = account_manager.verify_token(token)
        if not payload:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token",
            )
        return payload["sub"]

    def _get_current_account_id(token: str = Depends(get_auth_token)) -> bytes:
        payload = account_manager.verify_token(token)
        if not payload:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token",
            )
        account_id_hex = payload.get("account_id")
        if not account_id_hex:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token: missing account_id",
            )
        return bytes.fromhex(account_id_hex)

    return _get_current_public_id, _get_current_account_id
