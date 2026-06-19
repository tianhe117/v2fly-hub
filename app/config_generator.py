"""配置生成器 — 为 service 生成 xray + 出站 bin 的配置"""

import json
import os
import socket
import random
from . import db
from .config.xray import _build_outbound as xray_build_outbound, _build_stream_settings
from .config.sslocal import generate_sslocal_config
from .config.singbox import generate_singbox_config


def find_available_port(start=50000, end=60000, exclude=None):
    """查找可用端口"""
    exclude = exclude or set()
    for _ in range(100):
        port = random.randint(start, end)
        if port in exclude:
            continue
        if is_port_available(port):
            return port
    raise RuntimeError('cannot find available port')


def is_port_available(port):
    """检查端口是否可用"""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(('127.0.0.1', port))
            return True
    except OSError:
        return False


def check_inbound_port(port):
    """检查入站端口是否可用"""
    return is_port_available(port)


def generate_service_config(service_id):
    """为 service 生成完整配置

    返回:
        {
            'success': True/False,
            'message': '...',
            'config_dir': 'config/<service_name>',
            'xray_in': {...},      # xray 入站配置
            'outbound_bin': 'xray'|'sslocal'|'sing-box',
            'outbound_config': {...},  # 出站 bin 配置
            'socks_port': 50001    # 中间 socks 端口
        }
    """
    service = db.get_service(service_id)
    if not service:
        return {'success': False, 'message': 'service not found'}

    inbound_id = service['inbound_id']
    outbound_id = service['outbound_id']

    # 获取 inbound 和 outbound 详情
    inbound = db.get_inbound(inbound_id)
    outbound = db.get_outbound(outbound_id)

    if not inbound or not outbound:
        return {'success': False, 'message': 'inbound or outbound not found'}

    # 检查入站端口
    if not check_inbound_port(inbound['port']):
        return {'success': False, 'message': f'port {inbound["port"]} is already in use'}

    # 获取出站节点
    node = _get_outbound_node(outbound)
    if not node:
        return {'success': False, 'message': 'no node available for outbound'}

    # 分配中间 socks 端口
    socks_port = find_available_port()

    # 生成 xray 入站配置
    xray_in = _build_xray_inbound(inbound, socks_port)

    # 生成出站 bin 配置
    outbound_bin = node['bin_type']
    try:
        outbound_config = _build_outbound_config(node, socks_port, outbound_bin)
    except ValueError as e:
        return {'success': False, 'message': str(e)}

    # 配置目录
    config_dir = os.path.join('config', service['name'])

    return {
        'success': True,
        'service_name': service['name'],
        'config_dir': config_dir,
        'xray_in': xray_in,
        'outbound_bin': outbound_bin,
        'outbound_config': outbound_config,
        'socks_port': socks_port,
        'inbound_port': inbound['port'],
        'node_name': node['name'],
    }


def _get_outbound_node(outbound):
    """获取出站对应的节点"""
    if outbound['type'] == 'single':
        config = json.loads(outbound['config_json'])
        node_id = config.get('node_id')
        if node_id:
            conn = db.get_db()
            node = conn.execute('SELECT * FROM nodes WHERE id = ?', (node_id,)).fetchone()
            conn.close()
            return dict(node) if node else None
    elif outbound['type'] == 'auto':
        # 暂时用第一个节点
        pool = db.get_outbound_nodes(outbound['id'])
        if pool:
            return pool[0]
    return None


def _build_xray_inbound(inbound, socks_port):
    """生成 xray 入站配置（监听用户端口，出站指向本地 socks）"""
    protocol = inbound['protocol']
    port = inbound['port']
    listen_addr = inbound.get('listen_addr', '0.0.0.0')

    try:
        params = json.loads(inbound.get('params_json', '{}'))
    except (json.JSONDecodeError, TypeError):
        params = {}

    # 构建入站（xray 用 shadowsocks 而非 ss）
    xray_protocol = 'shadowsocks' if protocol == 'ss' else protocol
    inbound_config = {
        'protocol': xray_protocol,
        'port': port,
        'listen': listen_addr,
    }

    # 协议特定设置
    if protocol == 'ss':
        inbound_config['settings'] = {
            'method': params.get('method', 'aes-256-gcm'),
            'password': params.get('password', ''),
        }
    elif protocol == 'vmess':
        inbound_config['settings'] = {
            'clients': [{
                'id': params.get('id', ''),
                'alterId': params.get('aid', 0),
            }]
        }
        if params.get('network'):
            stream = {'network': params['network']}
            if params.get('ws_path'):
                stream['wsSettings'] = {'path': params['ws_path']}
            inbound_config['streamSettings'] = stream
    elif protocol in ('http', 'socks'):
        if params.get('username'):
            inbound_config['settings'] = {
                'accounts': [{
                    'user': params.get('username', ''),
                    'pass': params.get('password', ''),
                }]
            }

    # 完整 xray 配置：入站 + 出站(socks)
    config = {
        'inbounds': [inbound_config],
        'outbounds': [{
            'protocol': 'socks',
            'settings': {
                'servers': [{
                    'address': '127.0.0.1',
                    'port': socks_port
                }]
            }
        }]
    }

    return config


def _build_outbound_config(node, socks_port, bin_type):
    """生成出站 bin 的配置（socks 入站 → 实际出站）"""
    if bin_type == 'xray':
        return _build_xray_outbound(node, socks_port)
    elif bin_type == 'sslocal':
        return _build_sslocal_outbound(node, socks_port)
    elif bin_type == 'sing-box':
        return _build_singbox_outbound(node, socks_port)
    else:
        raise ValueError(f'unknown bin_type: {bin_type}')


def _build_xray_outbound(node, socks_port):
    """生成 xray 出站配置"""
    try:
        cfg = json.loads(node.get('config_json', '{}'))
    except (json.JSONDecodeError, TypeError):
        cfg = {}

    outbound = xray_build_outbound(node['protocol'], node['address'], node['port'], cfg)

    config = {
        'inbounds': [{
            'protocol': 'socks',
            'port': socks_port,
            'listen': '127.0.0.1'
        }],
        'outbounds': [outbound]
    }

    return config


def _build_sslocal_outbound(node, socks_port):
    """生成 sslocal 出站配置"""
    return generate_sslocal_config(node, socks_port)


def _build_singbox_outbound(node, socks_port):
    """生成 sing-box 出站配置"""
    return generate_singbox_config(node, socks_port)


def save_service_config(service_name, xray_in_config, outbound_bin, outbound_config):
    """保存配置文件到磁盘"""
    config_dir = os.path.join('config', service_name)
    os.makedirs(config_dir, exist_ok=True)

    # 保存 xray 入站配置
    xray_in_path = os.path.join(config_dir, 'xray_in.json')
    with open(xray_in_path, 'w', encoding='utf-8') as f:
        json.dump(xray_in_config, f, indent=2, ensure_ascii=False)

    # 保存出站配置
    outbound_filename = f'{outbound_bin}_out.json'
    outbound_path = os.path.join(config_dir, outbound_filename)
    with open(outbound_path, 'w', encoding='utf-8') as f:
        json.dump(outbound_config, f, indent=2, ensure_ascii=False)

    return {
        'xray_in': xray_in_path,
        'outbound': outbound_path,
        'outbound_bin': outbound_bin,
    }
