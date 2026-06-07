#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if command -v pipx >/dev/null 2>&1; then
  pipx install --force --editable "${repo_root}"
else
  cat >&2 <<'EOF'
pipx is required for the default install flow on externally-managed Python systems.
Install pipx, or create a virtualenv and run:

  python3 -m pip install -e .
EOF
  exit 1
fi
mkdir -p "${HOME}/.config/mt-linux" "${HOME}/.local/share/mt-linux" "${HOME}/.local/state/mt-linux"
mkdir -p "${HOME}/.config/systemd/user"
cp "${repo_root}/systemd/mt-linux.service" "${HOME}/.config/systemd/user/mt-linux.service"
systemctl --user daemon-reload || true
mt-ctl bootstrap-config

cat <<'EOF'
mt-linux installed.

Recommended next steps:
  1. mt-ctl doctor
  2. mt-ctl config set speakers.mic_speaker_name "Your Name"
  3. mt-ctl auth google           # or configure CalDAV in ~/.config/mt-linux/config.toml
  4. systemctl --user enable --now mt-linux.service
EOF

mt-ctl doctor || true
