# ============================================================
#  net-orchestrator.ps1  -  garante a conectividade Radmin<->Linux
#  Roda no boot da VM e sob demanda. Resolve o deadlock de ordem:
#   1. estado limpo (remove ICS de tudo)
#   2. espera o Radmin conectar de fato (RvControlSvc Running + IP 26.x)
#   3. aplica ICS: placa Radmin = publica, placa isolada = privada
#   4. confere 192.168.137.1 na placa isolada
#  Idempotente. Log em C:\radmin-agent\net.log
# ============================================================
param([int]$WaitSec = 120)
$ErrorActionPreference = "SilentlyContinue"
$ISO_MAC = "525400260002"   # placa isolada (ligada a tapradmin do Linux)
$LOG = "C:\radmin-agent\net.log"

function Log($m){ $ts=Get-Date -Format "HH:mm:ss"; Add-Content $LOG "[$ts] $m"; Write-Output $m }

function RadminNic {
  Get-WmiObject Win32_NetworkAdapter | Where-Object { $_.NetConnectionID -and $_.Description -match "Radmin" } | Select-Object -First 1
}
function IsoNic {
  Get-WmiObject Win32_NetworkAdapter | Where-Object { $_.MACAddress -and $_.MACAddress.Replace(":","").ToUpper() -eq $ISO_MAC } | Select-Object -First 1
}
function RadminIp {
  $n = RadminNic
  if(-not $n){ return $null }
  $c = Get-WmiObject Win32_NetworkAdapterConfiguration -Filter "Index=$($n.Index)"
  ($c.IPAddress | Where-Object { $_ -like "26.*" } | Select-Object -First 1)
}

Log "=== orquestrador iniciando ==="

# 1. espera o Radmin conectar (servico + IP na mesh)
$deadline = (Get-Date).AddSeconds($WaitSec)
$connected = $false
while((Get-Date) -lt $deadline){
  $svc = (Get-Service RvControlSvc).Status
  $ip  = RadminIp
  if($svc -eq "Running" -and $ip){ $connected = $true; Log "Radmin conectado: $ip"; break }
  Start-Sleep 3
}
if(-not $connected){
  # forca o servico a subir e tenta de novo curto
  Log "Radmin nao conectou; iniciando servico"
  Start-Service RvControlSvc
  Start-Sleep 8
  if(-not (RadminIp)){ Log "ERRO: sem IP Radmin apos espera"; exit 1 }
}

$rad = RadminNic
$iso = IsoNic
if(-not $rad){ Log "ERRO: placa Radmin nao encontrada"; exit 1 }
if(-not $iso){ Log "ERRO: placa isolada (MAC $ISO_MAC) nao encontrada"; exit 1 }
Log "placas: radmin='$($rad.NetConnectionID)' isolada='$($iso.NetConnectionID)'"

# 2. estado atual do ICS
$share = New-Object -ComObject HNetCfg.HNetShare
function CfgFor($name){
  foreach($c in $share.EnumEveryConnection){
    if($share.NetConnectionProps($c).Name -eq $name){ return $share.INetSharingConfigurationForINetConnection($c) }
  }
  return $null
}
$radCfg = CfgFor $rad.NetConnectionID
$isoCfg = CfgFor $iso.NetConnectionID

$radPub = ($radCfg.SharingEnabled -and $radCfg.SharingConnectionType -eq 0)
$isoPriv = ($isoCfg.SharingEnabled -and $isoCfg.SharingConnectionType -eq 1)

if($radPub -and $isoPriv){
  Log "ICS ja correto (Radmin=publica, isolada=privada)"
} else {
  Log "reaplicando ICS"
  # limpa qualquer compartilhamento antes
  foreach($c in $share.EnumEveryConnection){
    $cfg=$share.INetSharingConfigurationForINetConnection($c)
    if($cfg.SharingEnabled){ $cfg.DisableSharing() }
  }
  Start-Sleep 2
  (CfgFor $rad.NetConnectionID).EnableSharing(0)   # publica
  Start-Sleep 2
  (CfgFor $iso.NetConnectionID).EnableSharing(1)   # privada
  Start-Sleep 3
  Log "ICS aplicado"
}

# 3. confirma IP da placa isolada (ICS forca 192.168.137.1)
$isoCfgW = Get-WmiObject Win32_NetworkAdapterConfiguration -Filter "Index=$($iso.Index)"
$isoIp = $isoCfgW.IPAddress | Where-Object { $_ -like "192.168.137.*" }
Log "IP placa isolada: $isoIp"
if($isoIp){ Log "=== OK: conectividade pronta ===" } else { Log "AVISO: placa isolada sem IP 192.168.137.x" }
