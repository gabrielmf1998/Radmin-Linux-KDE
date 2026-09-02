@echo off
REM Executado automaticamente pelo Windows ao final do setup, como SYSTEM.
REM Dispara a fase 'system' do provisionamento (que agenda a fase 'user').
powershell -ExecutionPolicy Bypass -WindowStyle Hidden -File C:\prov\setup-guest.ps1 -Phase system
