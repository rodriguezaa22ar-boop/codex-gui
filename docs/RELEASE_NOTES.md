# Release Notes

## Multi-Device Launch Utility (codex-launch-agents)

### What changed
- Added a reusable launcher script at `scripts/launch_agents.py`.
- Added YAML and JSON device config support (`.json`, `.yaml`, `.yml`).
- Added configurable result collection with `--collect-results`.
- Added `--summarize-results` and `--summary-base` for per-host diff/commit summaries.
- Added retry/backoff handling for SSH connect, sync, launch, and result collection.
- Added installable console entrypoint `codex-launch-agents`.
- Added sample configuration file: `scripts/launch_agents.yaml.example`.
- Added test coverage in `tests/test_launch_agents.py` for parsing, retry behavior, mocked collect-results, and wrapper entrypoint delegation.

### Quick usage

```bash
codex-launch-agents \
  --devices scripts/launch_agents.yaml.example \
  --prompts-dir role_prompts \
  --repo-path ~/project
```

Useful flags:
- `--sync-repo` synchronize remote checkout before launch (`git fetch` + `git pull --ff-only`).
- `--collect-results` run `git status --porcelain` after launch and include changed files.
- `--summarize-results` include `diff_summary` and `commit` metadata in JSON output.
- `--max-retries` and `--backoff-seconds` tune transient-retry behavior.

### Verification

- `python3 -m unittest discover -s tests`
- `python3 -m unittest tests.test_launch_agents -v`
- `codex doctor --summary --ascii`
