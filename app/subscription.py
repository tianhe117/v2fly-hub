import urllib.request
import base64
import json


def fetch_subscription(url):
    """从 URL 获取订阅内容"""
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=15) as resp:
            content = resp.read().decode('utf-8')

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

        return {'success': True, 'content': content}
    except Exception as e:
        return {'success': False, 'message': str(e)}


def parse_nodes(content):
    """解析订阅内容，返回节点列表"""
    nodes = []
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

        # 分离 fragment
        if '#' in content:
            content, name = content.split('#', 1)
            name = urllib.request.unquote(name)

        # 解析 @server:port 格式
        if '@' in content:
            b64_part, server_part = content.split('@', 1)
            # 补齐 padding
            padding = 4 - len(b64_part) % 4
            if padding != 4:
                b64_part += '=' * padding
            decoded = base64.b64decode(b64_part).decode('utf-8')
            method, password = decoded.split(':', 1)

            # 解析 server:port
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

        return {
            'name': name,
            'protocol': 'ss',
            'address': address,
            'port': port,
            'config_json': json.dumps({
                'method': method,
                'password': password
            })
        }
    except Exception:
        return None
