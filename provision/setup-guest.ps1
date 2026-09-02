# ============================================================
#  setup-guest.ps1 - provisionamento do convidado, em 2 fases.
#
#  -Phase system : roda como SYSTEM ao FINAL do setup (via SetupComplete.cmd).
#     abre o sistema (UAC/RDP/firewall), instala o agente, e agenda a fase 'user'
#     no primeiro logon (RunOnce), onde ha sessao interativa.
#  -Phase user   : roda no 1o logon do bench (sessao interativa). Instala o Radmin
#     (o installer NSIS TRAVA sem sessao interativa), configura o ICS e desliga.
#
#  Assets esperados em C:\prov\  (Radmin_VPN.exe, agent\*.ps1) — copiados pelo
#  SetupComplete.cmd a partir da midia de provisao.
#  Log em C:\provision.log
# ============================================================
param([ValidateSet("system","user")] [string]$Phase = "system")
$ErrorActionPreference = "SilentlyContinue"
$LOG  = "C:\provision.log"
$PROV = "C:\prov"
function Log($m){ $ts=Get-Date -Format "HH:mm:ss"; Add-Content $LOG "[$ts] ($Phase) $m" }

if ($Phase -eq "system") {
  Log "=== fase system iniciada ==="
  # 1. abre o sistema
  Set-ItemProperty "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System" -Name EnableLUA -Value 0 -Type DWord
  Set-ItemProperty "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System" -Name LocalAccountTokenFilterPolicy -Value 1 -Type DWord
  Set-ItemProperty "HKLM:\SYSTEM\CurrentControlSet\Control\Terminal Server" -Name fDenyTSConnections -Value 0 -Type DWord
  Set-Service RemoteRegistry -StartupType Automatic; Start-Service RemoteRegistry
  Set-Service MpsSvc -StartupType Disabled 2>$null
  netsh advfirewall set allprofiles state off
  Log "sistema aberto (UAC off, RDP on, firewall off)"

  # 2. instala o agente (tarefas de boot: power/net/health/update)
  New-Item -ItemType Directory -Path "C:\radmin-agent" -Force | Out-Null
  Copy-Item "$PROV\agent\*.ps1" "C:\radmin-agent\" -Force
  & powershell -ExecutionPolicy Bypass -File "C:\radmin-agent\agent-install.ps1" | Out-Null
  & powershell -ExecutionPolicy Bypass -File "C:\radmin-agent\power-guard.ps1" | Out-Null
  Log "agente instalado"

  # 3. agenda a fase 'user' no proximo logon (sessao interativa p/ o Radmin)
  $ro = "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\RunOnce"
  New-ItemProperty $ro -Name "RadminProvision" -PropertyType String -Force `
    -Value "powershell -ExecutionPolicy Bypass -WindowStyle Hidden -File C:\prov\setup-guest.ps1 -Phase user" | Out-Null
  Log "fase user agendada (RunOnce). Fim da fase system."
  exit
}

# ---------------- fase user (sessao interativa) ----------------
Log "=== fase user iniciada ==="
$rad = "$PROV\Radmin_VPN.exe"
if (Test-Path $rad) {
  if (-not (Test-Path "C:\Program Files (x86)\Radmin VPN\RvControlSvc.exe")) {
    Log "instalando Radmin VPN (sessao interativa)"
    $p = Start-Process $rad -ArgumentList "/S" -Wait -PassThru
    Log "installer exit=$($p.ExitCode)"
  }
  for ($i=0; $i -lt 30; $i++) {
    if (Get-WmiObject Win32_NetworkAdapter | Where-Object {$_.Description -match "Radmin"}) { break }
    Start-Sleep 2
  }
  Start-Service RvControlSvc
  Log "Radmin instalado=$((Test-Path 'C:\Program Files (x86)\Radmin VPN\RvControlSvc.exe')) svc=$((Get-Service RvControlSvc).Status)"
} else { Log "ERRO: $rad ausente" }

# ICS: placa Radmin = publica, placa isolada (MAC ...26:00:02) = privada
$radNic = Get-WmiObject Win32_NetworkAdapter | Where-Object {$_.NetConnectionID -and $_.Description -match "Radmin"} | Select-Object -First 1
$isoNic = Get-WmiObject Win32_NetworkAdapter | Where-Object {$_.MACAddress -and $_.MACAddress.Replace(":","").ToUpper() -eq "525400260002"} | Select-Object -First 1
if ($radNic -and $isoNic) {
  $share = New-Object -ComObject HNetCfg.HNetShare
  foreach ($c in $share.EnumEveryConnection) { $cfg=$share.INetSharingConfigurationForINetConnection($c); if ($cfg.SharingEnabled) { $cfg.DisableSharing() } }
  Start-Sleep 2
  foreach ($c in $share.EnumEveryConnection) { if ($share.NetConnectionProps($c).Name -eq $radNic.NetConnectionID) { $share.INetSharingConfigurationForINetConnection($c).EnableSharing(0) } }
  Start-Sleep 2
  foreach ($c in $share.EnumEveryConnection) { if ($share.NetConnectionProps($c).Name -eq $isoNic.NetConnectionID) { $share.INetSharingConfigurationForINetConnection($c).EnableSharing(1) } }
  Log "ICS aplicado (rad=$($radNic.NetConnectionID) iso=$($isoNic.NetConnectionID))"
} else { Log "ERRO ICS: placas rad=$($radNic.NetConnectionID) iso=$($isoNic.NetConnectionID)" }

# identidade limpa p/ distribuicao (sem rede associada)
Set-ItemProperty "HKLM:\SOFTWARE\Wow6432Node\Famatech\RadminVPN\1.0" -Name Alias -Value "RADMIN-LINUX" -Type String
Log "=== provisionamento CONCLUIDO ==="
"DONE" | Out-File C:\provision-done.txt -Encoding ASCII
Start-Sleep 3
shutdown /s /t 3 /f
