#!/usr/bin/env bash
# Flow KB, local-only build: no password. Opens on http://127.0.0.1:5001
cd "$(dirname "$0")"
[ -d .venv ] || python3 -m venv .venv
. .venv/bin/activate
pip install -q -r requirements.txt
python main.py
