# ============================================================
#  power-guard.ps1 - the VM never sleeps, hibernates or reboots by itself.
#  Idempotent. Runs at boot and on demand.
# ============================================================
$ErrorActionPreference = "SilentlyContinue"
$LOG = "C:\radmin-agent\power.log"
function Log($m){ $ts=Get-Date -Format "HH:mm:ss"; Add-Content $LOG "[$ts] $m"; Write-Output $m }

Log "=== power-guard ==="
# never turn off the screen / sleep / hibernate (AC and DC)
powercfg -change -monitor-timeout-ac 0
powercfg -change -monitor-timeout-dc 0
powercfg -change -standby-timeout-ac 0
powercfg -change -standby-timeout-dc 0
powercfg -change -hibernate-timeout-ac 0
powercfg -change -hibernate-timeout-dc 0
powercfg -change -disk-timeout-ac 0
powercfg -change -disk-timeout-dc 0
powercfg -h off
# high performance plan
$hp = (powercfg -list | Select-String "High performance|Alto desempenho")
if($hp){ $g = ($hp -split "\s+")[3]; powercfg -setactive $g }

# Windows Update: do not download/install/reboot by itself (avoids an unexpected reboot)
$au = "HKLM:\SOFTWARE\Policies\Microsoft\Windows\WindowsUpdate\AU"
New-Item -Path $au -Force | Out-Null
Set-ItemProperty $au -Name NoAutoUpdate -Value 1 -Type DWord
Set-ItemProperty $au -Name NoAutoRebootWithLoggedOnUsers -Value 1 -Type DWord

# disable the screensaver
Set-ItemProperty "HKCU:\Control Panel\Desktop" -Name ScreenSaveActive -Value 0 -EA SilentlyContinue

# power button does not hibernate (in case of ACPI)
powercfg -setacvalueindex SCHEME_CURRENT SUB_BUTTONS PBUTTONACTION 3 2>$null

Log "power locked: no sleep/hibernate/monitor-off; WU manual"
Log "=== OK ==="
