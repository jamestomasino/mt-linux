#!/usr/bin/env bash
set -euo pipefail

out="${1:-tests/fixtures/test-tone.wav}"
mkdir -p "$(dirname "$out")"
sox -n -r 16000 -c 1 "$out" synth 1 sine 440
echo "$out"
