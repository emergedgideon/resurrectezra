#!/usr/bin/env bash
set -eu
python -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
