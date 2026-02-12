#!/bin/bash
cd "$(dirname "$0")"
pip install fastapi uvicorn python-multipart -q 2>/dev/null
python3 app.py
