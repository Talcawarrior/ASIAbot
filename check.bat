@echo off
REM One-command safety net (Windows). Equivalent of `make check`.
REM Runs lint + format + types + full test suite.

echo [1/4] ruff lint --fix
ruff check . --fix
if errorlevel 1 exit /b 1

echo [2/4] ruff format
ruff format .
if errorlevel 1 exit /b 1

echo [3/4] mypy
mypy --config-file=mypy.ini --exclude=scripts/ .
if errorlevel 1 exit /b 1

echo [4/4] pytest
pytest -q
if errorlevel 1 exit /b 1

echo =========================================
echo  check: ALL GREEN - safe to commit
echo =========================================
