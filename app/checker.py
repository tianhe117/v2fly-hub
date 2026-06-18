import socket
import json
import time
import urllib.request
import ssl
from concurrent.futures import ThreadPoolExecutor, as_completed
from . import db


def check_nodes(node_ids=None, check_all=False):
    """检测节点延迟

    Args:
        node_ids: 要检测的节点 ID 列表
        check_all: 是否检测所有节点

    Returns:
        检测结果列表
    """
    if check_all:
        nodes = db.get_all_nodes()
    else:
        nodes = []
        for nid in (node_ids or []):
            conn = db.get_db()
            node = conn.execute('SELECT * FROM nodes WHERE id = ?', (nid,)).fetchone()
            conn.close()
            if node:
                nodes.append(dict(node))

    if not nodes:
        return []

    settings = db.get_all_settings()
    tcp_timeout = int(settings.get('tcp_timeout', 3))
    curl_timeout = int(settings.get('curl_timeout', 10))
    test_url = settings.get('test_url', 'http://www.gstatic.com/generate_204')

    results = []

    def check_one(node):
        """检测单个节点"""
        tcp_ms = None
        curl_ms = None

        # TCP 检测
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(tcp_timeout)
            start = time.time()
            sock.connect((node['address'], node['port']))
            tcp_ms = int((time.time() - start) * 1000)
            sock.close()
        except:
            tcp_ms = -1

        # Curl 检测（通过代理）
        if tcp_ms and tcp_ms > 0:
            try:
                config = json.loads(node['config_json'])
                proxy_url = f"socks5://{node['address']}:{node['port']}"

                ctx = ssl.create_default_context()
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_NONE

                proxy_handler = urllib.request.ProxyHandler({
                    'http': proxy_url,
                    'https': proxy_url
                })
                opener = urllib.request.build_opener(proxy_handler)

                start = time.time()
                req = urllib.request.Request(test_url)
                opener.open(req, timeout=curl_timeout)
                curl_ms = int((time.time() - start) * 1000)
            except:
                curl_ms = -1

        # 更新数据库
        db.update_node_latency(node['id'], tcp_ms, curl_ms)

        return {
            'id': node['id'],
            'name': node['name'],
            'tcp': tcp_ms,
            'curl': curl_ms
        }

    # 并行检测
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = {executor.submit(check_one, node): node for node in nodes}
        for future in as_completed(futures):
            try:
                result = future.result()
                results.append(result)
            except Exception as e:
                node = futures[future]
                results.append({
                    'id': node['id'],
                    'name': node['name'],
                    'tcp': -1,
                    'curl': -1
                })

    return results
