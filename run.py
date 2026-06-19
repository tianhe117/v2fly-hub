#!/usr/bin/env python
"""Xray-hub - Entry point"""

import logging
from app.main import app
from app import db

# 禁用 Flask 访问日志，避免轮询日志无限循环
log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)

if __name__ == '__main__':
    port = int(db.get_setting('web_port') or 8080)
    app.run(debug=True, host='0.0.0.0', port=port)
