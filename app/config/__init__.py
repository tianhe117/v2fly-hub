import json
import os
import random


def generate_config(node, local_port=0):
    """根据节点 bin_type 生成对应配置

    Args:
        node: 节点字典，包含 protocol, address, port, config_json, bin_type
        local_port: 本地 SOCKS 代理端口，0 表示随机分配

    Returns:
        dict: {
            'config': dict,       # 配置内容
            'config_path': str,   # 临时配置文件路径
            'local_port': int,    # 本地代理端口
        }
    """
    if not local_port:
        local_port = random.randint(10000, 60000)

    bin_type = node.get('bin_type', 'xray')

    if bin_type == 'xray':
        from .xray import generate_xray_config
        config = generate_xray_config(node, local_port)
    elif bin_type == 'sslocal':
        from .sslocal import generate_sslocal_config
        config = generate_sslocal_config(node, local_port)
    elif bin_type == 'sing-box':
        from .singbox import generate_singbox_config
        config = generate_singbox_config(node, local_port)
    else:
        raise ValueError(f'unknown bin_type: {bin_type}')

    return {
        'config': config,
        'local_port': local_port,
        'bin_type': bin_type,
    }


def write_temp_config(config, bin_type):
    """将配置写入临时文件

    Returns:
        str: 临时配置文件路径
    """
    import tempfile
    config_dir = os.path.join(tempfile.gettempdir(), 'proxyhub')
    os.makedirs(config_dir, exist_ok=True)

    # sslocal 用 JSON，其他也用 JSON
    config_path = os.path.join(config_dir, f'{bin_type}_{random.randint(1000, 9999)}.json')
    with open(config_path, 'w', encoding='utf-8') as f:
        json.dump(config, f, indent=2)

    return config_path


def cleanup_temp_config(config_path):
    """清理临时配置文件"""
    try:
        if config_path and os.path.exists(config_path):
            os.remove(config_path)
    except OSError:
        pass
