from __future__ import annotations

import unittest

from tadiran_ac.controller import (
    DeviceSelectionError,
    resolve_device,
)


DEVICES = [
    {
        "device_id": "id-a",
        "name": "Bedroom",
        "configurations": {"power": True},
    },
    {
        "device_id": "id-b",
        "name": "Living Room",
        "configurations": {"power": False},
    },
]


class DeviceResolutionTests(unittest.TestCase):
    def test_uses_default_device_id_when_selector_is_omitted(self) -> None:
        device = resolve_device(
            DEVICES,
            selector=None,
            default_device_id="id-b",
        )
        self.assertEqual(device["device_id"], "id-b")

    def test_explicit_device_id_matches(self) -> None:
        device = resolve_device(
            DEVICES,
            selector="id-a",
            default_device_id="id-b",
        )
        self.assertEqual(device["device_id"], "id-a")

    def test_explicit_exact_name_matches(self) -> None:
        device = resolve_device(
            DEVICES,
            selector="Bedroom",
            default_device_id="id-b",
        )
        self.assertEqual(device["device_id"], "id-a")

    def test_explicit_no_match_does_not_fall_back(self) -> None:
        with self.assertRaises(DeviceSelectionError):
            resolve_device(
                DEVICES,
                selector="Does Not Exist",
                default_device_id="id-b",
            )

    def test_duplicate_exact_names_are_rejected(self) -> None:
        devices = [
            {
                "device_id": "id-a",
                "name": "Bedroom",
                "configurations": {},
            },
            {
                "device_id": "id-b",
                "name": "Bedroom",
                "configurations": {},
            },
        ]
        with self.assertRaises(DeviceSelectionError):
            resolve_device(
                devices,
                selector="Bedroom",
                default_device_id=None,
            )

    def test_missing_default_is_rejected(self) -> None:
        with self.assertRaises(DeviceSelectionError):
            resolve_device(
                DEVICES,
                selector=None,
                default_device_id=None,
            )


if __name__ == "__main__":
    unittest.main()
