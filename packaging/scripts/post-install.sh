#!/bin/sh
# Post-install script for synthetic-usage-awareness packages (deb/rpm/pkg).
#
# Installs the systemd user units into the system template directory so every
# user gets them via systemctl --user, seeds a commented config into the
# invoking user's ~/.config when run from a package-manager session, and
# drops an admin-editable env file for secrets.

set -e

SYSTEM_UNIT_DIR=/usr/lib/systemd/user
ENV_FILE=/etc/default/synthetic-usage-awareness
CONFIG_DIR="$HOME/.config/synthetic-usage-awareness"

install -d -m 0755 "$SYSTEM_UNIT_DIR"
install -m 0644 /usr/share/synthetic-usage-awareness/systemd-user/synthetic-usage-awareness.service "$SYSTEM_UNIT_DIR/"
install -m 0644 /usr/share/synthetic-usage-awareness/systemd-user/synthetic-usage-awareness.timer "$SYSTEM_UNIT_DIR/"

# Admin/root-editable env file (secrets). Never overwrite an existing one.
if [ "$(id -u)" = "0" ] && [ ! -f "$ENV_FILE" ]; then
    install -d -m 0755 /etc/default
    install -m 0600 /usr/share/synthetic-usage-awareness/examples/env.example "$ENV_FILE"
fi

# Seed a user config if the invoking user has a home directory (best effort;
# package managers sometimes run as a system user without one).
if [ -n "${HOME:-}" ] && [ -d "$HOME" ]; then
    install -d -m 0755 "$CONFIG_DIR"
    if [ ! -f "$CONFIG_DIR/config.toml" ]; then
        install -m 0600 /usr/share/synthetic-usage-awareness/examples/config.example.toml "$CONFIG_DIR/config.toml"
    fi
    if [ ! -f "$CONFIG_DIR/env" ]; then
        install -m 0600 /usr/share/synthetic-usage-awareness/examples/env.example "$CONFIG_DIR/env"
    fi
fi

# Reload user unit files for the invoking user if systemd is available.
if command -v systemctl >/dev/null 2>&1; then
    systemctl --user daemon-reload 2>/dev/null || true
fi

exit 0
