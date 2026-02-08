@echo off
echo ================================================
echo Starting HDLE Premium (Development Mode)
echo ================================================
echo.
echo Database: J:\Project_Vibe\V_book\hdle_premium.db
echo Reference Corpus: Hebrew Wikipedia (387k docs)
echo.

cd /d "J:\Project_Vibe\V_book"
call .venv\Scripts\activate.bat

echo [1] Activating virtual environment... OK
echo [2] Starting application...
echo.

python -m app.main --db-path "J:\Project_Vibe\V_book\hdle_premium.db"

set EXIT_CODE=%ERRORLEVEL%
echo.
echo ================================================
echo Application exited with code: %EXIT_CODE%
echo ================================================
echo.

if %EXIT_CODE% == 0 (
    echo [OK] Application closed normally
) else (
    echo [ERROR] Application crashed with error code %EXIT_CODE%
)

echo.
pause
