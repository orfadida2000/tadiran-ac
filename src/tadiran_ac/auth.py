from __future__ import annotations

from .credentials import get_refresh_token, set_refresh_token
from .my_tadiran.api import TadiranAPI, TadiranAuthError


class AuthenticationRequired(Exception):
    """A fresh interactive login is required."""


async def authenticate_with_saved_token(api: TadiranAPI, phone: str) -> str:
    stored_token = get_refresh_token(phone)

    if not stored_token:
        raise AuthenticationRequired(
            "No stored refresh token. Run 'tadiran-ac login' first."
        )

    api.refresh_token = stored_token

    try:
        await api.refresh()
    except TadiranAuthError as exc:
        raise AuthenticationRequired(
            "The stored refresh token was rejected. Run 'tadiran-ac login' "
            "to authenticate again."
        ) from exc

    if api.refresh_token and api.refresh_token != stored_token:
        set_refresh_token(phone, api.refresh_token)

    return stored_token


async def start_login(api: TadiranAPI, phone: str) -> str:
    """Send the SMS OTP and return the Cognito challenge session."""
    return await api.initiate_otp(phone)


async def finish_login(
    api: TadiranAPI,
    phone: str,
    cognito_session: str,
    otp: str,
) -> None:
    """Verify the OTP and persist the resulting refresh token."""
    await api.verify_otp(phone, cognito_session, otp)

    if not api.refresh_token:
        raise TadiranAuthError(
            "Authentication succeeded but Cognito did not return a refresh token."
        )

    set_refresh_token(phone, api.refresh_token)
