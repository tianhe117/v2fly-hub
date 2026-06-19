import sqlite3
import os

# 数据库路径：相对于项目根目录的 data/ 目录
DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'data', 'proxyhub.db')

# 支持的二进制类型
BIN_TYPES = ['xray', 'sslocal', 'sing-box']

DEFAULT_SETTINGS = {
    'bin_path_xray': './bin/xray.exe',
    'bin_path_sslocal': './bin/sslocal.exe',
    'bin_path_singbox': './bin/sing-box.exe',
    'config_dir': './config',
    'check_interval_normal': '240',
    'check_interval_failover': '30',
    'tcp_timeout': '3',
    'curl_timeout': '5',
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
            updated_at TIMESTAMP,
            upload_bytes INTEGER DEFAULT 0,
            download_bytes INTEGER DEFAULT 0,
            total_bytes INTEGER DEFAULT 0,
            expire_at INTEGER DEFAULT 0
        )
    ''')
    conn.execute('''
        CREATE TABLE IF NOT EXISTS nodes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sub_id INTEGER DEFAULT 0,
            name TEXT NOT NULL,
            protocol TEXT NOT NULL,
            address TEXT NOT NULL,
            port INTEGER NOT NULL,
            config_json TEXT NOT NULL,
            bin_type TEXT DEFAULT 'xray',
            is_in_pool BOOLEAN DEFAULT 0,
            tcp_latency INTEGER,
            curl_latency INTEGER,
            last_check_at TIMESTAMP
        )
    ''')
    conn.execute('''
        CREATE TABLE IF NOT EXISTS inbounds (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            protocol TEXT NOT NULL,
            listen_addr TEXT DEFAULT '0.0.0.0',
            port INTEGER NOT NULL,
            params_json TEXT NOT NULL DEFAULT '{}'
        )
    ''')
    conn.execute('''
        CREATE TABLE IF NOT EXISTS outbounds (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            type TEXT NOT NULL,
            config_json TEXT NOT NULL DEFAULT '{}'
        )
    ''')
    conn.execute('''
        CREATE TABLE IF NOT EXISTS outbound_nodes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            outbound_id INTEGER NOT NULL,
            node_id INTEGER NOT NULL,
            priority INTEGER DEFAULT 0
        )
    ''')
    conn.execute('''
        CREATE TABLE IF NOT EXISTS services (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            inbound_id INTEGER NOT NULL,
            outbound_id INTEGER NOT NULL,
            status TEXT DEFAULT 'stopped',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (inbound_id) REFERENCES inbounds(id),
            FOREIGN KEY (outbound_id) REFERENCES outbounds(id)
        )
    ''')
    conn.commit()

    # 迁移：添加新列（如果不存在）
    for col, typ in [
        ('bin_type', 'TEXT DEFAULT "xray"'),
        ('tcp_latency', 'INTEGER'),
        ('curl_latency', 'INTEGER'),
        ('last_check_at', 'TIMESTAMP'),
    ]:
        try:
            conn.execute(f'ALTER TABLE nodes ADD COLUMN {col} {typ}')
        except:
            pass

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


def update_subscription_traffic(sub_id, info):
    """更新订阅流量信息"""
    if not info:
        return
    conn = get_db()
    conn.execute('''
        UPDATE subscriptions SET
            upload_bytes = ?,
            download_bytes = ?,
            total_bytes = ?,
            expire_at = ?
        WHERE id = ?
    ''', (
        info.get('upload', 0),
        info.get('download', 0),
        info.get('total', 0),
        info.get('expire', 0),
        sub_id
    ))
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
            'INSERT INTO nodes (sub_id, name, protocol, address, port, config_json, bin_type) VALUES (?, ?, ?, ?, ?, ?, ?)',
            (sub_id, node['name'], node['protocol'], node['address'], node['port'],
             node['config_json'], node.get('bin_type', 'xray'))
        )
    conn.commit()
    conn.close()


def get_all_nodes():
    """获取所有节点"""
    conn = get_db()
    nodes = conn.execute('SELECT * FROM nodes ORDER BY sub_id, id').fetchall()
    conn.close()
    return [dict(n) for n in nodes]


def update_node_latency(node_id, tcp_latency, curl_latency):
    """更新节点延迟"""
    from datetime import datetime
    conn = get_db()
    conn.execute(
        'UPDATE nodes SET tcp_latency = ?, curl_latency = ?, last_check_at = ? WHERE id = ?',
        (tcp_latency, curl_latency, datetime.now().isoformat(), node_id)
    )
    conn.commit()
    conn.close()


def update_node(node_id, name, protocol, address, port, config_json, bin_type='xray'):
    """更新节点信息"""
    conn = get_db()
    conn.execute(
        'UPDATE nodes SET name = ?, protocol = ?, address = ?, port = ?, config_json = ?, bin_type = ? WHERE id = ?',
        (name, protocol, address, port, config_json, bin_type, node_id)
    )
    conn.commit()
    conn.close()


def get_nodes_grouped():
    """获取按订阅分组的节点（包括用户自定义节点）"""
    conn = get_db()
    # 用户自定义节点（sub_id = 0）
    custom_nodes = conn.execute('SELECT * FROM nodes WHERE sub_id = 0 ORDER BY id').fetchall()
    result = [{'sub': {'id': 0, 'name': 'Custom Nodes'}, 'nodes': [dict(n) for n in custom_nodes]}]

    # 订阅节点
    subs = conn.execute('SELECT * FROM subscriptions ORDER BY id').fetchall()
    for sub in subs:
        nodes = conn.execute('SELECT * FROM nodes WHERE sub_id = ? ORDER BY id', (sub['id'],)).fetchall()
        result.append({
            'sub': dict(sub),
            'nodes': [dict(n) for n in nodes]
        })
    conn.close()
    return result


def add_custom_node(name, protocol, address, port, config_json, bin_type='xray'):
    """添加用户自定义节点"""
    conn = get_db()
    cursor = conn.execute(
        'INSERT INTO nodes (sub_id, name, protocol, address, port, config_json, bin_type) VALUES (0, ?, ?, ?, ?, ?, ?)',
        (name, protocol, address, port, config_json, bin_type)
    )
    node_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return node_id


def delete_node(node_id):
    """删除节点"""
    conn = get_db()
    conn.execute('DELETE FROM nodes WHERE id = ?', (node_id,))
    conn.commit()
    conn.close()


# ========== 入站操作 ==========

def get_all_inbounds():
    """获取所有入站"""
    conn = get_db()
    rows = conn.execute('SELECT * FROM inbounds ORDER BY id').fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_inbound(inbound_id):
    """获取单个入站"""
    conn = get_db()
    row = conn.execute('SELECT * FROM inbounds WHERE id = ?', (inbound_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def create_inbound(name, protocol, listen_addr, port, params_json):
    """创建入站"""
    conn = get_db()
    cursor = conn.execute(
        'INSERT INTO inbounds (name, protocol, listen_addr, port, params_json) VALUES (?, ?, ?, ?, ?)',
        (name, protocol, listen_addr, port, params_json)
    )
    inbound_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return inbound_id


def update_inbound(inbound_id, name, protocol, listen_addr, port, params_json):
    """更新入站"""
    conn = get_db()
    conn.execute(
        'UPDATE inbounds SET name = ?, protocol = ?, listen_addr = ?, port = ?, params_json = ? WHERE id = ?',
        (name, protocol, listen_addr, port, params_json, inbound_id)
    )
    conn.commit()
    conn.close()


def delete_inbound(inbound_id):
    """删除入站"""
    conn = get_db()
    conn.execute('DELETE FROM inbounds WHERE id = ?', (inbound_id,))
    conn.commit()
    conn.close()


# ========== 出站操作 ==========

def get_all_outbounds():
    """获取所有出站"""
    conn = get_db()
    rows = conn.execute('SELECT * FROM outbounds ORDER BY id').fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_outbound(outbound_id):
    """获取单个出站"""
    conn = get_db()
    row = conn.execute('SELECT * FROM outbounds WHERE id = ?', (outbound_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def create_outbound(name, out_type, config_json):
    """创建出站"""
    conn = get_db()
    cursor = conn.execute(
        'INSERT INTO outbounds (name, type, config_json) VALUES (?, ?, ?)',
        (name, out_type, config_json)
    )
    outbound_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return outbound_id


def update_outbound(outbound_id, name, out_type, config_json):
    """更新出站"""
    conn = get_db()
    conn.execute(
        'UPDATE outbounds SET name = ?, type = ?, config_json = ? WHERE id = ?',
        (name, out_type, config_json, outbound_id)
    )
    conn.commit()
    conn.close()


def delete_outbound(outbound_id):
    """删除出站（同时删除关联的节点池）"""
    conn = get_db()
    conn.execute('DELETE FROM outbound_nodes WHERE outbound_id = ?', (outbound_id,))
    conn.execute('DELETE FROM outbounds WHERE id = ?', (outbound_id,))
    conn.commit()
    conn.close()


# ========== 出站节点池操作 ==========

def get_outbound_nodes(outbound_id):
    """获取出站的节点池（按优先级排序）"""
    conn = get_db()
    rows = conn.execute('''
        SELECT on2.id as pool_id, on2.priority, n.*
        FROM outbound_nodes on2
        JOIN nodes n ON on2.node_id = n.id
        WHERE on2.outbound_id = ?
        ORDER BY on2.priority
    ''', (outbound_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def add_outbound_node(outbound_id, node_id, priority):
    """向出站节点池添加节点"""
    conn = get_db()
    conn.execute(
        'INSERT INTO outbound_nodes (outbound_id, node_id, priority) VALUES (?, ?, ?)',
        (outbound_id, node_id, priority)
    )
    conn.commit()
    conn.close()


def remove_outbound_node(pool_id):
    """从出站节点池移除节点"""
    conn = get_db()
    conn.execute('DELETE FROM outbound_nodes WHERE id = ?', (pool_id,))
    conn.commit()
    conn.close()


def reorder_outbound_nodes(outbound_id, node_ids):
    """重新排序出站节点池（node_ids 按新优先级顺序）"""
    conn = get_db()
    for i, node_id in enumerate(node_ids):
        conn.execute(
            'UPDATE outbound_nodes SET priority = ? WHERE outbound_id = ? AND node_id = ?',
            (i + 1, outbound_id, node_id)
        )
    conn.commit()
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


# ========== 服务操作 ==========

def get_all_services():
    """获取所有服务（含 inbound/outbound 信息）"""
    conn = get_db()
    rows = conn.execute('''
        SELECT s.*, i.name as inbound_name, i.protocol as inbound_protocol,
               i.port as inbound_port, i.params_json as inbound_params,
               o.name as outbound_name, o.type as outbound_type, o.config_json as outbound_config
        FROM services s
        JOIN inbounds i ON s.inbound_id = i.id
        JOIN outbounds o ON s.outbound_id = o.id
        ORDER BY s.id
    ''').fetchall()
    conn.close()
    result = []
    for row in rows:
        svc = dict(row)
        # 如果是 auto 类型出站，获取节点池信息
        if svc['outbound_type'] == 'auto':
            pool = get_outbound_nodes(svc['outbound_id'])
            svc['outbound_pool'] = pool
        result.append(svc)
    return result


def get_service(service_id):
    """获取单个服务"""
    conn = get_db()
    row = conn.execute('''
        SELECT s.*, i.name as inbound_name, i.protocol as inbound_protocol,
               i.port as inbound_port, i.params_json as inbound_params,
               o.name as outbound_name, o.type as outbound_type, o.config_json as outbound_config
        FROM services s
        JOIN inbounds i ON s.inbound_id = i.id
        JOIN outbounds o ON s.outbound_id = o.id
        WHERE s.id = ?
    ''', (service_id,)).fetchone()
    conn.close()
    if not row:
        return None
    svc = dict(row)
    if svc['outbound_type'] == 'auto':
        svc['outbound_pool'] = get_outbound_nodes(svc['outbound_id'])
    return svc


def create_service(name, inbound_id, outbound_id):
    """创建服务"""
    conn = get_db()
    cursor = conn.execute(
        'INSERT INTO services (name, inbound_id, outbound_id) VALUES (?, ?, ?)',
        (name, inbound_id, outbound_id)
    )
    service_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return service_id


def update_service(service_id, name=None, inbound_id=None, outbound_id=None):
    """更新服务"""
    conn = get_db()
    fields = []
    values = []
    if name is not None:
        fields.append('name = ?')
        values.append(name)
    if inbound_id is not None:
        fields.append('inbound_id = ?')
        values.append(inbound_id)
    if outbound_id is not None:
        fields.append('outbound_id = ?')
        values.append(outbound_id)
    if fields:
        values.append(service_id)
        conn.execute(f'UPDATE services SET {", ".join(fields)} WHERE id = ?', values)
        conn.commit()
    conn.close()


def delete_service(service_id):
    """删除服务"""
    conn = get_db()
    conn.execute('DELETE FROM services WHERE id = ?', (service_id,))
    conn.commit()
    conn.close()


def update_service_status(service_id, status):
    """更新服务状态"""
    conn = get_db()
    conn.execute('UPDATE services SET status = ? WHERE id = ?', (status, service_id))
    conn.commit()
    conn.close()


# 初始化数据库
init_db()
