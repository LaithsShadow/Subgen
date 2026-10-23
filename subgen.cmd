@echo off
rem Console mode: subgen.cmd VIDEO_OR_FOLDER... [--source auto/CODE] [--target CODE] [--embedded] [--model M] [--translator T]
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1
set "PYTHONPATH=%~dp0."
"%LOCALAPPDATA%\Subgen\venv\Scripts\python.exe" -m subgen %*
