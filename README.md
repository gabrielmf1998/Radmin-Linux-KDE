# Radmin VPN (Linux) — clone funcional

UI PySide6 que **imita a janela do Radmin VPN** mas lê o Radmin **real** rodando
na VM Windows (bancada `ntlite-bench`). Fase 2: só leitura — nada aqui altera o Radmin.

    radmin-linux/
    ├── app/            cliente Linux
    │   ├── main.py     UI Qt (clone) + tray
    │   ├── backend.py  transporte: chama a shim via WMI e parseia o JSON
    │   ├── roster.py   lista persistente de peers (offline + apelidos locais)
    │   └── icons.py    logo/sinal/power desenhados em QPainter
    ├── shim/
    │   └── radmin-shim.ps1   roda na VM, devolve JSON do estado do Radmin
    ├── radmin-linux.sh   abre a UI
    └── deploy-shim.sh    (re)envia a shim para C:\ na VM

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
