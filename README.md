# tadiran-ac

A Windows-oriented command-line client for controlling air conditioners
registered in a MyTadiran account.

The program uses the MyTadiran cloud API. Authentication is performed through
the same AWS Cognito flow used by the upstream `ha-my-tadiran` integration.

## Security model

Only the Cognito **refresh token** is persisted as a secret. It is stored via
Python `keyring`, which uses the Windows credential backend on Windows.

The following are not persisted as secrets by this project:

- SMS OTP
- access token
- ID token

The normal configuration file contains personal but non-secret data such as
the MyTadiran phone number and default device ID.

## Configuration location

By default:

```text
%APPDATA%\tadiran-ac\config.toml
```

You can override the path with the `TADIRAN_AC_CONFIG` environment variable.

Start by copying `config.example.toml` to the path above.

## Initial setup

Install dependencies / run from the checkout:

```powershell
uv sync
```

Copy the example configuration:

```powershell
$configDir = Join-Path $env:APPDATA 'tadiran-ac'
New-Item -ItemType Directory -Path $configDir -Force | Out-Null
Copy-Item .\config.example.toml (Join-Path $configDir 'config.toml')
```

Edit `config.toml` and replace:

```toml
phone = "+972XXXXXXXXX"
```

with the full MyTadiran phone number in E.164 form.

Then authenticate:

```powershell
uv run tadiran-ac login
```

The command sends an SMS and prompts for the OTP once. The resulting refresh
token is stored in the Windows credential store.

List the ACs registered to the account:

```powershell
uv run tadiran-ac devices
```

Copy the desired device ID into:

```toml
default_device_id = "REPLACE_WITH_DEVICE_ID"
```

in `config.toml`.

## Device selection

When `--device` is omitted, the program uses `default_device_id` from the
configuration.

When `--device` is explicitly provided, it is resolved in this order:

1. exact device ID;
2. exact device name.

If an explicit selector does not match, the command fails. It never falls back
to the configured default.

If multiple devices have the same exact name, selection by that name fails and
you must use the device ID.

Examples:

```powershell
uv run tadiran-ac status
uv run tadiran-ac --device 'DEVICE_ID' status
uv run tadiran-ac --device 'Bedroom' status
```

## Commands

Authentication:

```text
tadiran-ac login
tadiran-ac logout
tadiran-ac auth status
```

Discovery/state:

```text
tadiran-ac devices
tadiran-ac status
tadiran-ac get power
tadiran-ac get temperature
tadiran-ac get current-temperature
tadiran-ac get fan
tadiran-ac get mode
tadiran-ac get light
tadiran-ac get swing-vertical
tadiran-ac get swing-horizontal
tadiran-ac get turbo
tadiran-ac get mute
tadiran-ac get online
```

Power:

```text
tadiran-ac power on
tadiran-ac power off
tadiran-ac power toggle
```

Target temperature:

```text
tadiran-ac temperature 22
```

Fan:

```text
tadiran-ac fan auto
tadiran-ac fan low
tadiran-ac fan medium
tadiran-ac fan high
```

HVAC mode:

```text
tadiran-ac mode cool
tadiran-ac mode heat
tadiran-ac mode dry
tadiran-ac mode fan
tadiran-ac mode auto
```

Other boolean controls:

```text
tadiran-ac light on|off|toggle
tadiran-ac swing-vertical on|off|toggle
tadiran-ac swing-horizontal on|off|toggle
tadiran-ac turbo on|off|toggle
tadiran-ac mute on|off|toggle
```

Use `--json` before the subcommand for machine-readable output where applicable:

```powershell
uv run tadiran-ac --json status
```

## Installing as a command for AutoHotkey

After testing the checkout:

```powershell
uv tool install .
```

Then AutoHotkey can invoke short-lived commands directly, for example:

```text
tadiran-ac power toggle
tadiran-ac --device "DEVICE_ID" power off
tadiran-ac --device "Bedroom" temperature 23
```

The Python process does not need to remain running in the background. Each
invocation loads the stored refresh token, obtains fresh short-lived Cognito
tokens, performs the operation, and exits.

## Notes

- `mode` intentionally sends both `power=true` and the selected mode, matching
  the behavior of the upstream Home Assistant integration.
- Single-setting commands send only the field they need, except for `mode` as
  described above.
- Some Tadiran models may report an unusable sentinel value for
  `temp_current`; `temperature` refers to `temp_set`, the target temperature.
- Cloud shadow updates can lag, so an immediate read after a write may briefly
  show the previous value.

## Tests

The included device-resolution tests use only the Python standard library:

```powershell
uv run python -m unittest discover -s tests
```
