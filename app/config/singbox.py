import json


def generate_singbox_config(node, local_port):
    """生成 sing-box 配置

    支持协议: hysteria2, tuic
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
            "type": "socks",
            "listen": "127.0.0.1",
            "listen_port": local_port
        }],
        "outbounds": [outbound]
    }

    return config


def _build_outbound(protocol, address, port, cfg):
    """构建出站配置"""
    if protocol in ('hysteria2', 'hy2', 'hysteria'):
        return _build_hysteria2(address, port, cfg)
    elif protocol == 'tuic':
        return _build_tuic(address, port, cfg)
    else:
        raise ValueError(f'sing-box does not support protocol: {protocol}')


def _build_hysteria2(address, port, cfg):
    """构建 Hysteria2 出站"""
    outbound = {
        "type": "hysteria2",
        "server": address,
        "server_port": port,
        "password": cfg.get('password', ''),
    }

    # TLS (sing-box 用 server_name，不是 sni)
    tls = {}
    if cfg.get('sni'):
        tls['server_name'] = cfg['sni']
    if cfg.get('skip_cert_verify'):
        tls['insecure'] = True
    if cfg.get('alpn'):
        alpn = cfg['alpn']
        if isinstance(alpn, str):
            alpn = [x.strip() for x in alpn.split(',')]
        tls['alpn'] = alpn
    if tls:
        tls['enabled'] = True
        outbound['tls'] = tls

    # 带宽设置
    if cfg.get('up_mbps'):
        outbound['up_mbps'] = cfg['up_mbps']
    if cfg.get('down_mbps'):
        outbound['down_mbps'] = cfg['down_mbps']

    # 混淆
    obfs = cfg.get('obfs', '')
    if obfs:
        outbound['obfs'] = {
            "type": obfs,
            "password": cfg.get('obfs_password', '')
        }

    return outbound


def _build_tuic(address, port, cfg):
    """构建 TUIC 出站"""
    outbound = {
        "type": "tuic",
        "server": address,
        "server_port": port,
        "uuid": cfg.get('uuid', ''),
        "password": cfg.get('password', ''),
    }

    # TLS (sing-box 用 server_name)
    tls = {}
    if cfg.get('sni'):
        tls['server_name'] = cfg['sni']
    if cfg.get('skip_cert_verify'):
        tls['insecure'] = True
    if cfg.get('alpn'):
        alpn = cfg['alpn']
        if isinstance(alpn, str):
            alpn = [x.strip() for x in alpn.split(',')]
        tls['alpn'] = alpn
    if tls:
        tls['enabled'] = True
        outbound['tls'] = tls

    # 拥塞控制
    if cfg.get('congestion_control'):
        outbound['congestion_control'] = cfg['congestion_control']

    # UDP relay mode
    if cfg.get('udp_relay_mode'):
        outbound['udp_relay_mode'] = cfg['udp_relay_mode']

    return outbound
