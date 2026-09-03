# ============================================================
#  radmin-update.ps1 - finds the latest Radmin VPN version
#  straight from the official page, compares it with the installed one and installs.
#  -CheckOnly : only reports (JSON), does not install.
#  JSON output between <<<UPD>>> and <<<END>>>.
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

# find the latest version + URL by scraping the official page
function DiscoverLatest {
  [System.Net.ServicePointManager]::SecurityProtocol = [System.Net.SecurityProtocolType]::Tls12 -bor [System.Net.SecurityProtocolType]::Tls
  try {
    $html = (New-Object System.Net.WebClient).DownloadString($PAGE)
  } catch { Log "failed to download page: $($_.Exception.Message)"; return $null }
  $mm = [regex]::Matches($html, "Radmin_VPN_([\d\.]+)\.exe")
  if($mm.Count -eq 0){ Log "no version on the page"; return $null }
  # take the HIGHEST version found
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
Log "installed=$cur latest=$lat new=$hasNew"

$installed = $false
$err = ""
if($hasNew -and -not $CheckOnly -and $url){
  $tmp = "C:\radmin-agent\Radmin_update.exe"
  try {
    Log "downloading $url"
    (New-Object System.Net.WebClient).DownloadFile($url, $tmp)
    if(Test-Path $tmp){
      Log "installing silently"
      $p = Start-Process $tmp -ArgumentList "/S" -Wait -PassThru
      $installed = ($p.ExitCode -eq 0)
      Remove-Item $tmp -Force
      Log "installed=$installed exit=$($p.ExitCode)"
    }
  } catch { $err = $_.Exception.Message; Log "install error: $err" }
}

function J($s){ if($null -eq $s){'null'}else{'"'+([string]$s)+'"'} }
Write-Output "<<<UPD>>>"
Write-Output ('{"installed_version":' + (J $cur) + ',"latest_version":' + (J $lat) + ',"download_url":' + (J $url) + ',"has_update":' + $hasNew.ToString().ToLower() + ',"did_install":' + $installed.ToString().ToLower() + ',"error":' + (J $err) + '}')
Write-Output "<<<END>>>"
