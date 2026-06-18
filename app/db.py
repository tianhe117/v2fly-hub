import sqlite3
import os

# 数据库路径：相对于项目根目录的 data/ 目录
DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'data', 'v2ray.db')

DEFAULT_SETTINGS = {
    'v2fly_bin_path': './bin/v2ray.exe',
    'v2fly_config_dir': './config',
    'check_interval_normal': '240',
    'check_interval_failover': '30',
    'tcp_timeout': '3',
    'curl_timeout': '10',
    'test_url': 'http://www.gstatic.com/generate_204',
    'auto_failover': 'true',
    'web_port': '8080',
    'web_username': 'admin',
    'web_password': '',
}


def get_db():
    """获取数据库连接"""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """初始化数据库表"""
    conn = get_db()
    conn.execute('''
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
    ''')
    conn.commit()
    conn.close()


def get_all_settings():
    """获取所有设置"""
    conn = get_db()
    rows = conn.execute('SELECT key, value FROM settings').fetchall()
    conn.close()
    # 合并默认值，数据库优先
    settings = dict(DEFAULT_SETTINGS)
    for row in rows:
        settings[row['key']] = row['value']
    return settings


def get_setting(key):
    """获取单个设置"""
    conn = get_db()
    row = conn.execute('SELECT value FROM settings WHERE key = ?', (key,)).fetchone()
    conn.close()
    if row:
        return row['value']
    return DEFAULT_SETTINGS.get(key)


def update_settings(data):
    """批量更新设置"""
    conn = get_db()
    for key, value in data.items():
        conn.execute(
            'INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)',
            (key, str(value))
        )
    conn.commit()
    conn.close()


def reset_settings():
    """重置所有设置为默认值"""
    conn = get_db()
    conn.execute('DELETE FROM settings')
    conn.commit()
    conn.close()


def clear_nodes():
    """清空节点表（如果存在）"""
    conn = get_db()
    try:
        conn.execute('DELETE FROM nodes')
        conn.commit()
    except sqlite3.OperationalError:
        pass  # 表不存在时忽略
    conn.close()


def clear_database():
    """清空整个数据库"""
    conn = get_db()
    tables = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()
    for table in tables:
        conn.execute(f'DELETE FROM {table["name"]}')
    conn.commit()
    conn.close()


# 初始化数据库
init_db()
