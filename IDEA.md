# The idea

**Run a Windows-only app on Linux, natively-feeling, without the user ever seeing Windows.**

Some software only exists for Windows and can't be ported, reverse-engineered, or
replaced — here, Radmin VPN (a mesh VPN whose network adapter is a Windows kernel
driver). Wine can't load kernel drivers, and there's no Linux client.

Instead of faking the app, we run the **real** app inside a tiny headless Windows VM
and drive it from a native-looking Linux front-end. The VM is plumbing the user never
opens; the Linux window *is* the app, as far as they're concerned.

```
┌── Linux desktop ───────────────────────────────┐
│                                                 │
│   Radmin VPN (Linux)   ← native Qt window       │
│      the user clicks here                       │
│           │                                     │
│           │ WMI over an isolated NAT link       │
│           ▼                                     │
│   ┌── headless QEMU VM (Windows 7, 512 MB) ──┐  │
│   │   real Radmin VPN + mesh driver          │  │
│   │   agent scripts (boot tasks) keep it      │  │
│   │   configured, healed and up to date       │  │
│   └──────────────────────────────────────────┘  │
│           │                                     │
│           ▼ ICS/NAT                             │
│      the friends' 26.0.0.0/8 mesh              │
└─────────────────────────────────────────────────┘
```

## Why it works everywhere

- **Every Linux kernel ships KVM.** Just enable it.
- The VM needs **512 MB RAM and 1 CPU** — no machine lacks that.
- The VM image is **built once, ready to go**: Windows, the app, the agent, the
  scheduled tasks, the NAT link — all baked in. Ship the image, it just runs.

## What the pieces do

| piece | role |
|---|---|
| **The VM** | a Windows 7 kernel running the real app, headless — nobody logs in |
| **Isolated NAT link** | a private `tap` between host and VM; no bridge to any real NIC |
| **Agent (in the VM)** | boot tasks that configure networking, lock power, self-heal, auto-update |
| **The front-end** | a Qt window that looks like the real app but talks to the VM over WMI |

The user never opens the VM, never logs into Windows, never validates anything by
hand. The front-end is the whole product: it powers the VM on and off, shows the
mesh, connects/disconnects, and **repairs itself in the background**.

## It's not just Radmin

Swap the app and the front-end's data layer and the same skeleton adapts **any
Windows-only software** to Linux: the headless VM, the isolated link, the boot
agent, the self-healing, and the `shim → WMI → UI` pattern are all reusable.

Radmin VPN is simply the first proof that it works end to end.

## Status

Working proof of concept. Still under active testing — see `README.md` for the
concrete architecture and the per-component detail. Not production-ready; the VM
image is not distributed here (it carries live state).
