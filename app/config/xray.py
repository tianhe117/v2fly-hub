import json


def generate_xray_config(node, local_port):
    """生成 Xray 配置

    支持协议: vmess, vless, trojan
    """
    protocol = node['protocol']
    address = node['address']
    port = node['port']

    try:
        cfg = json.loads(node.get('config_json', '{}'))
    except (json.JSONDecodeError, TypeError):
        cfg = {}

    # 生成出站配置
    outbound = _build_outbound(protocol, address, port, cfg)

    config = {
        "inbounds": [{
            "protocol": "socks",
            "port": local_port,
            "listen": "127.0.0.1"
        }],
        "outbounds": [outbound]
    }

    return config


def _build_outbound(protocol, address, port, cfg):
    """构建出站配置"""
    if protocol == 'vmess':
        return _build_vmess(address, port, cfg)
    elif protocol == 'vless':
        return _build_vless(address, port, cfg)
    elif protocol == 'trojan':
        return _build_trojan(address, port, cfg)
    else:
        raise ValueError(f'xray does not support protocol: {protocol}')


def _build_vmess(address, port, cfg):
    """构建 VMess 出站"""
    stream_settings = _build_stream_settings(cfg)

    outbound = {
        "protocol": "vmess",
        "settings": {
            "vnext": [{
                "address": address,
                "port": port,
                "users": [{
                    "id": cfg.get('id', ''),
                    "alterId": cfg.get('aid', 0),
                    "security": cfg.get('security', 'auto')
                }]
            }]
        },
        "streamSettings": stream_settings
    }

    return outbound


def _build_vless(address, port, cfg):
    """构建 VLESS 出站"""
    stream_settings = _build_stream_settings(cfg)

    user = {
        "id": cfg.get('id', ''),
        "encryption": cfg.get('encryption', 'none')
    }
    if cfg.get('flow'):
        user['flow'] = cfg['flow']

    outbound = {
        "protocol": "vless",
        "settings": {
            "vnext": [{
                "address": address,
                "port": port,
                "users": [user]
            }]
        },
        "streamSettings": stream_settings
    }

    return outbound


def _build_trojan(address, port, cfg):
    """构建 Trojan 出站"""
    stream_settings = _build_stream_settings(cfg)

    outbound = {
        "protocol": "trojan",
        "settings": {
            "servers": [{
                "address": address,
                "port": port,
                "password": cfg.get('password', '')
            }]
        },
        "streamSettings": stream_settings
    }

    return outbound


def _build_stream_settings(cfg):
    """构建传输层配置"""
    network = cfg.get('network', 'tcp')

    stream = {
        "network": network,
        "security": "tls" if cfg.get('tls') else "none"
    }

    # TLS 设置
    if cfg.get('tls'):
        tls_settings = {}
        if cfg.get('sni'):
            tls_settings['serverName'] = cfg['sni']
        if cfg.get('allowInsecure'):
            tls_settings['allowInsecure'] = True
        if cfg.get('fingerprint'):
            tls_settings['fingerprint'] = cfg['fingerprint']
        if cfg.get('alpn'):
            alpn = cfg['alpn']
            if isinstance(alpn, str):
                alpn = [x.strip() for x in alpn.split(',')]
            tls_settings['alpn'] = alpn
        if tls_settings:
            stream['tlsSettings'] = tls_settings

    # 传输层设置
    if network == 'ws':
        ws_settings = {}
        if cfg.get('ws_host'):
            ws_settings['headers'] = {'Host': cfg['ws_host']}
        if cfg.get('ws_path'):
            ws_settings['path'] = cfg['ws_path']
        if ws_settings:
            stream['wsSettings'] = ws_settings

    elif network in ('h2', 'http'):
        h2_settings = {}
        if cfg.get('h2_host'):
            host = cfg['h2_host']
            if isinstance(host, str):
                host = [host]
            h2_settings['host'] = host
        if cfg.get('h2_path'):
            h2_settings['path'] = cfg['h2_path']
        if h2_settings:
            stream['httpSettings'] = h2_settings

    elif network == 'grpc':
        grpc_settings = {}
        if cfg.get('grpc_service_name'):
            grpc_settings['serviceName'] = cfg['grpc_service_name']
        if grpc_settings:
            stream['grpcSettings'] = grpc_settings

    return stream
