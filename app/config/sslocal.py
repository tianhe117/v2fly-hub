import json


def generate_sslocal_config(node, local_port):
    """生成 sslocal 配置

    支持协议: ss (shadowsocks)
    sslocal 使用 JSON 配置格式
    """
    protocol = node['protocol']
    address = node['address']
    port = node['port']

    if protocol != 'ss':
        raise ValueError(f'sslocal does not support protocol: {protocol}')

    try:
        cfg = json.loads(node.get('config_json', '{}'))
    except (json.JSONDecodeError, TypeError):
        cfg = {}

    config = {
        "server": address,
        "server_port": port,
        "password": cfg.get('password', ''),
        "method": cfg.get('method', 'aes-256-gcm'),
        "local_address": "127.0.0.1",
        "local_port": local_port,
    }

    # 插件支持
    plugin = cfg.get('plugin', '')
    if plugin:
        config['plugin'] = plugin
        plugin_opts = cfg.get('plugin_opts', '')
        if plugin_opts:
            config['plugin_opts'] = plugin_opts

    return config
