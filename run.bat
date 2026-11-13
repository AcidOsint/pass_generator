@echo off
cd /d "%~dp0"
where py >nul 2>nul
if %errorlevel%==0 (
    py -3 -m q3pass
) else (
    python -m q3pass
)
