# ============================================================
#  setup-guest.ps1 - provisionamento do convidado no 1o logon.
#  Chamado pelo autounattend (FirstLogonCommands). Faz TUDO:
#   1. abre o sistema (UAC off, RDP on, firewall off, RemoteRegistry)
#   2. instala o Radmin VPN silencioso (da mesma midia, D:)
#   3. configura o ICS (Radmin=publica, placa isolada=privada)
#   4. instala o agente (C:\radmin-agent + tarefas no boot)
#   NAO entra em rede nenhuma - a imagem fica limpa.
#  Log em C:\provision.log
# ============================================================
$ErrorActionPreference = "SilentlyContinue"
$LOG = "C:\provision.log"
function Log($m){ $ts=Get-Date -Format "HH:mm:ss"; Add-Content $LOG "[$ts] $m" }
$MEDIA = $PSScriptRoot   # a midia onde este script esta (D:\)

Log "=== provisionamento iniciado (midia=$MEDIA) ==="

# --- 1. abre o sistema (o que fazia offline via reged) ---
Log "1. abrindo o sistema (UAC/RDP/firewall)"
$sys = "HKLM:\SYSTEM\CurrentControlSet"
Set-ItemProperty "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System" -Name EnableLUA -Value 0 -Type DWord
Set-ItemProperty "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System" -Name LocalAccountTokenFilterPolicy -Value 1 -Type DWord
Set-ItemProperty "$sys\Control\Terminal Server" -Name fDenyTSConnections -Value 0 -Type DWord
Set-ItemProperty "$sys\Control\Terminal Server\WinStations\RDP-Tcp" -Name UserAuthentication -Value 0 -Type DWord
Set-Service RemoteRegistry -StartupType Automatic; Start-Service RemoteRegistry
netsh advfirewall set allprofiles state off
Log "   sistema aberto"

# --- 2. Radmin VPN silencioso ---
$rad = Join-Path $MEDIA "Radmin_VPN.exe"
if(Test-Path $rad){
  Log "2. instalando Radmin VPN ($rad)"
  # o instalador do Radmin (NSIS) TRAVA em sessao 0 headless: precisa de sessao
  # interativa. Rodamos via tarefa agendada no usuario logado (sessao 1) com /S.
  $already = Test-Path "C:\Program Files (x86)\Radmin VPN\RvControlSvc.exe"
  if(-not $already){
    schtasks /create /tn RvInstall /tr "`"$rad`" /S" /sc once /st 00:00 /ru bench /rp bench /it /f | Out-Null
    schtasks /run /tn RvInstall | Out-Null
    Log "   instalador disparado na sessao interativa; aguardando..."
    for($i=0;$i -lt 90;$i++){
      if(Test-Path "C:\Program Files (x86)\Radmin VPN\RvControlSvc.exe"){ break }
      Start-Sleep 4
    }
    schtasks /delete /tn RvInstall /f 2>$null | Out-Null
  }
  # espera a placa Radmin aparecer
  for($i=0;$i -lt 30;$i++){
    if(Get-WmiObject Win32_NetworkAdapter | Where-Object {$_.Description -match "Radmin"}){ break }
    Start-Sleep 2
  }
  Start-Service RvControlSvc
  Log "   instalado=$((Test-Path 'C:\Program Files (x86)\Radmin VPN\RvControlSvc.exe')) servico=$((Get-Service RvControlSvc).Status)"
} else { Log "2. ERRO: Radmin_VPN.exe nao esta na midia" }

# --- 3. ICS (Radmin=publica, placa isolada 52:54:00:26:00:02=privada) ---
Log "3. configurando ICS"
$radNic = Get-WmiObject Win32_NetworkAdapter | Where-Object {$_.NetConnectionID -and $_.Description -match "Radmin"} | Select-Object -First 1
$isoNic = Get-WmiObject Win32_NetworkAdapter | Where-Object {$_.MACAddress -and $_.MACAddress.Replace(":","").ToUpper() -eq "525400260002"} | Select-Object -First 1
if($radNic -and $isoNic){
  $share = New-Object -ComObject HNetCfg.HNetShare
  foreach($c in $share.EnumEveryConnection){ $cfg=$share.INetSharingConfigurationForINetConnection($c); if($cfg.SharingEnabled){$cfg.DisableSharing()} }
  Start-Sleep 2
  foreach($c in $share.EnumEveryConnection){ $p=$share.NetConnectionProps($c); if($p.Name -eq $radNic.NetConnectionID){ $share.INetSharingConfigurationForINetConnection($c).EnableSharing(0) } }
  Start-Sleep 2
  foreach($c in $share.EnumEveryConnection){ $p=$share.NetConnectionProps($c); if($p.Name -eq $isoNic.NetConnectionID){ $share.INetSharingConfigurationForINetConnection($c).EnableSharing(1) } }
  Log "   ICS: Radmin=$($radNic.NetConnectionID) publica, isolada=$($isoNic.NetConnectionID) privada"
} else { Log "   ERRO: placas nao encontradas (rad=$($radNic.NetConnectionID) iso=$($isoNic.NetConnectionID))" }

# --- 4. agente ---
Log "4. instalando o agente"
New-Item -ItemType Directory -Path "C:\radmin-agent" -Force | Out-Null
Copy-Item (Join-Path $MEDIA "agent\*.ps1") "C:\radmin-agent\" -Force
& powershell -ExecutionPolicy Bypass -File "C:\radmin-agent\agent-install.ps1" | Out-Null
& powershell -ExecutionPolicy Bypass -File "C:\radmin-agent\power-guard.ps1" | Out-Null
Log "   agente instalado; tarefas: $((schtasks /query 2>$null | Select-String RadminAgent).Count)"

# --- limpeza da identidade (imagem base limpa) ---
Set-ItemProperty "HKLM:\SOFTWARE\Wow6432Node\Famatech\RadminVPN\1.0" -Name Alias -Value "RADMIN-LINUX" -Type String
Log "=== provisionamento CONCLUIDO ==="
"DONE" | Out-File C:\provision-done.txt -Encoding ASCII
# desliga a VM: o host detecta o processo QEMU morrer = build terminou
Start-Sleep 3
shutdown /s /t 3 /f
