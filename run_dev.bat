@echo off
REM HDLE Premium - Development Launch Script
REM Launches the application with the development database (hdle_premium.db)

echo Starting HDLE Premium in DEVELOPMENT mode...
echo Database: J:\Project_Vibe\V_book\hdle_premium.db
echo.

python -m app.main --db-path "J:\Project_Vibe\V_book\hdle_premium.db"
