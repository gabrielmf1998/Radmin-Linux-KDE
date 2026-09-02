# ============================================================
#  radmin-update.ps1 - checa/instala update do Radmin VPN.
#  -CheckOnly : so reporta se ha versao nova (JSON), nao instala.
#  Sem flag   : baixa e instala silencioso se houver nova.
#  Saida JSON entre <<<UPD>>> e <<<END>>>.
# ============================================================
param([switch]$CheckOnly)
$ErrorActionPreference = "SilentlyContinue"
$LOG = "C:\radmin-agent\update.log"
$URL = "https://download.radmin-vpn.com/download/files/Radmin_VPN_2.0.4899.9.exe"
function Log($m){ $ts=Get-Date -Format "HH:mm:ss"; Add-Content $LOG "[$ts] $m"; }

function InstalledVer {
  $exe = "C:\Program Files (x86)\Radmin VPN\RvRvpnGui.exe"
  if(Test-Path $exe){ return (Get-Item $exe).VersionInfo.ProductVersion }
  return $null
}

# a versao "mais nova conhecida" vem do nome do arquivo no servidor.
# como o site publica sempre o mesmo nome versionado, extraimos do URL.
function LatestVer {
  if($URL -match "Radmin_VPN_([\d\.]+)\.exe"){ return $matches[1] }
  return $null
}

$cur = InstalledVer
$lat = LatestVer
$hasNew = $false
if($cur -and $lat){
  try { $hasNew = ([version]$lat -gt [version]$cur) } catch { $hasNew = ($cur -ne $lat) }
}
Log "instalada=$cur latest=$lat nova=$hasNew"

$installed = $false
if($hasNew -and -not $CheckOnly){
  $tmp = "C:\radmin-agent\Radmin_update.exe"
  Log "baixando $URL"
  (New-Object System.Net.WebClient).DownloadFile($URL, $tmp)
  if(Test-Path $tmp){
    Log "instalando silencioso"
    $p = Start-Process $tmp -ArgumentList "/S" -Wait -PassThru
    $installed = ($p.ExitCode -eq 0)
    Remove-Item $tmp -Force
    Log "instalado=$installed exit=$($p.ExitCode)"
  }
}

Write-Output "<<<UPD>>>"
Write-Output ('{"installed_version":"' + $cur + '","latest_version":"' + $lat + '","has_update":' + $hasNew.ToString().ToLower() + ',"did_install":' + $installed.ToString().ToLower() + '}')
Write-Output "<<<END>>>"
