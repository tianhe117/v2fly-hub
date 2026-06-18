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
    conn.execute('''
        CREATE TABLE IF NOT EXISTS subscriptions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            url TEXT NOT NULL,
            filter_keywords TEXT DEFAULT '',
            exclude_keywords TEXT DEFAULT '',
            updated_at TIMESTAMP
        )
    ''')
    conn.execute('''
        CREATE TABLE IF NOT EXISTS nodes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sub_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            protocol TEXT NOT NULL,
            address TEXT NOT NULL,
            port INTEGER NOT NULL,
            config_json TEXT NOT NULL,
            is_in_pool BOOLEAN DEFAULT 0,
            FOREIGN KEY (sub_id) REFERENCES subscriptions(id) ON DELETE CASCADE
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
    """清空节点表"""
    conn = get_db()
    conn.execute('DELETE FROM nodes')
    conn.commit()
    conn.close()


# ========== 订阅操作 ==========

def get_all_subscriptions():
    """获取所有订阅"""
    conn = get_db()
    subs = conn.execute('SELECT * FROM subscriptions ORDER BY id').fetchall()
    conn.close()
    return [dict(s) for s in subs]


def get_subscription(sub_id):
    """获取单个订阅"""
    conn = get_db()
    sub = conn.execute('SELECT * FROM subscriptions WHERE id = ?', (sub_id,)).fetchone()
    conn.close()
    return dict(sub) if sub else None


def create_subscription(name, url, filter_keywords='', exclude_keywords=''):
    """创建订阅"""
    conn = get_db()
    cursor = conn.execute(
        'INSERT INTO subscriptions (name, url, filter_keywords, exclude_keywords, updated_at) VALUES (?, ?, ?, ?, ?)',
        (name, url, filter_keywords, exclude_keywords, None)
    )
    sub_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return sub_id


def update_subscription(sub_id, data):
    """更新订阅"""
    conn = get_db()
    fields = []
    values = []
    for key in ['name', 'url', 'filter_keywords', 'exclude_keywords']:
        if key in data:
            fields.append(f'{key} = ?')
            values.append(data[key])
    if fields:
        values.append(sub_id)
        conn.execute(f'UPDATE subscriptions SET {", ".join(fields)} WHERE id = ?', values)
        conn.commit()
    conn.close()


def delete_subscription(sub_id):
    """删除订阅"""
    conn = get_db()
    conn.execute('DELETE FROM nodes WHERE sub_id = ?', (sub_id,))
    conn.execute('DELETE FROM subscriptions WHERE id = ?', (sub_id,))
    conn.commit()
    conn.close()


def set_subscription_updated(sub_id):
    """设置订阅更新时间"""
    conn = get_db()
    from datetime import datetime
    conn.execute('UPDATE subscriptions SET updated_at = ? WHERE id = ?', (datetime.now().isoformat(), sub_id))
    conn.commit()
    conn.close()


# ========== 节点操作 ==========

def get_nodes_by_sub(sub_id):
    """获取订阅下的所有节点"""
    conn = get_db()
    nodes = conn.execute('SELECT * FROM nodes WHERE sub_id = ? ORDER BY id', (sub_id,)).fetchall()
    conn.close()
    return [dict(n) for n in nodes]


def clear_nodes_by_sub(sub_id):
    """清空订阅下的节点"""
    conn = get_db()
    conn.execute('DELETE FROM nodes WHERE sub_id = ?', (sub_id,))
    conn.commit()
    conn.close()


def add_nodes(sub_id, nodes):
    """批量添加节点"""
    conn = get_db()
    for node in nodes:
        conn.execute(
            'INSERT INTO nodes (sub_id, name, protocol, address, port, config_json) VALUES (?, ?, ?, ?, ?, ?)',
            (sub_id, node['name'], node['protocol'], node['address'], node['port'], node['config_json'])
        )
    conn.commit()
    conn.close()


def get_all_nodes():
    """获取所有节点"""
    conn = get_db()
    nodes = conn.execute('SELECT * FROM nodes ORDER BY sub_id, id').fetchall()
    conn.close()
    return [dict(n) for n in nodes]


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
