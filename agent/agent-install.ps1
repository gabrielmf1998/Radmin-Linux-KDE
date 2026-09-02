# ============================================================
#  agent-install.ps1 - instala o agente Radmin-Linux na VM.
#  Cria C:\radmin-agent, registra tarefas agendadas no boot:
#   - power-guard   (ao ligar)
#   - net-orchestrator (ao ligar, apos rede)
#  Roda como SYSTEM no boot -> resolve o deadlock sem intervencao.
# ============================================================
$ErrorActionPreference = "SilentlyContinue"
$dir = "C:\radmin-agent"
New-Item -ItemType Directory -Path $dir -Force | Out-Null

# tarefa: power-guard ao ligar (SYSTEM)
schtasks /create /tn "RadminAgent-Power" /tr "powershell -ExecutionPolicy Bypass -WindowStyle Hidden -File $dir\power-guard.ps1" /sc onstart /ru SYSTEM /rl HIGHEST /f | Out-Null

# tarefa: orquestrador de rede ao ligar (SYSTEM), com atraso p/ a rede subir
schtasks /create /tn "RadminAgent-Net" /tr "powershell -ExecutionPolicy Bypass -WindowStyle Hidden -File $dir\net-orchestrator.ps1" /sc onstart /delay 0000:30 /ru SYSTEM /rl HIGHEST /f | Out-Null

# tarefa: orquestrador tambem ao logon do bench (redundancia, caso ICS precise da sessao)
schtasks /create /tn "RadminAgent-Net-Logon" /tr "powershell -ExecutionPolicy Bypass -WindowStyle Hidden -File $dir\net-orchestrator.ps1" /sc onlogon /ru bench /rp bench /it /f | Out-Null

# tarefa: health + auto-heal a cada 5 min (redundancia caso a UI esteja fechada)
schtasks /create /tn "RadminAgent-Health" /tr "powershell -ExecutionPolicy Bypass -WindowStyle Hidden -File $dir\health.ps1 -Heal" /sc minute /mo 5 /ru SYSTEM /rl HIGHEST /f | Out-Null

Write-Output "<<<AGENTOK>>>"
schtasks /query /tn "RadminAgent-Power" /fo LIST 2>&1 | Select-String "TaskName|Status" | Out-String
schtasks /query /tn "RadminAgent-Net" /fo LIST 2>&1 | Select-String "TaskName|Status" | Out-String
