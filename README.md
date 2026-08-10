# devin-cli-usage

Devin account usage and quota monitor. It follows the same dependency-free
interface as the other `/code/*usage` tools.

## Install

```bash
uv tool install devin-cli-usage
```

For local development:

```bash
uv tool install .
```

## Commands

| Command | Description |
| --- | --- |
| `devin-cli-usage` | Show current account usage |
| `devin-cli-usage status` | Same as above |
| `devin-cli-usage json` | Print normalized JSON |
| `devin-cli-usage statusline` | Print compact cached output |
| `devin-cli-usage refresh` | Refresh the cache and print status |
| `devin-cli-usage daemon [-i SECS]` | Keep the cache fresh |
| `devin-cli-usage install` | Print installation instructions |

## Authentication and data

The tool reads `windsurf_api_key` and `api_server_url` from Devin's local
`~/.local/share/devin/credentials.toml`, then calls the read-only
`GetUserStatus` service used by the installed client. It rereads credentials
for every live request. It never refreshes credentials or modifies
Devin-owned files.

The tool writes only its own non-secret cache at
`~/.local/share/devin/usage-limits.json`. JSON results report whether they are
`live`, `cached`, `stale`, or `unavailable`.

Environment overrides:

- `DEVIN_USAGE_CREDENTIALS_FILE`: alternate credentials file
- `DEVIN_USAGE_FILE`: alternate cache path

The user-status service is undocumented and may change with Devin client
releases.
