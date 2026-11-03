@echo off
REM Runs coffin_cavity_hfss.py with the .AnE environment and logs everything.
cd /d "%~dp0"
set MPLBACKEND=Agg
echo [run] started %DATE% %TIME% > coffin_cavity_hfss_run.log
"C:\Users\epm114\.AnE\Scripts\python.exe" -u coffin_cavity_hfss.py >> coffin_cavity_hfss_run.log 2>&1
echo [run] exit code %ERRORLEVEL% at %DATE% %TIME% >> coffin_cavity_hfss_run.log
