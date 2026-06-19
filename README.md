# V2fly-hub

Web-based management tool for V2fly-core. Manages subscriptions, node selection, availability checking, and auto-failover.

## Quick Start

```bash
pip install -r requirements.txt
python run.py
```

Open http://localhost:8080

## Directory Structure

```
v2ray-webui/
├── run.py                  # Entry point
├── app/                    # Python application package
│   ├── __init__.py
│   ├── main.py             # Flask application (page routes & API)
│   ├── db.py               # Database operations (SQLite)
│   ├── v2fly_manager.py    # v2fly process management
│   └── upgrade.py          # Binary upgrade from GitHub
├── templates/              # Jinja2 HTML templates
│   ├── base.html           # Shared layout (navbar, sidebar, log panel)
│   ├── dashboard.html      # Dashboard
│   ├── inbounds.html       # Inbound settings
│   ├── outbounds.html      # Outbound settings
│   ├── subscriptions.html  # Subscription management
│   ├── nodes.html          # Node list
│   └── settings.html       # Settings + V2fly upgrade
├── bin/                    # V2fly binary + data files (gitignored)
├── config/                 # V2fly runtime config (gitignored)
├── data/                   # SQLite database (gitignored)
├── docs/
│   └── DESIGN.md           # Design document
├── requirements.txt
└── .gitignore
```

## Concept: Service = Inbound + Outbound

- **Inbound**: HTTP / SOCKS / Shadowsocks / VMess
- **Outbound**: Freedom (direct) / Single proxy / Auto-switch (node pool with failover)

## License

MIT
