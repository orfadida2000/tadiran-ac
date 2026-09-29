from __future__ import annotations

import argparse
import asyncio
import json
import sys
from typing import Any

import aiohttp

from .auth import (
    AuthenticationRequired,
    authenticate_with_saved_token,
    finish_login,
    start_login,
)
from .config import (
    ConfigError,
    get_config_path,
    initialize_config,
    load_config,
    set_phone,
)
from .controller import (
    DeviceSelectionError,
    TadiranController,
)
from .credentials import (
    CredentialStoreError,
    delete_refresh_token,
    set_refresh_token,
)
from .my_tadiran.api import (
    TadiranAPI,
    TadiranAPIError,
    TadiranAuthError,
)
from .my_tadiran.const import (
    TEMP_MAX,
    TEMP_MIN,
)

EXIT_CONFIG = 3
EXIT_AUTH = 4
EXIT_DEVICE = 5
EXIT_API = 6

PROPERTY_TO_FIELD = {
    "power": "power",
    "temperature": "temp_set",
    "current-temperature": "temp_current",
    "fan": "wind_speed",
    "mode": "mode",
    "light": "light",
    "swing-vertical": "swing_ud",
    "swing-horizontal": "swing_lr",
    "turbo": "turbo",
    "mute": "mute",
    "online": "online",
}

BOOLEAN_COMMANDS = {
    "power": "power",
    "light": "light",
    "swing-vertical": "swing_ud",
    "swing-horizontal": "swing_lr",
    "turbo": "turbo",
    "mute": "mute",
}


def _temperature(value: str) -> int:
    try:
        temperature = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("temperature must be an integer") from exc

    if not TEMP_MIN <= temperature <= TEMP_MAX:
        raise argparse.ArgumentTypeError(f"temperature must be between {TEMP_MIN} and {TEMP_MAX}")

    return temperature


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tadiran-ac",
        description="Control ACs registered in a MyTadiran account.",
    )

    parser.add_argument(
        "--device",
        metavar="ID_OR_NAME",
        help=(
            "Explicit device selector. Exact device ID is checked first, "
            "then exact device name. No fallback occurs on failure."
        ),
    )

    parser.add_argument(
        "--json",
        action="store_true",
        help="Use JSON output where applicable.",
    )

    command_subparsers = parser.add_subparsers(
        dest="command",
        required=True,
    )

    # Configuration

    config_parser = command_subparsers.add_parser(
        "config",
        help="Manage the application configuration.",
    )

    config_command_subparsers = config_parser.add_subparsers(
        dest="config_command",
        required=True,
    )

    config_command_subparsers.add_parser(
        "init",
        help=("Create the configuration file with default values if it does not exist."),
    )

    config_command_subparsers.add_parser(
        "path",
        help="Print the active configuration file path.",
    )

    config_set_phone_parser = config_command_subparsers.add_parser(
        "set-phone",
        help="Set the MyTadiran account phone number.",
    )

    config_set_phone_parser.add_argument(
        "phone",
        metavar="PHONE",
        help="Phone number in +972XXXXXXXXX format.",
    )

    # Authentication

    command_subparsers.add_parser(
        "login",
        help="Authenticate by SMS and store the refresh token.",
    )

    command_subparsers.add_parser(
        "logout",
        help="Remove the stored refresh token.",
    )

    auth_parser = command_subparsers.add_parser(
        "auth",
        help="Authentication diagnostics.",
    )

    auth_command_subparsers = auth_parser.add_subparsers(
        dest="auth_command",
        required=True,
    )

    auth_command_subparsers.add_parser(
        "status",
        help="Verify that the stored refresh token can authenticate.",
    )

    # Device discovery and state

    command_subparsers.add_parser(
        "devices",
        help="List devices returned by the MyTadiran account.",
    )

    command_subparsers.add_parser(
        "status",
        help="Show the selected AC's current reported state.",
    )

    get_parser = command_subparsers.add_parser(
        "get",
        help="Print one property of the selected AC.",
    )

    get_parser.add_argument(
        "property",
        choices=sorted(PROPERTY_TO_FIELD),
    )

    # Boolean controls

    for command in BOOLEAN_COMMANDS:
        command_parser = command_subparsers.add_parser(
            command,
            help=f"Change {command}.",
        )

        command_parser.add_argument(
            "action",
            choices=("on", "off", "toggle"),
        )

    # Temperature

    temperature_parser = command_subparsers.add_parser(
        "temperature",
        help="Set the target temperature.",
    )

    temperature_parser.add_argument(
        "value",
        type=_temperature,
    )

    # Fan

    fan_parser = command_subparsers.add_parser(
        "fan",
        help="Set fan speed.",
    )

    fan_parser.add_argument(
        "value",
        choices=("auto", "low", "medium", "high"),
    )

    # HVAC mode

    mode_parser = command_subparsers.add_parser(
        "mode",
        help="Set HVAC mode and power the AC on.",
    )

    mode_parser.add_argument(
        "value",
        choices=("cool", "heat", "dry", "fan", "auto"),
    )

    return parser


def _safe_device_view(
    device: dict[str, Any],
) -> dict[str, Any]:
    return {
        "device_id": device.get("device_id"),
        "name": device.get("name"),
        "description": device.get("description"),
        "model_id": device.get("model_id"),
        "configurations": device.get("configurations") or {},
    }


def _device_summary(
    device: dict[str, Any],
) -> dict[str, Any]:
    configurations = device.get("configurations") or {}

    return {
        "device_id": device.get("device_id"),
        "name": device.get("name"),
        "description": device.get("description"),
        "model_id": device.get("model_id"),
        "online": configurations.get("online"),
    }


def _print_json(value: Any) -> None:
    print(
        json.dumps(
            value,
            indent=2,
            ensure_ascii=False,
            sort_keys=False,
        )
    )


def _format_scalar(value: Any) -> str:
    if value is True:
        return "true"

    if value is False:
        return "false"

    if value is None:
        return "null"

    return str(value)


def _print_devices(
    devices: list[dict[str, Any]],
    *,
    as_json: bool,
) -> None:
    summaries = [_device_summary(device) for device in devices]

    if as_json:
        _print_json(summaries)
        return

    if not summaries:
        print("No devices returned by MyTadiran.")
        return

    for index, device in enumerate(summaries, start=1):
        if index > 1:
            print()

        print(f"Name: {device['name']}")
        print(f"Device ID: {device['device_id']}")
        print(f"Description: {device['description']}")
        print(f"Model ID: {device['model_id']}")
        print(f"Online: {_format_scalar(device['online'])}")


def _print_status(
    device: dict[str, Any],
    *,
    as_json: bool,
) -> None:
    view = _safe_device_view(device)

    if as_json:
        _print_json(view)
        return

    print(f"Name: {view['name']}")
    print(f"Device ID: {view['device_id']}")
    print(f"Description: {view['description']}")
    print(f"Model ID: {view['model_id']}")

    configurations = view["configurations"]

    if configurations:
        print("Configurations:")

        for key, value in configurations.items():
            print(f"  {key}: {_format_scalar(value)}")


def _print_action(
    device: dict[str, Any],
    updates: dict[str, Any],
    *,
    as_json: bool,
) -> None:
    result = {
        "device_id": device.get("device_id"),
        "name": device.get("name"),
        "updates": updates,
    }

    if as_json:
        _print_json(result)
        return

    rendered = ", ".join(f"{key}={_format_scalar(value)}" for key, value in updates.items())

    print(f"Command sent to {device.get('name')!r}: {rendered}")


def _handle_config_command(
    args: argparse.Namespace,
) -> int:
    if args.config_command == "path":
        print(get_config_path())
        return 0

    if args.config_command == "init":
        path, created = initialize_config()

        if args.json:
            _print_json(
                {
                    "path": str(path),
                    "created": created,
                }
            )
        elif created:
            print(f"Created configuration file: {path}")
        else:
            print(f"Configuration file already exists: {path}")

        return 0

    if args.config_command == "set-phone":
        path, created = set_phone(args.phone)

        if args.json:
            _print_json(
                {
                    "path": str(path),
                    "created": created,
                    "phone": args.phone,
                }
            )
        else:
            if created:
                print(f"Created configuration file: {path}")

            print(f"Phone number updated: {args.phone}")

        return 0

    raise RuntimeError(f"Unhandled config command: {args.config_command!r}")


async def _login(phone: str) -> int:
    async with aiohttp.ClientSession() as session:
        api = TadiranAPI(session)

        cognito_session = await start_login(
            api,
            phone,
        )

        print(f"SMS code sent to {phone}.")

        otp = input("SMS code: ").strip()

        await finish_login(
            api,
            phone,
            cognito_session,
            otp,
        )

    print("Authentication succeeded. Refresh token stored securely.")

    return 0


async def _run_authenticated(
    args: argparse.Namespace,
    *,
    phone: str,
    default_device_id: str | None,
) -> int:
    async with aiohttp.ClientSession() as session:
        api = TadiranAPI(session)

        stored_refresh_token = await authenticate_with_saved_token(
            api,
            phone,
        )

        try:
            controller = TadiranController(
                api,
                default_device_id=default_device_id,
            )

            if args.command == "auth":
                if args.json:
                    _print_json(
                        {
                            "authenticated": True,
                            "refresh_token_stored": True,
                        }
                    )
                else:
                    print("Authentication succeeded using the stored refresh token.")

                return 0

            if args.command == "devices":
                devices = await controller.list_devices()

                _print_devices(
                    devices,
                    as_json=args.json,
                )

                return 0

            if args.command == "status":
                device = await controller.get_device(args.device)

                _print_status(
                    device,
                    as_json=args.json,
                )

                return 0

            if args.command == "get":
                device = await controller.get_device(args.device)

                field = PROPERTY_TO_FIELD[args.property]
                configurations = device.get("configurations") or {}
                value = configurations.get(field)

                if args.json:
                    _print_json(
                        {
                            "device_id": device.get("device_id"),
                            "name": device.get("name"),
                            "property": args.property,
                            "field": field,
                            "value": value,
                        }
                    )
                else:
                    print(_format_scalar(value))

                return 0

            if args.command in BOOLEAN_COMMANDS:
                device, updates = await controller.set_boolean(
                    args.device,
                    field=BOOLEAN_COMMANDS[args.command],
                    action=args.action,
                )

                _print_action(
                    device,
                    updates,
                    as_json=args.json,
                )

                return 0

            if args.command == "temperature":
                device, updates = await controller.update(
                    args.device,
                    {
                        "temp_set": args.value,
                    },
                )

                _print_action(
                    device,
                    updates,
                    as_json=args.json,
                )

                return 0

            if args.command == "fan":
                device, updates = await controller.update(
                    args.device,
                    {
                        "wind_speed": args.value.upper(),
                    },
                )

                _print_action(
                    device,
                    updates,
                    as_json=args.json,
                )

                return 0

            if args.command == "mode":
                device, updates = await controller.update(
                    args.device,
                    {
                        "power": True,
                        "mode": args.value.upper(),
                    },
                )

                _print_action(
                    device,
                    updates,
                    as_json=args.json,
                )

                return 0

            raise RuntimeError(f"Unhandled command: {args.command!r}")

        finally:
            if api.refresh_token and api.refresh_token != stored_refresh_token:
                set_refresh_token(
                    phone,
                    api.refresh_token,
                )


async def _async_main(
    args: argparse.Namespace,
) -> int:
    if args.command == "config":
        return _handle_config_command(args)

    config = load_config()

    if args.command == "logout":
        removed = delete_refresh_token(config.phone)

        if args.json:
            _print_json(
                {
                    "refresh_token_removed": removed,
                }
            )
        elif removed:
            print("Stored refresh token removed.")
        else:
            print("No stored refresh token was present.")

        return 0

    if args.command == "login":
        return await _login(config.phone)

    return await _run_authenticated(
        args,
        phone=config.phone,
        default_device_id=config.default_device_id,
    )


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()

    try:
        return asyncio.run(_async_main(args))
    except ConfigError as exc:
        print(
            f"Configuration error: {exc}",
            file=sys.stderr,
        )
        return EXIT_CONFIG
    except (
        AuthenticationRequired,
        TadiranAuthError,
        CredentialStoreError,
    ) as exc:
        print(
            f"Authentication error: {exc}",
            file=sys.stderr,
        )
        return EXIT_AUTH
    except DeviceSelectionError as exc:
        print(
            f"Device selection error: {exc}",
            file=sys.stderr,
        )
        return EXIT_DEVICE
    except (
        TadiranAPIError,
        aiohttp.ClientError,
    ) as exc:
        print(
            f"API error: {exc}",
            file=sys.stderr,
        )
        return EXIT_API
    except KeyboardInterrupt:
        print(
            "Cancelled.",
            file=sys.stderr,
        )
        return 130
