from __future__ import annotations

import keyring
from keyring.errors import KeyringError


SERVICE_NAME = "tadiran-ac"


class CredentialStoreError(Exception):
    """Access to the OS credential store failed."""


def get_refresh_token(phone: str) -> str | None:
    try:
        return keyring.get_password(SERVICE_NAME, phone)
    except KeyringError as exc:
        raise CredentialStoreError(
            f"Could not read the refresh token from the credential store: {exc}"
        ) from exc


def set_refresh_token(phone: str, refresh_token: str) -> None:
    try:
        keyring.set_password(SERVICE_NAME, phone, refresh_token)
    except KeyringError as exc:
        raise CredentialStoreError(
            f"Could not save the refresh token to the credential store: {exc}"
        ) from exc


def delete_refresh_token(phone: str) -> bool:
    try:
        existing = keyring.get_password(SERVICE_NAME, phone)
        if existing is None:
            return False
        keyring.delete_password(SERVICE_NAME, phone)
        return True
    except KeyringError as exc:
        raise CredentialStoreError(
            f"Could not delete the refresh token from the credential store: {exc}"
        ) from exc
