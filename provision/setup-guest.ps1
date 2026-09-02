# ============================================================
#  setup-guest.ps1 - provisionamento do convidado, UMA fase.
#  Rodado como SYSTEM ao FINAL do setup (via SetupComplete.cmd).
#
#  Cada passo foi validado isoladamente:
#   - Radmin instala com /VERYSILENT (Inno Setup; /S NAO funciona) mesmo em
#     sessao 0 (SYSTEM) via Start-Process -Wait.
#   - O ICS NAO e feito aqui: o agente (net-orchestrator) o configura no 1o boot
#     em producao. Isso evita a dependencia do servico de firewall no provisioning.
#
#  Assets em C:\prov\ (Radmin_VPN.exe, agent\*.ps1), copiados pelo SetupComplete.cmd.
#  Log em C:\provision.log
# ============================================================
$ErrorActionPreference = "SilentlyContinue"
$LOG  = "C:\provision.log"
$PROV = "C:\prov"
function Log($m){ $ts=Get-Date -Format "HH:mm:ss"; Add-Content $LOG "[$ts] $m" }

Log "=== provisionamento iniciado ==="

# 1. abre o sistema (UAC off, RDP on, firewall off). NAO desabilita o MpsSvc:
#    o ICS depende dele. Firewall off via netsh mantem o servico rodando.
Set-ItemProperty "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System" -Name EnableLUA -Value 0 -Type DWord
Set-ItemProperty "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System" -Name LocalAccountTokenFilterPolicy -Value 1 -Type DWord
Set-ItemProperty "HKLM:\SYSTEM\CurrentControlSet\Control\Terminal Server" -Name fDenyTSConnections -Value 0 -Type DWord
Set-Service RemoteRegistry -StartupType Automatic; Start-Service RemoteRegistry
netsh advfirewall set allprofiles state off
Log "1. sistema aberto (UAC off, RDP on, firewall off; MpsSvc mantido)"

# 2. Radmin VPN silencioso (/VERYSILENT - Inno Setup)
$rad = "$PROV\Radmin_VPN.exe"
if (Test-Path $rad) {
  Log "2. instalando Radmin VPN (/VERYSILENT)"
  $p = Start-Process $rad -ArgumentList "/VERYSILENT","/SUPPRESSMSGBOXES","/NORESTART" -Wait -PassThru
  for ($i=0; $i -lt 30; $i++) {
    if (Test-Path "C:\Program Files (x86)\Radmin VPN\RvControlSvc.exe") { break }
    Start-Sleep 2
  }
  Start-Service RvControlSvc
  $ok = Test-Path "C:\Program Files (x86)\Radmin VPN\RvControlSvc.exe"
  Log "   exit=$($p.ExitCode) instalado=$ok svc=$((Get-Service RvControlSvc).Status)"
} else { Log "2. ERRO: $rad ausente" }

# 3. agente (tarefas de boot: power/net/health/update). O net-orchestrator
#    configura o ICS no 1o boot em producao.
New-Item -ItemType Directory -Path "C:\radmin-agent" -Force | Out-Null
Copy-Item "$PROV\agent\*.ps1" "C:\radmin-agent\" -Force
& powershell -ExecutionPolicy Bypass -File "C:\radmin-agent\agent-install.ps1" | Out-Null
& powershell -ExecutionPolicy Bypass -File "C:\radmin-agent\power-guard.ps1" | Out-Null
$ntasks = (schtasks /query 2>$null | Select-String RadminAgent).Count
Log "3. agente instalado ($ntasks tarefas)"

# 4. identidade limpa p/ distribuicao (sem rede associada)
Set-ItemProperty "HKLM:\SOFTWARE\Wow6432Node\Famatech\RadminVPN\1.0" -Name Alias -Value "RADMIN-LINUX" -Type String

Log "=== provisionamento CONCLUIDO ==="
"DONE" | Out-File C:\provision-done.txt -Encoding ASCII
Start-Sleep 3
shutdown /s /t 3 /f
