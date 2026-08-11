# devin-cli-usage

Devin account usage and quota monitor. It follows the same dependency-free
interface as the other `/code/*usage` tools.

The tool targets the local Devin CLI harness, but reports account-wide Devin
quota. It does not estimate usage from local CLI sessions.

## Example output

```text
Devin usage
Status: live
Plan: Pro
Daily: 100% remaining, resets in 11h
Weekly: 100% remaining, resets in 6d11h
Prompt credits available: -1
```

Statusline:

```text
devin:daily:100%left reset:11h
```

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

The normalized JSON includes:

- `provider`, `source`, `retrieved_at`, and `status`
- plan name, billing strategy, and plan period
- daily and weekly quota percentages and reset times
- available and consumed credits, ACU limits, and overage balance when supplied

`status` is `live`, `cached`, `stale`, or `unavailable`. Errors and caches do
not include the API key or Devin account identity. A credit value of `-1` is a
vendor sentinel for an unlimited or non-credit-based allowance and is
preserved verbatim.

The tool writes only its own non-secret cache at
`~/.local/share/devin/usage-limits.json`. JSON results report whether they are
`live`, `cached`, `stale`, or `unavailable`.

Environment overrides:

- `DEVIN_USAGE_CREDENTIALS_FILE`: alternate credentials file
- `DEVIN_USAGE_FILE`: alternate cache path

The user-status service is undocumented and may change with Devin client
releases.

## Options

```text
usage: devin-cli-usage [-h] [-i INTERVAL] [--max-age MAX_AGE] [--refresh]
                       {status,json,daemon,statusline,refresh,install}
```

- `--max-age SECS`: maximum cache age used by `statusline`
- `--refresh`: bypass the cache for `statusline`
- `-i SECS`: daemon refresh interval

## Development

```bash
uv --no-config lock --check
uv --no-config run --locked python -m unittest discover -s tests
uv --no-config build --no-sources
```
