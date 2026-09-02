# ============================================================
#  radmin-update.ps1 - descobre a ultima versao do Radmin VPN
#  direto da pagina oficial, compara com a instalada e instala.
#  -CheckOnly : so reporta (JSON), nao instala.
#  Saida JSON entre <<<UPD>>> e <<<END>>>.
# ============================================================
param([switch]$CheckOnly)
$ErrorActionPreference = "SilentlyContinue"
$LOG = "C:\radmin-agent\update.log"
$PAGE = "https://www.radmin-vpn.com/"
function Log($m){ $ts=Get-Date -Format "HH:mm:ss"; Add-Content $LOG "[$ts] $m" }

function InstalledVer {
  $exe = "C:\Program Files (x86)\Radmin VPN\RvRvpnGui.exe"
  if(Test-Path $exe){ return (Get-Item $exe).VersionInfo.ProductVersion }
  return $null
}

# descobre a ultima versao + URL raspando a pagina oficial
function DiscoverLatest {
  [System.Net.ServicePointManager]::SecurityProtocol = [System.Net.SecurityProtocolType]::Tls12 -bor [System.Net.SecurityProtocolType]::Tls
  try {
    $html = (New-Object System.Net.WebClient).DownloadString($PAGE)
  } catch { Log "falha ao baixar pagina: $($_.Exception.Message)"; return $null }
  $mm = [regex]::Matches($html, "Radmin_VPN_([\d\.]+)\.exe")
  if($mm.Count -eq 0){ Log "nenhuma versao na pagina"; return $null }
  # pega a MAIOR versao encontrada
  $best = $null
  foreach($x in $mm){
    try { $v=[version]$x.Groups[1].Value } catch { continue }
    if(-not $best -or $v -gt $best){ $best = $v }
  }
  $verStr = $best.ToString()
  $url = [regex]::Match($html, "https?://[^""']*Radmin_VPN_" + [regex]::Escape($verStr) + "\.exe")
  $u = if($url.Success){ $url.Value } else { "https://download.radmin-vpn.com/download/files/Radmin_VPN_$verStr.exe" }
  return @{ ver = $verStr; url = $u }
}

$cur = InstalledVer
$latest = DiscoverLatest
$lat = if($latest){ $latest.ver } else { $null }
$url = if($latest){ $latest.url } else { $null }

$hasNew = $false
if($cur -and $lat){
  try { $hasNew = ([version]$lat -gt [version]$cur) } catch { $hasNew = ($cur -ne $lat) }
}
Log "instalada=$cur latest=$lat nova=$hasNew"

$installed = $false
$err = ""
if($hasNew -and -not $CheckOnly -and $url){
  $tmp = "C:\radmin-agent\Radmin_update.exe"
  try {
    Log "baixando $url"
    (New-Object System.Net.WebClient).DownloadFile($url, $tmp)
    if(Test-Path $tmp){
      Log "instalando silencioso"
      $p = Start-Process $tmp -ArgumentList "/S" -Wait -PassThru
      $installed = ($p.ExitCode -eq 0)
      Remove-Item $tmp -Force
      Log "instalado=$installed exit=$($p.ExitCode)"
    }
  } catch { $err = $_.Exception.Message; Log "erro instalacao: $err" }
}

function J($s){ if($null -eq $s){'null'}else{'"'+([string]$s)+'"'} }
Write-Output "<<<UPD>>>"
Write-Output ('{"installed_version":' + (J $cur) + ',"latest_version":' + (J $lat) + ',"download_url":' + (J $url) + ',"has_update":' + $hasNew.ToString().ToLower() + ',"did_install":' + $installed.ToString().ToLower() + ',"error":' + (J $err) + '}')
Write-Output "<<<END>>>"
