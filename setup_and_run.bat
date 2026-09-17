@echo off
echo =========================================
echo Setting up police Node
echo =========================================
python -m venv venv
call venv\Scripts\activate
pip install -r requirements.txt
echo Starting API Server...
start cmd /k "call venv\Scripts\activate && python -m uvicorn node_api:app --host 0.0.0.0 --port 8000"
echo =========================================
echo Server is running on port 8000!
echo Access the local dashboard at: http://localhost:8000/
echo.
echo Starting secure internet tunnel (Pinggy)...
start cmd /k "ssh -o StrictHostKeyChecking=no -p 443 -R0:127.0.0.1:8000 a.pinggy.io"
echo.
echo =========================================
echo A second black window just opened!
echo Look inside that new window for your public URL (it ends in .pinggy.link).
echo Copy that URL and text it to your Team Leader immediately.
echo (Note: The free tunnel expires after 60 minutes. Just restart this script if it drops).
echo =========================================
pause
