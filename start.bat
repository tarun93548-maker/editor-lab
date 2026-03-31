@echo off
echo Starting Editor Lab...

if "%ANTHROPIC_API_KEY%"=="" (
    set /p ANTHROPIC_API_KEY="Paste your Anthropic API key: "
    setx ANTHROPIC_API_KEY "%ANTHROPIC_API_KEY%"
)

if not exist "venv" (
    python -m venv venv
)

call venv\Scripts\activate.bat
pip install -r requirements.txt --quiet

if not exist "uploads" mkdir uploads
if not exist "outputs" mkdir outputs
if not exist "temp" mkdir temp

echo.
echo  Open http://localhost:8000
echo.
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
