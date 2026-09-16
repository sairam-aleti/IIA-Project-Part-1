#!/bin/bash
echo "Setting up insurance Node"
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
echo "Starting API Server on port 8000..."
python3 -m uvicorn node_api:app --host 0.0.0.0 --port 8000 &
echo "Server is running!"
echo "To expose to internet, run: ssh -p 443 -R0:localhost:8000 a.pinggy.io"
