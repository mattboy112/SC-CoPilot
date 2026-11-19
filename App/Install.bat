@echo off
cd /d "%~dp0"
echo Installing the packages for SC Co-Pilot...
echo (numpy, sounddevice, faster-whisper, edge-tts, zstandard, kokoro-onnx, soundfile, pillow)
echo.
where python >nul 2>nul || (echo Python wasn't found. Install Python 3.12 from the Microsoft Store, then run this again. & pause & exit /b 1)
python -m pip install --user -r requirements.txt
if errorlevel 1 (echo. & echo Something went wrong above. Copy the error into a GitHub issue: https://github.com/mattboy112/SC-CoPilot/issues & pause & exit /b 1)
echo.
echo All set. Start the app with "Start SC Co-Pilot.bat".
echo For the Kokoro voices, open Settings in the app and hit "Download Kokoro voices".
pause
