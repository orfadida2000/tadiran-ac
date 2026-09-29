"""Async client for the Tadiran cloud API and its AWS Cognito auth.

Adapted from rluvaton/ha-my-tadiran and used under the MIT License.
See THIRD_PARTY_LICENSES/ha-my-tadiran-LICENSE.
"""
from __future__ import annotations

import base64
import json
import logging
import re
import time
from typing import Any

import aiohttp

from .const import (
    COGNITO_CLIENT_ID,
    COGNITO_URL,
    ORG_ID_EU,
    ORG_ID_IL,
    TADIRAN_BASE_URL,
)

_LOGGER = logging.getLogger(__name__)


class TadiranAuthError(Exception):
    """Authentication failed; the user needs to reauth."""


class TadiranInvalidOTP(TadiranAuthError):
    """The OTP code was wrong or expired."""


class TadiranAPIError(Exception):
    """A non-auth API call failed."""


def _decode_jwt_payload(token: str) -> dict[str, Any]:
    payload_b64 = token.split(".")[1]
    payload_b64 += "=" * (-len(payload_b64) % 4)
    return json.loads(base64.urlsafe_b64decode(payload_b64))


class TadiranAPI:
    """Async Tadiran API client."""

    def __init__(self, session: aiohttp.ClientSession) -> None:
        self._session = session
        self.access_token: str | None = None
        self.id_token: str | None = None
        self.refresh_token: str | None = None
        self.org_id: str | None = None

    async def _cognito(self, target: str, body: dict[str, Any]) -> dict[str, Any]:
        async with self._session.post(
            COGNITO_URL,
            headers={
                "Content-Type": "application/x-amz-json-1.1",
                "X-Amz-Target": (
                    f"AWSCognitoIdentityProviderService.{target}"
                ),
            },
            data=json.dumps(body),
        ) as resp:
            data = await resp.json(content_type=None)
            if resp.status != 200:
                err_type = data.get("__type", "Unknown")
                err_msg = data.get("message", "")
                if "CodeMismatch" in err_type or "ExpiredCode" in err_type:
                    raise TadiranInvalidOTP(f"{err_type}: {err_msg}")
                raise TadiranAuthError(f"{err_type}: {err_msg}")
            return data

    async def initiate_otp(self, phone: str) -> str:
        """Send SMS OTP. Return the Cognito session for verify_otp()."""
        resp = await self._cognito(
            "InitiateAuth",
            {
                "ClientId": COGNITO_CLIENT_ID,
                "AuthFlow": "CUSTOM_AUTH",
                "AuthParameters": {"USERNAME": phone},
            },
        )
        return resp["Session"]

    async def verify_otp(self, phone: str, session: str, otp: str) -> None:
        """Submit OTP and store tokens."""
        resp = await self._cognito(
            "RespondToAuthChallenge",
            {
                "ClientId": COGNITO_CLIENT_ID,
                "ChallengeName": "CUSTOM_CHALLENGE",
                "Session": session,
                "ChallengeResponses": {
                    "USERNAME": phone,
                    "ANSWER": otp,
                },
            },
        )

        while "ChallengeName" in resp and "AuthenticationResult" not in resp:
            resp = await self._cognito(
                "RespondToAuthChallenge",
                {
                    "ClientId": COGNITO_CLIENT_ID,
                    "ChallengeName": resp["ChallengeName"],
                    "Session": resp["Session"],
                    "ChallengeResponses": {
                        "USERNAME": phone,
                        "ANSWER": otp,
                    },
                },
            )

        auth_result = resp.get("AuthenticationResult")
        if not auth_result:
            raise TadiranAuthError("No AuthenticationResult in response")
        self._store_tokens(auth_result)

    async def refresh(self) -> None:
        """Exchange refresh_token for fresh ID/access tokens."""
        if not self.refresh_token:
            raise TadiranAuthError("No refresh_token available")

        resp = await self._cognito(
            "InitiateAuth",
            {
                "ClientId": COGNITO_CLIENT_ID,
                "AuthFlow": "REFRESH_TOKEN_AUTH",
                "AuthParameters": {
                    "REFRESH_TOKEN": self.refresh_token,
                },
            },
        )

        auth_result = resp.get("AuthenticationResult")
        if not auth_result:
            raise TadiranAuthError(
                "Refresh failed: no AuthenticationResult"
            )

        self._store_tokens(auth_result)

    def _store_tokens(self, auth_result: dict[str, Any]) -> None:
        self.access_token = auth_result["AccessToken"]
        self.id_token = auth_result["IdToken"]

        if auth_result.get("RefreshToken"):
            self.refresh_token = auth_result["RefreshToken"]

        self._derive_org_id()

    def _derive_org_id(self) -> None:
        if not self.id_token:
            return

        try:
            claims = _decode_jwt_payload(self.id_token)
        except (ValueError, IndexError) as exc:
            _LOGGER.warning("Could not decode id_token: %s", exc)
            return

        email = claims.get("email", "")
        match = re.search(r"tenant-[a-f0-9-]{36}", email)
        if match:
            self.org_id = match.group(0)
            return

        region = claims.get("custom:region", "il")
        self.org_id = ORG_ID_IL if region == "il" else ORG_ID_EU

    def _id_token_exp(self) -> int:
        if not self.id_token:
            return 0

        try:
            return int(_decode_jwt_payload(self.id_token).get("exp", 0))
        except (ValueError, IndexError):
            return 0

    def _auth_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.access_token}",
            "idtoken": self.id_token or "",
            "organizationid": self.org_id or "",
        }

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: Any = None,
        extra_headers: dict[str, str] | None = None,
    ) -> Any:
        if self._id_token_exp() - time.time() < 60:
            await self.refresh()

        headers = self._auth_headers()
        if extra_headers:
            headers.update(extra_headers)

        url = f"{TADIRAN_BASE_URL}{path}"

        for attempt in range(2):
            async with self._session.request(
                method,
                url,
                headers=headers,
                json=json_body,
            ) as resp:
                if resp.status == 401 and attempt == 0:
                    _LOGGER.debug(
                        "401 from %s, refreshing and retrying",
                        path,
                    )
                    await self.refresh()
                    headers = self._auth_headers()
                    if extra_headers:
                        headers.update(extra_headers)
                    continue

                if resp.status >= 400:
                    body = await resp.text()
                    raise TadiranAPIError(
                        f"{method} {path} -> {resp.status}: "
                        f"{body[:200]}"
                    )

                if resp.content_length == 0:
                    return None

                return await resp.json(content_type=None)

        raise TadiranAPIError(f"{method} {path}: retry exhausted")

    async def get_devices(self) -> list[dict[str, Any]]:
        return await self._request(
            "GET",
            "/tadiran-mobile-app/api/v1/devices/",
        )

    async def update_device_shadow(
        self,
        device_id: str,
        updates: dict[str, Any],
    ) -> Any:
        body = [
            {"name": key, "value": value}
            for key, value in updates.items()
        ]

        return await self._request(
            "PUT",
            f"/mobile-app/api/v1/devices/{device_id}/shadow/update/",
            json_body=body,
            extra_headers={
                "x-manufacturer-name": "TUYA",
                "Content-Type": "application/json",
            },
        )
