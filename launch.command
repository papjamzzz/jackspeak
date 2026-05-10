#!/bin/bash
cd "$(dirname "$0")"
pkill -f "python3 app.py" 2>/dev/null
python3 -m pip install -q -r requirements.txt
sleep 1
open http://127.0.0.1:5568 &
python3 app.py
