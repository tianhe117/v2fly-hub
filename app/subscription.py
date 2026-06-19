import urllib.request
import base64
import json
import yaml

# 协议→二进制映射
BIN_TYPE_MAP = {
    'vmess': 'xray',
    'vless': 'xray',
    'trojan': 'xray',
    'ss': 'xray',
    'ssr': 'xray',
    'hysteria': 'sing-box',
    'hysteria2': 'sing-box',
    'hy2': 'sing-box',
    'tuic': 'sing-box',
    'anytls': 'xray',
}


def fetch_subscription(url):
    """从 URL 获取订阅内容"""
    try:
        import ssl
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

        # 使用 Clash User-Agent 以获取流量信息 header
        req = urllib.request.Request(url, headers={
            'User-Agent': 'ClashForAndroid/2.5.12',
            'Accept': '*/*'
        })
        with urllib.request.urlopen(req, timeout=30, context=ctx) as resp:
            content = resp.read().decode('utf-8')
            headers = resp.headers

        # 解析流量和过期信息
        info = {}
        user_info = headers.get('subscription-userinfo', '') or headers.get('Subscription-Userinfo', '')

        if user_info:
            # format: upload=0; download=123; total=456; expire=789
            for item in user_info.split(';'):
                if '=' in item:
                    key, value = item.strip().split('=', 1)
                    try:
                        info[key] = int(value)
                    except ValueError:
                        pass

        # 尝试 base64 解码
        try:
            # 补齐 padding
            padding = 4 - len(content) % 4
            if padding != 4:
                content += '=' * padding
            decoded = base64.b64decode(content).decode('utf-8')
            # 检查解码后是否包含 vmess:// 或 ss://
            if 'vmess://' in decoded or 'ss://' in decoded:
                content = decoded
        except Exception:
            pass

        return {'success': True, 'content': content, 'info': info}
    except Exception as e:
        return {'success': False, 'message': str(e)}


def parse_nodes(content):
    """解析订阅内容，返回节点列表"""
    nodes = []

    # 检测是否为 Clash 格式
    if content.strip().startswith('mixed-port:') or 'proxies:' in content:
        return parse_clash_nodes(content)

    # 标准格式（base64 编码的链接）
    lines = content.strip().split('\n')

    for line in lines:
        line = line.strip()
        if not line:
            continue

        if line.startswith('vmess://'):
            node = decode_vmess(line)
            if node:
                nodes.append(node)
        elif line.startswith('ss://'):
            node = decode_ss(line)
            if node:
                nodes.append(node)

    return nodes


def parse_clash_nodes(content):
    """解析 Clash 格式的节点配置（使用 PyYAML）"""
    try:
        config = yaml.safe_load(content)
    except Exception:
        # YAML 解析失败，尝试只解析 proxies 部分
        try:
            idx = content.find('proxies:')
            if idx < 0:
                return []
            lines = content[idx:].split('\n')
            proxy_lines = ['proxies:']
            for line in lines[1:]:
                stripped = line.rstrip()
                if stripped and not stripped[0].isspace() and not stripped.startswith('-'):
                    break
                proxy_lines.append(line)
            proxy_content = '\n'.join(proxy_lines)
            config = yaml.safe_load(proxy_content)
        except Exception:
            return []

    proxies = config.get('proxies', [])
    if not proxies:
        return []

    result = []
    for proxy in proxies:
        if not isinstance(proxy, dict):
            continue

        node = parse_clash_node(proxy)
        if node:
            result.append(node)

    return result


def parse_clash_node(proxy):
    """解析单个 Clash 节点（参考 passwall2）"""
    name = proxy.get('name', 'unknown')
    node_type = proxy.get('type', '').lower()
    server = proxy.get('server', '')
    port = int(proxy.get('port', 0))

    if not server or not port:
        return None

    # 获取公共的 TLS 相关配置
    tls = proxy.get('tls', False)
    skip_cert_verify = proxy.get('skip-cert-verify', False)
    sni = proxy.get('sni', '')

    if node_type == 'ss':
        cfg = {
            'method': proxy.get('cipher', 'aes-256-gcm'),
            'password': proxy.get('password', ''),
        }
        # 处理插件
        plugin = proxy.get('plugin', '')
        if plugin:
            cfg['plugin'] = plugin
            plugin_opts = proxy.get('plugin-opts', {})
            if plugin_opts:
                opts = []
                if 'mode' in plugin_opts:
                    opts.append(f"obfs={plugin_opts['mode']}")
                if 'host' in plugin_opts:
                    opts.append(f"obfs-host={plugin_opts['host']}")
                cfg['plugin_opts'] = ';'.join(opts)
        return {
            'name': name,
            'protocol': 'ss',
            'address': server,
            'port': port,
            'config_json': json.dumps(cfg),
            'bin_type': BIN_TYPE_MAP.get('ss', 'xray')
        }

    elif node_type == 'ssr':
        cfg = {
            'method': proxy.get('cipher', 'aes-256-gcm'),
            'password': proxy.get('password', ''),
            'obfs': proxy.get('obfs', ''),
            'protocol': proxy.get('protocol', ''),
            'obfs_param': proxy.get('obfs-param', ''),
            'protocol_param': proxy.get('protocol-param', ''),
        }
        return {
            'name': name,
            'protocol': 'ssr',
            'address': server,
            'port': port,
            'config_json': json.dumps(cfg),
            'bin_type': BIN_TYPE_MAP.get('ssr', 'xray')
        }

    elif node_type == 'vmess':
        # 处理传输层
        network = proxy.get('network', 'tcp')
        ws_opts = proxy.get('ws-opts') or {}
        h2_opts = proxy.get('h2-opts') or {}
        grpc_opts = proxy.get('grpc-opts') or {}

        cfg = {
            'id': proxy.get('uuid', ''),
            'aid': int(proxy.get('alterId', 0)),
            'security': proxy.get('cipher', 'auto'),
            'network': network,
            'tls': bool(tls),
            'sni': sni,
            'skip_cert_verify': bool(skip_cert_verify),
        }

        # WebSocket
        if network == 'ws' and ws_opts:
            headers = ws_opts.get('headers') or {}
            cfg['ws_host'] = headers.get('Host', '')
            cfg['ws_path'] = ws_opts.get('path', '')

        # HTTP/2
        elif network == 'h2' and h2_opts:
            cfg['h2_host'] = h2_opts.get('host', [])
            cfg['h2_path'] = h2_opts.get('path', '')

        # gRPC
        elif network == 'grpc' and grpc_opts:
            cfg['grpc_service_name'] = grpc_opts.get('grpc-service-name', '')

        return {
            'name': name,
            'protocol': 'vmess',
            'address': server,
            'port': port,
            'config_json': json.dumps(cfg),
            'bin_type': BIN_TYPE_MAP.get('vmess', 'xray')
        }

    elif node_type == 'vless':
        network = proxy.get('network', 'tcp')
        ws_opts = proxy.get('ws-opts') or {}
        grpc_opts = proxy.get('grpc-opts') or {}
        reality_opts = proxy.get('reality-opts') or {}

        cfg = {
            'id': proxy.get('uuid', ''),
            'flow': proxy.get('flow', ''),
            'encryption': proxy.get('encryption', 'none'),
            'network': network,
            'tls': bool(tls),
            'sni': sni or proxy.get('servername', ''),
            'skip_cert_verify': bool(skip_cert_verify),
        }

        # Reality
        if reality_opts:
            cfg['reality'] = True
            cfg['reality_public_key'] = reality_opts.get('public-key', '')
            cfg['reality_short_id'] = reality_opts.get('short-id', '')

        # WebSocket
        if network == 'ws' and ws_opts:
            headers = ws_opts.get('headers') or {}
            cfg['ws_host'] = headers.get('Host', '')
            cfg['ws_path'] = ws_opts.get('path', '')

        # gRPC
        elif network == 'grpc' and grpc_opts:
            cfg['grpc_service_name'] = grpc_opts.get('grpc-service-name', '')

        return {
            'name': name,
            'protocol': 'vless',
            'address': server,
            'port': port,
            'config_json': json.dumps(cfg),
            'bin_type': BIN_TYPE_MAP.get('vless', 'xray')
        }

    elif node_type == 'trojan':
        network = proxy.get('network', 'tcp')
        ws_opts = proxy.get('ws-opts') or {}
        grpc_opts = proxy.get('grpc-opts') or {}

        cfg = {
            'password': proxy.get('password', ''),
            'sni': sni,
            'alpn': proxy.get('alpn', []),
            'skip_cert_verify': bool(skip_cert_verify),
            'network': network,
        }

        # WebSocket
        if network == 'ws' and ws_opts:
            headers = ws_opts.get('headers') or {}
            cfg['ws_host'] = headers.get('Host', '')
            cfg['ws_path'] = ws_opts.get('path', '')

        # gRPC
        elif network == 'grpc' and grpc_opts:
            cfg['grpc_service_name'] = grpc_opts.get('grpc-service-name', '')

        return {
            'name': name,
            'protocol': 'trojan',
            'address': server,
            'port': port,
            'config_json': json.dumps(cfg),
            'bin_type': BIN_TYPE_MAP.get('trojan', 'xray')
        }

    elif node_type in ('hysteria', 'hysteria2', 'hy2'):
        cfg = {
            'password': proxy.get('password', '') or proxy.get('auth', ''),
            'sni': sni,
            'skip_cert_verify': bool(skip_cert_verify),
            'up_mbps': proxy.get('up-mbps', 100),
            'down_mbps': proxy.get('down-mbps', 100),
        }

        # Hysteria2 混淆
        obfs = proxy.get('obfs', '')
        if obfs:
            cfg['obfs'] = obfs
            cfg['obfs_password'] = proxy.get('obfs-password', '')

        return {
            'name': name,
            'protocol': node_type,
            'address': server,
            'port': port,
            'config_json': json.dumps(cfg),
            'bin_type': BIN_TYPE_MAP.get(node_type, 'sing-box')
        }

    elif node_type == 'tuic':
        cfg = {
            'uuid': proxy.get('uuid', ''),
            'password': proxy.get('password', ''),
            'sni': sni,
            'skip_cert_verify': bool(skip_cert_verify),
            'alpn': proxy.get('alpn', []),
            'congestion_control': proxy.get('congestion-control', 'cubic'),
            'udp_relay_mode': proxy.get('udp-relay-mode', 'native'),
        }
        return {
            'name': name,
            'protocol': 'tuic',
            'address': server,
            'port': port,
            'config_json': json.dumps(cfg),
            'bin_type': BIN_TYPE_MAP.get('tuic', 'sing-box')
        }

    elif node_type == 'anytls':
        cfg = {
            'password': proxy.get('password', ''),
            'sni': sni,
            'skip_cert_verify': bool(skip_cert_verify),
        }
        return {
            'name': name,
            'protocol': 'anytls',
            'address': server,
            'port': port,
            'config_json': json.dumps(cfg),
            'bin_type': BIN_TYPE_MAP.get('anytls', 'xray')
        }

    # 未知类型，跳过
    return None


def decode_vmess(vmess_url):
    """解码 vmess 链接"""
    try:
        # vmess:// 后面是 base64 编码的 JSON
        b64_str = vmess_url[8:]
        # 补齐 padding
        padding = 4 - len(b64_str) % 4
        if padding != 4:
            b64_str += '=' * padding
        json_str = base64.b64decode(b64_str).decode('utf-8')
        config = json.loads(json_str)

        name = config.get('ps', 'unknown')
        address = config.get('add', '')
        port = int(config.get('port', 443))

        return {
            'name': name,
            'protocol': 'vmess',
            'address': address,
            'port': port,
            'config_json': json.dumps({
                'id': config.get('id', ''),
                'aid': int(config.get('aid', 0)),
                'net': config.get('net', 'tcp'),
                'type': config.get('type', 'none'),
                'host': config.get('host', ''),
                'path': config.get('path', ''),
                'tls': config.get('tls', '')
            }),
            'bin_type': 'xray'
        }
    except Exception:
        return None


def decode_ss(ss_url):
    """解码 ss 链接"""
    try:
        # ss://base64(method:password)@server:port#name
        # 或 ss://base64(method:password@server:port)#name
        content = ss_url[5:]
        name = ''
        plugin = ''

        # 分离 fragment
        if '#' in content:
            content, name = content.split('#', 1)
            name = urllib.request.unquote(name)

        # 分离 query 参数（plugin 等）
        if '?' in content:
            content, query = content.split('?', 1)
            # 解析 plugin 参数
            for param in query.split('&'):
                if param.startswith('plugin='):
                    plugin = urllib.request.unquote(param[7:])

        # 解析 @server:port 格式
        if '@' in content:
            b64_part, server_part = content.split('@', 1)
            # 补齐 padding
            padding = 4 - len(b64_part) % 4
            if padding != 4:
                b64_part += '=' * padding
            decoded = base64.b64decode(b64_part).decode('utf-8')
            method, password = decoded.split(':', 1)

            # 解析 server:port（去掉末尾的 /）
            server_part = server_part.rstrip('/')
            if ':' in server_part:
                address, port = server_part.rsplit(':', 1)
                port = int(port)
            else:
                address = server_part
                port = 8388
        else:
            # 整个内容是 base64
            padding = 4 - len(content) % 4
            if padding != 4:
                content += '=' * padding
            decoded = base64.b64decode(content).decode('utf-8')

            if '@' in decoded:
                method_pass, server_port = decoded.split('@', 1)
                method, password = method_pass.split(':', 1)
                if ':' in server_port:
                    address, port = server_port.rsplit(':', 1)
                    port = int(port)
                else:
                    address = server_port
                    port = 8388
            else:
                return None

        if not name:
            name = f'{address}:{port}'

        config = {
            'method': method,
            'password': password
        }
        if plugin:
            config['plugin'] = plugin

        return {
            'name': name,
            'protocol': 'ss',
            'address': address,
            'port': port,
            'config_json': json.dumps(config),
            'bin_type': 'xray'
        }
    except Exception:
        return None
