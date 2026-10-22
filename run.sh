#!/usr/bin/env bash
# Bramble on this PC (development copy): bash run.sh
cd "$(dirname "$(readlink -f "$0")")" || exit 1
[ -x .venv/bin/python ] || { python3 -m venv .venv && .venv/bin/pip install -q PyQt6; }
exec .venv/bin/python -m bramble "$@"
