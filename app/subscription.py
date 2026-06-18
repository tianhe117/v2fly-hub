import urllib.request
import base64
import json


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
    """解析 Clash 格式的节点配置"""
    nodes = []

    # 简单的 YAML 解析（不依赖 pyyaml）
    in_proxies = False
    current_node = None

    for line in content.split('\n'):
        line = line.rstrip()

        # 找到 proxies: 部分
        if line.strip() == 'proxies:':
            in_proxies = True
            continue

        if not in_proxies:
            continue

        # 遇到新的顶级 key，结束解析
        if line and not line.startswith(' ') and not line.startswith('-'):
            break

        # 解析节点
        if line.strip().startswith('- {') or line.strip().startswith('-{'):
            # 单行格式: - {name: xxx, type: ss, ...}
            if current_node:
                nodes.append(current_node)

            # 提取花括号内的内容
            start = line.index('{')
            end = line.rindex('}')
            items_str = line[start+1:end]

            current_node = {}
            for item in items_str.split(','):
                if ':' in item:
                    key, value = item.split(':', 1)
                    current_node[key.strip()] = value.strip().strip('\'\"')

        elif line.strip().startswith('- name:'):
            # 多行格式开始
            if current_node:
                nodes.append(current_node)

            current_node = {'name': line.split(':', 1)[1].strip().strip('\'\"')}

        elif current_node and ':' in line:
            # 多行格式的属性
            key, value = line.split(':', 1)
            key = key.strip()
            value = value.strip().strip('\'\"')
            if key and value:
                current_node[key] = value

    # 添加最后一个节点
    if current_node:
        nodes.append(current_node)

    # 转换为标准格式
    result = []
    for node in nodes:
        name = node.get('name', 'unknown')
        node_type = node.get('type', '').lower()
        server = node.get('server', '')
        port = int(node.get('port', 0))

        if not server or not port:
            continue

        if node_type == 'ss':
            config = {
                'method': node.get('cipher', 'aes-256-gcm'),
                'password': node.get('password', '')
            }
            result.append({
                'name': name,
                'protocol': 'ss',
                'address': server,
                'port': port,
                'config_json': json.dumps(config)
            })
        elif node_type == 'vmess':
            config = {
                'id': node.get('uuid', ''),
                'aid': int(node.get('alterId', 0)),
                'net': node.get('network', 'tcp'),
                'type': node.get('network', 'none'),
                'host': node.get('ws-opts', {}).get('headers', {}).get('Host', ''),
                'path': node.get('ws-opts', {}).get('path', ''),
                'tls': 'tls' if node.get('tls', False) else ''
            }
            result.append({
                'name': name,
                'protocol': 'vmess',
                'address': server,
                'port': port,
                'config_json': json.dumps(config)
            })

    return result


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
            })
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
            'config_json': json.dumps(config)
        }
    except Exception:
        return None
