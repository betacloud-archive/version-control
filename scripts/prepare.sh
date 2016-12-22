#!/usr/bin/env bash
set -x

virtualenv venv
source venv/bin/activate
pip install -r requirements.txt
