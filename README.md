# devin-cli-usage

`devin-cli-usage` shows your Devin quota from the terminal: how much of the daily and weekly limits you have used, and when they reset.

```sh
uv tool install devin-cli-usage
devin-cli-usage
```

`devin-cli-usage` is developed in [clanker-usage](https://github.com/wakamex/clanker-usage), which also has the documentation, the issue tracker, and matching monitors for Claude Code, Codex, Antigravity, Gemini CLI, Cursor, DeepSeek, OpenCode Go and Z.ai. This repository holds its history up to version 0.1.1 and is read-only.

Every version stays on PyPI. 0.4.0 changed the options, JSON output and cache location ([release notes](https://github.com/wakamex/clanker-usage/releases/tag/v0.4.0)); to keep the earlier behavior, install `devin-cli-usage==0.1.1`.
