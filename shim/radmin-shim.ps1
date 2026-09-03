# ============================================================
#  radmin-shim.ps1  -  Radmin VPN JSON API for the Linux client
#  Compatible with PowerShell 2.0 (Windows 7) - JSON built by hand.
#  Output: a block between <<<RADMINJSON>>> and <<<END>>>. Read-only.
# ============================================================
$ErrorActionPreference = "SilentlyContinue"

function JStr($s) {
  if ($null -eq $s) { return '""' }
  $s = [string]$s
  $s = $s.Replace('\','\\').Replace('"','\"').Replace([char]13,'').Replace([char]10,'\n').Replace([char]9,'\t')
  return '"' + $s + '"'
}

function Get-NodeIp {
  $cfg = Get-WmiObject Win32_NetworkAdapterConfiguration | Where-Object {
    $_.Description -match "Radmin" -and $_.IPAddress
  } | Select-Object -First 1
  if ($cfg) {
    foreach ($ip in $cfg.IPAddress) { if ($ip -like "26.*") { return $ip } }
  }
  return $null
}

function Get-ServiceState {
  $s = Get-WmiObject Win32_Service | Where-Object { $_.Name -eq "RvControlSvc" } | Select-Object -First 1
  if ($s) { return $s.State } else { return "NotInstalled" }
}

$nodeIp = Get-NodeIp
$svc    = Get-ServiceState

# Peers = ARP table of the Radmin interface
$peerJson = @()
$arp = (arp -a) 2>$null
$inRadmin = $false
foreach ($line in $arp) {
  if ($line -match "Interface:\s+(\S+)") {
    $iface = $matches[1]
    $inRadmin = ($iface -like "26.*")
    continue
  }
  if (-not $inRadmin) { continue }
  if ($line -match "^\s*(26\.\d+\.\d+\.\d+)\s+([0-9a-fA-F-]{17})\s+(\w+)") {
    $ip = $matches[1]; $mac = $matches[2]; $type = $matches[3]
    if ($ip -eq "26.255.255.255") { continue }
    if ($ip -eq $nodeIp) { continue }
    # try the NetBIOS hostname (the peer machine's real name)
    $hn = ""
    $nb = (nbtstat -A $ip) 2>$null
    foreach ($nl in $nb) {
      if ($nl -match "^\s*(\S+)\s+<00>\s+UNIQUE") { $hn = $matches[1]; break }
    }
    $peerJson += '{"ip":' + (JStr $ip) + ',"mac":' + (JStr $mac) + ',"type":' + (JStr $type) + ',"host":' + (JStr $hn) + '}'
  }
}

# associated networks (GUIDs under Networks) + node alias
$netKey = "HKLM:\SOFTWARE\Wow6432Node\Famatech\RadminVPN\1.0\Networks"
$netJson = @()
if (Test-Path $netKey) {
  foreach ($sub in Get-ChildItem $netKey) {
    $netJson += (JStr $sub.PSChildName)
  }
}
$alias = (Get-ItemProperty "HKLM:\SOFTWARE\Wow6432Node\Famatech\RadminVPN\1.0").Alias

$ts = [int][double]::Parse((Get-Date -UFormat %s))
$json = '{'
$json += '"ok":true'
$json += ',"node_ip":' + (JStr $nodeIp)
$json += ',"hostname":' + (JStr $env:COMPUTERNAME)
$json += ',"alias":' + (JStr $alias)
$json += ',"service":' + (JStr $svc)
$json += ',"networks":[' + ($netJson -join ',') + ']'
$json += ',"peers":[' + ($peerJson -join ',') + ']'
$json += ',"ts":' + $ts
$json += '}'

Write-Output "<<<RADMINJSON>>>"
Write-Output $json
Write-Output "<<<END>>>"
