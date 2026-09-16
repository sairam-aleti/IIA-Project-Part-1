@echo off
echo =========================================
echo Setting up police Node
echo =========================================
python -m venv venv
call venv\Scripts\activate
pip install -r requirements.txt
echo Starting API Server...
start python -m uvicorn node_api:app --host 0.0.0.0 --port 8000
echo =========================================
echo Server is running on port 8000!
echo Access the local dashboard at: http://localhost:8000/
echo.
echo IMPORTANT: To expose this node to the internet, run this command:
echo ssh -p 443 -R0:localhost:8000 a.pinggy.io
echo.
echo Then copy the pinggy URL it gives you and send it to the Mediator.
pause
