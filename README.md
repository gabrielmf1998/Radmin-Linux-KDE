# Radmin VPN (Linux) — clone funcional

UI PySide6 que **imita a janela do Radmin VPN** mas lê o Radmin **real** rodando
na VM Windows (bancada `ntlite-bench`). Fase 2: só leitura — nada aqui altera o Radmin.

    radmin-linux/
    ├── agent/          scripts que rodam DENTRO da VM (Windows)
    │   ├── net-orchestrator.ps1  garante ICS no boot (resolve ordem)
    │   ├── power-guard.ps1       VM nunca dorme/hiberna/reinicia
    │   ├── radmin-update.ps1     checa/instala update do Radmin
    │   └── agent-install.ps1     registra as tarefas no boot
    ├── app/            cliente Linux
    │   ├── main.py     UI Qt (clone) + tray
    │   ├── backend.py  transporte: chama a shim via WMI e parseia o JSON
    │   ├── roster.py   lista persistente de peers (offline + apelidos locais)
    │   ├── vmctl.py    liga/desliga a VM inteira (monitor QEMU + preflight)
    │   ├── agent.py    dispara os scripts do agente e lê updates
    │   └── icons.py    logo/sinal/power desenhados em QPainter
    ├── shim/
    │   └── radmin-shim.ps1   roda na VM, devolve JSON do estado do Radmin
    ├── radmin-linux.sh   abre a UI (auto-repara a pilha antes)
    ├── deploy-shim.sh    (re)envia a shim para C:\ na VM
    └── deploy-agent.sh   (re)envia o agente para C:\radmin-agent na VM

## Como funciona

    UI (Linux) ──WMI/impacket sobre a tap──▶ VM Windows ──▶ Radmin real
                bench:bench@192.168.137.1        C:\radmin-shim.ps1

- **nó** (nome/IP/status): da própria VM
- **peers online + IP**: tabela ARP da placa Radmin (tempo real)
- **hostname do peer**: NetBIOS (`nbtstat`)
- **apelido**: duplo-clique num peer — local, só na UI (não toca no Radmin)
- **offline**: o roster lembra quem já viu; **liveness por ping sweep** do Linux
  (temos rota p/ 26.0.0.0/8) a cada 30s — quem não responde fica offline
- **conectar/desconectar**: clique no botão power ou menu Network → para/inicia o
  RvControlSvc (o botão real da mesh). Validado: derruba/restaura os peers.
- **sair da rede**: menu Network → remove a associação (chave Networks\{GUID})
- **entrar/criar rede**: exige o servidor Radmin (protocolo proprietário) — a UI
  abre a janela real do Radmin na VM (VNC) p/ você fazer, e atualiza depois

## Uso

    ./radmin-linux.sh    # auto-repara a pilha e abre a janela (fecha p/ bandeja)

O launcher roda `preflight.sh`, que verifica e conserta 7 camadas antes de abrir:
venv, interface tapradmin, DHCP, VM ligada, rede, WMI, shim na VM. Se a tap tiver
perdido o carrier (device tun recriado com a VM viva) ele **reinicia a VM** sozinho.

    ./preflight.sh       # roda só a checagem/reparo (use -q p/ só erros)
    ./deploy-shim.sh     # reenvia a shim manualmente

## Limites (honestos)

- A GUI real mostra o **apelido Radmin** ("Kaylarica_Laptop"); a shim só alcança o
  **hostname NetBIOS** ("PC-BIA"). O apelido bonito vive no protocolo LPC
  (`RadminVpnGuiChannel`) — decifrá-lo seria uma fase à parte.
- Cada refresh custa ~15-20s (o WMI reconecta o SMB + nbtstat por peer).
- Depende de: VM ligada, tap `192.168.137.2` no ar, UAC derrubado na VM.

## Config (env)

    RADMIN_TARGET=bench:bench@192.168.137.1   # alvo WMI
    RADMIN_SHIM='C:\radmin-shim.ps1'          # caminho da shim na VM

## Automação (agente na VM)

O agente roda **sozinho no boot** da VM (tarefas agendadas) e é controlável pela UI:

| script | quando | o que faz |
|---|---|---|
| `power-guard.ps1` | boot (SYSTEM) | trava energia: sem sleep/hibernate/monitor-off, WU sem reboot |
| `net-orchestrator.ps1` | boot +30s, e ao logon | espera o Radmin conectar, garante ICS (Radmin=pública, isolada=privada) |
| `radmin-update.ps1` | sob demanda | compara versão instalada vs. servidor, instala silencioso |

Instalar/reparar: `./deploy-agent.sh` + menu **System → Instalar/reparar agente**.

## O power da UI = a VM inteira

Para o usuário, **Radmin VPN (Linux) é a VM**. O botão power:
- VM ligada → desliga a VM (ACPI limpo via monitor QEMU)
- VM desligada → liga a VM (via preflight, que auto-repara a pilha)

Validado: desligar pela UI → religar pela UI → o agente reconfigura tudo no boot e
o `RvControlSvc` volta Running sozinho. **Com ICS não há o deadlock da bridge L2.**
