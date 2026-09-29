from __future__ import annotations

from typing import Any

from .my_tadiran.api import TadiranAPI


BOOL_FIELDS = frozenset(
    {
        "power",
        "online",
        "light",
        "turbo",
        "mute",
        "swing_ud",
        "swing_lr",
    }
)


class DeviceSelectionError(Exception):
    """A requested AC could not be selected safely."""


def _coerce_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes"}
    return bool(value)


def normalize_device(device: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(device)
    configurations = dict(normalized.get("configurations") or {})

    for field in BOOL_FIELDS:
        if field in configurations:
            configurations[field] = _coerce_bool(configurations[field])

    normalized["configurations"] = configurations
    return normalized


def resolve_device(
    devices: list[dict[str, Any]],
    *,
    selector: str | None,
    default_device_id: str | None,
) -> dict[str, Any]:
    normalized_devices = [normalize_device(device) for device in devices]

    if selector is not None:
        id_matches = [
            device
            for device in normalized_devices
            if device.get("device_id") == selector
        ]
        if id_matches:
            return id_matches[0]

        name_matches = [
            device
            for device in normalized_devices
            if device.get("name") == selector
        ]

        if len(name_matches) == 1:
            return name_matches[0]

        if len(name_matches) > 1:
            raise DeviceSelectionError(
                f"Multiple Tadiran ACs have the exact name {selector!r}. "
                "Use a device ID instead."
            )

        raise DeviceSelectionError(
            f"No Tadiran AC matched explicit device selector {selector!r}. "
            "The configured default was not used."
        )

    if not default_device_id:
        raise DeviceSelectionError(
            "No --device was provided and 'default_device_id' is not configured."
        )

    for device in normalized_devices:
        if device.get("device_id") == default_device_id:
            return device

    raise DeviceSelectionError(
        f"The configured default_device_id {default_device_id!r} does not match "
        "any device currently returned by MyTadiran."
    )


class TadiranController:
    def __init__(
        self,
        api: TadiranAPI,
        *,
        default_device_id: str | None,
    ) -> None:
        self._api = api
        self._default_device_id = default_device_id

    async def list_devices(self) -> list[dict[str, Any]]:
        return [
            normalize_device(device)
            for device in await self._api.get_devices()
        ]

    async def get_device(self, selector: str | None) -> dict[str, Any]:
        devices = await self.list_devices()
        return resolve_device(
            devices,
            selector=selector,
            default_device_id=self._default_device_id,
        )

    async def update(
        self,
        selector: str | None,
        updates: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        device = await self.get_device(selector)
        device_id = device.get("device_id")

        if not isinstance(device_id, str) or not device_id:
            raise DeviceSelectionError(
                "The selected device did not contain a usable device_id."
            )

        await self._api.update_device_shadow(device_id, updates)
        return device, updates

    async def set_boolean(
        self,
        selector: str | None,
        *,
        field: str,
        action: str,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        if field not in BOOL_FIELDS:
            raise ValueError(f"{field!r} is not a supported boolean field.")

        device = await self.get_device(selector)
        configurations = device.get("configurations") or {}

        if action == "on":
            value = True
        elif action == "off":
            value = False
        elif action == "toggle":
            if field not in configurations:
                raise DeviceSelectionError(
                    f"The selected device did not report the {field!r} field, "
                    "so it cannot be toggled safely."
                )
            value = not _coerce_bool(configurations[field])
        else:
            raise ValueError(f"Unsupported boolean action: {action!r}")

        device_id = device.get("device_id")
        if not isinstance(device_id, str) or not device_id:
            raise DeviceSelectionError(
                "The selected device did not contain a usable device_id."
            )

        updates = {field: value}
        await self._api.update_device_shadow(device_id, updates)
        return device, updates
