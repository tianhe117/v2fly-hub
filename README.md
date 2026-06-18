# v2fly-manager

Web-based management tool for v2fly-core. Manages subscriptions, node selection, availability checking, and auto-failover.

## Quick Start

```bash
pip install -r requirements.txt
python app.py
```

Open http://localhost:8080

## Directory Structure

```
v2ray-webui/
├── app.py              # Flask application
├── models.py           # Database models (SQLite)
├── subscription.py     # Subscription parsing (vmess://, ss://)
├── node_checker.py     # Node availability checker
├── v2fly_manager.py    # v2fly process management + config generation
├── templates/          # Jinja2 templates
│   ├── base.html       # Shared layout (navbar, sidebar, log panel)
│   ├── dashboard.html  # Dashboard
│   ├── inbounds.html   # Inbound settings
│   ├── outbounds.html  # Outbound settings
│   ├── subscriptions.html
│   ├── nodes.html
│   └── settings.html
├── bin/                # v2fly binary (gitignored)
├── config/             # v2fly runtime config (gitignored)
├── data/               # SQLite database (gitignored)
├── docs/               # Documentation
│   └── DESIGN.md       # Design document
└── requirements.txt
```

## Concept: Service = Inbound + Outbound

- **Inbound**: HTTP / SOCKS / Shadowsocks / VMess
- **Outbound**: Freedom (direct) / Single proxy / Auto-switch (node pool with failover)

## License

MIT
