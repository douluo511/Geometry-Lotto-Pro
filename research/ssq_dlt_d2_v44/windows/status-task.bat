@echo off
rem Run from an existing console. Paths are explicit; no working-directory guess.
rem Default: XML export only. Append -Install only after reviewing the XML.
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoLogo -NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File "%~dp0Install-StatusTask.ps1" %*
exit /b %ERRORLEVEL%
