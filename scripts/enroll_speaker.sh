#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 2 ]]; then
  echo "usage: $0 <name> <audio.wav>" >&2
  exit 1
fi

mt-ctl enroll "$1" "$2"
