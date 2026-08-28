"""synthetic-usage-awareness — Synthetic subscription usage tracker service.

Monitors Synthetic API quota and sends Telegram alerts when significant
amounts of usage are consumed. Accounts for quota regeneration (2% per 4h)
to avoid false alerts when usage regenerates back.

Standalone service decoupled from Hermes Agent:
  - scheduled by a systemd user timer (or `--loop` for continuous mode)
  - configuration in $XDG_CONFIG_HOME/synthetic-usage-awareness/config.toml
  - state in $XDG_CACHE_HOME/synthetic-usage-awareness/state.json

Alerts:
  - 8h worth (4%): "Sleep amount used"
  - 16h worth (8%): "Awake amount used"
  - 24h worth (12%): "Full day used"
  - Below 12% remaining: every individual percent drop

Monitoring interval scales linearly with remaining quota:
  - 10 min at 100% remaining
  - 1 min below 12% remaining

Copyright (C) 2026 Alik

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <https://www.gnu.org/licenses/>.
"""

from __future__ import annotations

__version__ = "1.0.0"

__all__ = ["__version__"]
