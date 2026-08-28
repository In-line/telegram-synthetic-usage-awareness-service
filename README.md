# synthetic-usage-awareness

Standalone systemd user service that monitors [Synthetic](https://synthetic.new)
subscription quota and sends Telegram alerts when significant amounts of usage
are consumed, accounting for quota regeneration (2% per 4h) to avoid false
alerts when usage regenerates back.

It ships as a native Linux package
(deb/rpm/pkg), runs one check per invocation, and is scheduled by a systemd
user timer.

## Alerts

| Alert | Threshold |
|---|---|
| 🌙 Sleep Amount Used | 8h worth (4%) |
| ☀️ Awake Amount Used | 16h worth (8%) |
| 📅 Full Day Used | 24h worth (12%) |
| ⚠️ Low Usage | below 12% remaining: every individual percent drop |

Alert thresholds are progressive: after 8h fires, the next alert is 16h, then
24h, then the cycle resets with a new baseline. If quota regenerates back to
or above the baseline, the cycle resets without alerting.

## Install

Debian 12/13, Ubuntu:

```sh
sudo apt install ./synthetic-usage-awareness_1.0.0-1_amd64.deb
```

Fedora / RHEL / openSUSE:

```sh
sudo dnf install ./synthetic-usage-awareness-1.0.0-1.*.rpm   # or zypper in
```

Arch:

```sh
sudo pacman -U ./synthetic-usage-awareness-1.0.0-1-x86_64.pkg.tar.zst
```

The post-install script seeds:

- `~/.config/synthetic-usage-awareness/config.toml` — main config
- `~/.config/synthetic-usage-awareness/env` — secrets (0600)
- `/etc/default/synthetic-usage-awareness` — system-wide secrets (root)
- systemd user units into `/usr/lib/systemd/user/`

## Configure

Fill in the secrets:

```sh
$EDITOR ~/.config/synthetic-usage-awareness/env
# SYN_AWARENESS_API_KEY=syn_...
# SYN_AWARENESS_BOT_TOKEN=123456:ABC...
# SYN_AWARENESS_CHAT_ID=-1234567
```

All settings can also live in `config.toml` (see the packaged
`config.example.toml`); environment variables always win over the file.

Check the effective configuration:

```sh
synthetic-usage-awareness --show-config
synthetic-usage-awareness --validate
```

## Enable the timer

```sh
systemctl --user enable --now synthetic-usage-awareness.timer
systemctl --user list-timers synthetic-usage-awareness.timer
journalctl --user -u synthetic-usage-awareness.service -f
```

The timer runs a check every 10 minutes (`OnBootSec=3min` for the first).

## Manual runs

```sh
synthetic-usage-awareness --once   # single check (what the timer runs)
synthetic-usage-awareness --loop   # continuous foreground mode
```

## Paths

| What | Where |
|---|---|
| Config | `$XDG_CONFIG_HOME/synthetic-usage-awareness/config.toml` (default `~/.config/...`) |
| Secrets env | `~/.config/synthetic-usage-awareness/env` or `/etc/default/synthetic-usage-awareness` |
| State | `$XDG_CACHE_HOME/synthetic-usage-awareness/state.json` (default `~/.cache/...`) |
| Units | `/usr/lib/systemd/user/synthetic-usage-awareness.{service,timer}` |

## Building packages (pkger + docker)

Packages are built with [pkger](https://github.com/vv9k/pkger) inside Docker
containers for: Debian 13, Ubuntu 24.04/26.04, Fedora 43/44, RHEL 8/9,
openSUSE Tumbleweed, and Arch.

```sh
./scripts/install-pkger.sh          # fetch pkger into ./bin
./scripts/build-all-packages.sh     # pre-tag images + build every distro
./scripts/build-all-packages.sh debian-13   # single distro
```

Artifacts land in `dist/<image>/`.

## CI/CD

- `ci.yml` — on push/PR: pre-commit (ruff lint+format, gitleaks secret scan)
  and pytest across Python 3.11–3.13, all inside Docker.
- `release.yml` — on `v*` tags: builds packages for all distros in Docker via
  pkger, smoke-tests the deb in a Debian 13 container, and attaches all
  artifacts to a GitHub Release (optional curated notes from
  `.github/release-notes/`; falls back to auto-generated notes).

Release checklist:

```sh
./scripts/release.sh v1.0.0   # optional: .github/release-notes/v1.0.0.md
```

## Development

```sh
python3 -m venv .venv && . .venv/bin/activate
pip install -e . pytest pre-commit
pre-commit install
pytest
```

Before pushing, secrets are scanned twice: by gitleaks in pre-commit and by
`scripts/secret-scan.sh` (also wired into `pre-push`).

## License

GPL-3.0-or-later — see [LICENSE](LICENSE).
