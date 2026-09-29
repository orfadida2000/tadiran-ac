from __future__ import annotations

import os
import re
import tomllib
from dataclasses import dataclass
from importlib import resources
from pathlib import Path

from platformdirs import user_config_path

APP_NAME = "tadiran-ac"
CONFIG_FILE_NAME = "config.toml"
CONFIG_PATH_ENV_VAR = "TADIRAN_AC_CONFIG"
DEFAULT_CONFIG_RESOURCE = "config.default.toml"

_PHONE_PATTERN = re.compile(r"\+972[0-9]{9}")
_PHONE_ASSIGNMENT_PATTERN = re.compile(r"(?m)^(?P<prefix>[ \t]*phone[ \t]*=[ \t]*).*$")

_PLACEHOLDER_DEVICE_IDS = {
    "",
    "REPLACE_WITH_DEVICE_ID",
}


class ConfigError(Exception):
    """The local application configuration is missing or invalid."""


@dataclass(frozen=True)
class AppConfig:
    phone: str
    default_device_id: str | None


def get_config_path() -> Path:
    override = os.environ.get(CONFIG_PATH_ENV_VAR)

    if override:
        return Path(override).expanduser()

    return (
        user_config_path(
            APP_NAME,
            appauthor=False,
            roaming=True,
        )
        / CONFIG_FILE_NAME
    )


def _validate_phone(phone: str) -> str:
    phone = phone.strip()

    if not _PHONE_PATTERN.fullmatch(phone):
        raise ConfigError(
            "Phone number must be an Israeli E.164 number in the form '+972XXXXXXXXX'."
        )

    return phone


def _get_default_config() -> str:
    try:
        return (
            resources.files("tadiran_ac")
            .joinpath(DEFAULT_CONFIG_RESOURCE)
            .read_text(encoding="utf-8")
        )
    except (FileNotFoundError, OSError) as exc:
        raise ConfigError(
            f"Could not load packaged default configuration {DEFAULT_CONFIG_RESOURCE!r}: {exc}"
        ) from exc


def initialize_config() -> tuple[Path, bool]:
    path = get_config_path()

    if path.exists():
        if not path.is_file():
            raise ConfigError(f"Configuration path exists but is not a file: {path}")

        return path, False

    try:
        path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        path.write_text(
            _get_default_config(),
            encoding="utf-8",
        )
    except OSError as exc:
        raise ConfigError(f"Could not create configuration file {path}: {exc}") from exc

    return path, True


def set_phone(phone: str) -> tuple[Path, bool]:
    phone = _validate_phone(phone)

    path, created = initialize_config()

    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError(f"Could not read configuration file {path}: {exc}") from exc

    try:
        tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"Could not parse configuration file {path}: {exc}") from exc

    if _PHONE_ASSIGNMENT_PATTERN.search(text):
        text = _PHONE_ASSIGNMENT_PATTERN.sub(
            lambda match: f'{match.group("prefix")}"{phone}"',
            text,
            count=1,
        )
    else:
        if text and not text.endswith("\n"):
            text += "\n"

        text += f'phone = "{phone}"\n'

    try:
        path.write_text(
            text,
            encoding="utf-8",
        )
    except OSError as exc:
        raise ConfigError(f"Could not write configuration file {path}: {exc}") from exc

    return path, created


def load_config() -> AppConfig:
    path = get_config_path()

    if not path.is_file():
        raise ConfigError(
            f"Configuration file not found: {path}\nRun 'tadiran-ac config init' first."
        )

    try:
        with path.open("rb") as file:
            data = tomllib.load(file)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ConfigError(f"Could not read configuration file {path}: {exc}") from exc

    phone = data.get("phone")

    if not isinstance(phone, str):
        raise ConfigError("Config value 'phone' must be a string.")

    phone = _validate_phone(phone)

    default_device_id = data.get("default_device_id")

    if default_device_id is None:
        normalized_device_id = None
    elif not isinstance(default_device_id, str):
        raise ConfigError("Config value 'default_device_id' must be a string.")
    else:
        normalized_device_id = default_device_id.strip()

        if normalized_device_id in _PLACEHOLDER_DEVICE_IDS:
            normalized_device_id = None

    return AppConfig(
        phone=phone,
        default_device_id=normalized_device_id,
    )
