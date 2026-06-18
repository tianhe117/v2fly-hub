#!/usr/bin/env python
"""V2Fly Manager - Entry point"""

from app.main import app
from app import db

if __name__ == '__main__':
    host = db.get_setting('web_listen') or '0.0.0.0'
    port = int(db.get_setting('web_port') or 8080)
    app.run(debug=True, host=host, port=port)
