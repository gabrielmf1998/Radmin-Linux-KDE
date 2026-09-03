# ============================================================
#  agent-install.ps1 - installs the Radmin-Linux agent in the VM.
#  Creates C:\radmin-agent, registers scheduled tasks at boot:
#   - power-guard   (on power-on)
#   - net-orchestrator (on power-on, after network)
#  Runs as SYSTEM at boot -> resolves the deadlock without intervention.
# ============================================================
$ErrorActionPreference = "SilentlyContinue"
$dir = "C:\radmin-agent"
New-Item -ItemType Directory -Path $dir -Force | Out-Null

# task: power-guard on power-on (SYSTEM)
schtasks /create /tn "RadminAgent-Power" /tr "powershell -ExecutionPolicy Bypass -WindowStyle Hidden -File $dir\power-guard.ps1" /sc onstart /ru SYSTEM /rl HIGHEST /f | Out-Null

# task: network orchestrator on power-on (SYSTEM), delayed for the network to come up
schtasks /create /tn "RadminAgent-Net" /tr "powershell -ExecutionPolicy Bypass -WindowStyle Hidden -File $dir\net-orchestrator.ps1" /sc onstart /delay 0000:30 /ru SYSTEM /rl HIGHEST /f | Out-Null

# task: orchestrator also at the bench logon (redundancy, in case ICS needs the session)
schtasks /create /tn "RadminAgent-Net-Logon" /tr "powershell -ExecutionPolicy Bypass -WindowStyle Hidden -File $dir\net-orchestrator.ps1" /sc onlogon /ru bench /rp bench /it /f | Out-Null

# task: health + auto-heal every 5 min (redundancy in case the UI is closed)
schtasks /create /tn "RadminAgent-Health" /tr "powershell -ExecutionPolicy Bypass -WindowStyle Hidden -File $dir\health.ps1 -Heal" /sc minute /mo 5 /ru SYSTEM /rl HIGHEST /f | Out-Null

Write-Output "<<<AGENTOK>>>"
schtasks /query /tn "RadminAgent-Power" /fo LIST 2>&1 | Select-String "TaskName|Status" | Out-String
schtasks /query /tn "RadminAgent-Net" /fo LIST 2>&1 | Select-String "TaskName|Status" | Out-String
