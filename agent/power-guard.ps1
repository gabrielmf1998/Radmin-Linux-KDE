# ============================================================
#  power-guard.ps1 - a VM nunca dorme, hiberna ou reinicia sozinha.
#  Idempotente. Roda no boot e sob demanda.
# ============================================================
$ErrorActionPreference = "SilentlyContinue"
$LOG = "C:\radmin-agent\power.log"
function Log($m){ $ts=Get-Date -Format "HH:mm:ss"; Add-Content $LOG "[$ts] $m"; Write-Output $m }

Log "=== power-guard ==="
# nunca desligar tela / dormir / hibernar (AC e DC)
powercfg -change -monitor-timeout-ac 0
powercfg -change -monitor-timeout-dc 0
powercfg -change -standby-timeout-ac 0
powercfg -change -standby-timeout-dc 0
powercfg -change -hibernate-timeout-ac 0
powercfg -change -hibernate-timeout-dc 0
powercfg -change -disk-timeout-ac 0
powercfg -change -disk-timeout-dc 0
powercfg -h off
# plano de alta performance
$hp = (powercfg -list | Select-String "High performance|Alto desempenho")
if($hp){ $g = ($hp -split "\s+")[3]; powercfg -setactive $g }

# Windows Update: nao baixar/instalar/reiniciar sozinho (evita reboot inesperado)
$au = "HKLM:\SOFTWARE\Policies\Microsoft\Windows\WindowsUpdate\AU"
New-Item -Path $au -Force | Out-Null
Set-ItemProperty $au -Name NoAutoUpdate -Value 1 -Type DWord
Set-ItemProperty $au -Name NoAutoRebootWithLoggedOnUsers -Value 1 -Type DWord

# desabilita screensaver
Set-ItemProperty "HKCU:\Control Panel\Desktop" -Name ScreenSaveActive -Value 0 -EA SilentlyContinue

# botao de energia nao hiberna (caso ACPI)
powercfg -setacvalueindex SCHEME_CURRENT SUB_BUTTONS PBUTTONACTION 3 2>$null

Log "energia travada: sem sleep/hibernate/monitor-off; WU manual"
Log "=== OK ==="
