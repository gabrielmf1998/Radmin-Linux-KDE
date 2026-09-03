# ============================================================
#  setup-guest.ps1 - guest provisioning, ONE phase.
#  Run as SYSTEM at the END of setup (via SetupComplete.cmd).
#
#  Each step was validated in isolation:
#   - Radmin installs with /VERYSILENT (Inno Setup; /S does NOT work) even in
#     session 0 (SYSTEM) via Start-Process -Wait.
#   - ICS is NOT done here: the agent (net-orchestrator) configures it on the 1st boot
#     in production. This avoids depending on the firewall service during provisioning.
#
#  Assets in C:\prov\ (Radmin_VPN.exe, agent\*.ps1), copied by SetupComplete.cmd.
#  Log in C:\provision.log
# ============================================================
$ErrorActionPreference = "SilentlyContinue"
$LOG  = "C:\provision.log"
$PROV = "C:\prov"
function Log($m){ $ts=Get-Date -Format "HH:mm:ss"; Add-Content $LOG "[$ts] $m" }

Log "=== provisioning started ==="

# 1. open up the system (UAC off, RDP on, firewall off). Do NOT disable MpsSvc:
#    ICS depends on it. Firewall off via netsh keeps the service running.
Set-ItemProperty "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System" -Name EnableLUA -Value 0 -Type DWord
Set-ItemProperty "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System" -Name LocalAccountTokenFilterPolicy -Value 1 -Type DWord
Set-ItemProperty "HKLM:\SYSTEM\CurrentControlSet\Control\Terminal Server" -Name fDenyTSConnections -Value 0 -Type DWord
Set-Service RemoteRegistry -StartupType Automatic; Start-Service RemoteRegistry
netsh advfirewall set allprofiles state off
Log "1. system opened (UAC off, RDP on, firewall off; MpsSvc kept)"

# 2. silent Radmin VPN (/VERYSILENT - Inno Setup)
$rad = "$PROV\Radmin_VPN.exe"
if (Test-Path $rad) {
  Log "2. installing Radmin VPN (/VERYSILENT)"
  $p = Start-Process $rad -ArgumentList "/VERYSILENT","/SUPPRESSMSGBOXES","/NORESTART" -Wait -PassThru
  for ($i=0; $i -lt 30; $i++) {
    if (Test-Path "C:\Program Files (x86)\Radmin VPN\RvControlSvc.exe") { break }
    Start-Sleep 2
  }
  Start-Service RvControlSvc
  $ok = Test-Path "C:\Program Files (x86)\Radmin VPN\RvControlSvc.exe"
  Log "   exit=$($p.ExitCode) installed=$ok svc=$((Get-Service RvControlSvc).Status)"
} else { Log "2. ERROR: $rad missing" }

# 3. agent (boot tasks: power/net/health/update). net-orchestrator
#    configures ICS on the 1st boot in production.
New-Item -ItemType Directory -Path "C:\radmin-agent" -Force | Out-Null
Copy-Item "$PROV\agent\*.ps1" "C:\radmin-agent\" -Force
& powershell -ExecutionPolicy Bypass -File "C:\radmin-agent\agent-install.ps1" | Out-Null
& powershell -ExecutionPolicy Bypass -File "C:\radmin-agent\power-guard.ps1" | Out-Null
$ntasks = (schtasks /query 2>$null | Select-String RadminAgent).Count
Log "3. agent installed ($ntasks tasks)"

# 4. clean identity for distribution (no associated network)
Set-ItemProperty "HKLM:\SOFTWARE\Wow6432Node\Famatech\RadminVPN\1.0" -Name Alias -Value "RADMIN-LINUX" -Type String

Log "=== provisioning DONE ==="
"DONE" | Out-File C:\provision-done.txt -Encoding ASCII
Start-Sleep 3
shutdown /s /t 3 /f
