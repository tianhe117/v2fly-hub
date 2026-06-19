import socket
import json
import time
import urllib.request
import ssl
import os
import subprocess
import random
from concurrent.futures import ThreadPoolExecutor, as_completed
from . import db
from . import bin_manager
from .config import generate_config, write_temp_config, cleanup_temp_config


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

        # TCP 检测（直接连接目标服务器）
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(tcp_timeout)
            start = time.time()
            sock.connect((node['address'], node['port']))
            tcp_ms = int((time.time() - start) * 1000)
            sock.close()
        except:
            tcp_ms = -1

        # Curl 检测（通过临时本地代理）
        if tcp_ms and tcp_ms > 0:
            curl_ms = _check_curl_via_proxy(node, curl_timeout, test_url)

        # 更新数据库
        db.update_node_latency(node['id'], tcp_ms, curl_ms)

        return {
            'id': node['id'],
            'name': node['name'],
            'tcp': tcp_ms,
            'curl': curl_ms
        }

    # 并行检测（限制并发数，避免同时启动太多进程）
    with ThreadPoolExecutor(max_workers=5) as executor:
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


def _check_curl_via_proxy(node, curl_timeout, test_url):
    """通过启动临时本地代理进程来检测 curl 延迟

    Returns:
        int: 延迟毫秒数，失败返回 -1
    """
    bin_type = node.get('bin_type', 'xray')
    bin_path = bin_manager.get_bin_path(bin_type)

    if not bin_path or not os.path.exists(bin_path):
        return -1

    config_path = None
    process = None

    try:
        # 生成配置
        result = generate_config(node)
        config = result['config']
        local_port = result['local_port']

        # 写入临时配置文件
        config_path = write_temp_config(config, bin_type)

        # 启动临时进程
        reg = bin_manager.BIN_REGISTRY.get(bin_type)
        if not reg:
            return -1

        args = [bin_path] + [a.replace('{config}', config_path) for a in reg['run_args']]

        process = subprocess.Popen(
            args,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
        )

        # 等待进程启动
        time.sleep(1.0)

        if process.poll() is not None:
            return -1

        # 通过本地代理检测
        proxy_url = f"socks5://127.0.0.1:{local_port}"

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

        return curl_ms

    except:
        return -1

    finally:
        # 清理进程
        if process:
            try:
                process.terminate()
                process.wait(timeout=3)
            except:
                try:
                    process.kill()
                except:
                    pass

        # 清理临时配置文件
        cleanup_temp_config(config_path)
