@echo off
where pythonw >nul 2>nul && (start "" pythonw "%~dp0sc_copilot.pyw" & exit /b)
where pyw >nul 2>nul && (start "" pyw "%~dp0sc_copilot.pyw" & exit /b)
start "" python "%~dp0sc_copilot.pyw"
