import urllib.request
import json
import os
import zipfile
import tempfile
import shutil

# 二进制 GitHub 仓库配置
BIN_REPOS = {
    'xray': {
        'repo': 'XTLS/Xray-core',
        'exe_names': ['xray.exe', 'xray'],
        'asset_patterns': {
            'windows-64': ['windows-64', 'windows-x64'],
            'linux-64': ['linux-64', 'linux-x64'],
        },
    },
    'sslocal': {
        'repo': 'shadowsocks/shadowsocks-rust',
        'exe_names': ['sslocal.exe', 'sslocal'],
        'asset_patterns': {
            'windows-64': ['x86_64-pc-windows'],
            'linux-64': ['x86_64-unknown-linux'],
        },
        'plugins': [
            {
                'name': 'obfs-local',
                'repo': 'shadowsocks/simple-obfs',
                'exe_names': ['obfs-local.exe', 'obfs-local'],
                'asset_patterns': {
                    'windows-64': ['obfs-local'],
                    'linux-64': ['obfs-local'],
                },
            },
        ],
    },
    'sing-box': {
        'repo': 'SagerNet/sing-box',
        'exe_names': ['sing-box.exe', 'sing-box'],
        'asset_patterns': {
            'windows-64': ['windows-amd64', 'windows-x64'],
            'linux-64': ['linux-amd64', 'linux-x64'],
        },
    },
}


def get_bin_dir():
    """获取 bin 目录路径"""
    return os.path.join(os.path.dirname(__file__), '..', 'bin')


def get_current_version(bin_name='xray'):
    """获取当前版本号"""
    from . import bin_manager
    version_str = bin_manager.get_version(bin_name)
    if not version_str or version_str == 'unknown':
        return None
    # 尝试解析版本号
    try:
        parts = version_str.split()
        for part in parts:
            if part[0].isdigit():
                return part.lstrip('v')
    except Exception:
        pass
    return None


def get_platform_key():
    """获取平台标识"""
    from . import bin_manager
    return bin_manager.get_platform()['key']


def check_platform_supported():
    """检查当前平台是否支持"""
    from . import bin_manager
    info = bin_manager.get_platform()
    return info['supported'], info['message'], info['key']


def check_update(bin_name='xray'):
    """检查指定二进制的最新版本"""
    repo_info = BIN_REPOS.get(bin_name)
    if not repo_info:
        return {'success': False, 'message': f'unknown binary: {bin_name}'}

    supported, message, platform_key = check_platform_supported()
    if not supported:
        return {'success': False, 'message': message, 'error_type': 'platform_not_supported'}

    github_api = f"https://api.github.com/repos/{repo_info['repo']}/releases/latest"

    try:
        req = urllib.request.Request(
            github_api,
            headers={'User-Agent': 'ProxyHub'}
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())

        # 解析 assets
        asset_patterns = repo_info.get('asset_patterns', {})
        assets = []
        for asset in data.get('assets', []):
            name = asset['name']
            # 跳过 sha256 校验文件
            if name.endswith('.sha256'):
                continue
            for platform_key, patterns in asset_patterns.items():
                if any(p in name for p in patterns):
                    assets.append({
                        'name': name,
                        'platform': platform_key,
                        'url': asset['browser_download_url'],
                        'size': asset['size']
                    })
                    break

        current_version = get_current_version(bin_name)
        latest_version = data['tag_name'].lstrip('v')

        is_latest = False
        if current_version and latest_version:
            is_latest = current_version == latest_version

        # 检查插件状态
        plugins_status = []
        for plugin in repo_info.get('plugins', []):
            plugin_exists = False
            for exe_name in plugin['exe_names']:
                if os.path.exists(os.path.join(get_bin_dir(), exe_name)):
                    plugin_exists = True
                    break
            plugins_status.append({
                'name': plugin['name'],
                'exists': plugin_exists
            })

        return {
            'success': True,
            'bin_name': bin_name,
            'tag_name': data['tag_name'],
            'published_at': data['published_at'][:10],
            'assets': assets,
            'current_version': current_version,
            'is_latest': is_latest,
            'plugins': plugins_status
        }
    except Exception as e:
        return {'success': False, 'message': str(e)}


def download_binary(bin_name='xray', progress_callback=None):
    """下载指定二进制的最新版本"""
    repo_info = BIN_REPOS.get(bin_name)
    if not repo_info:
        return {'success': False, 'message': f'unknown binary: {bin_name}'}

    supported, message, platform_key = check_platform_supported()
    if not supported:
        return {'success': False, 'message': message}

    update_info = check_update(bin_name)
    if not update_info['success']:
        return update_info

    bin_dir = get_bin_dir()

    # 即使主程序已是最新，也要检查并下载缺失的插件
    plugins = repo_info.get('plugins', [])
    plugins_downloaded = []
    for plugin in plugins:
        plugin_missing = True
        for exe_name in plugin['exe_names']:
            if os.path.exists(os.path.join(bin_dir, exe_name)):
                plugin_missing = False
                break
        if plugin_missing:
            try:
                _download_plugin(plugin, platform_key, bin_dir)
                plugins_downloaded.append(plugin['name'])
            except Exception:
                pass

    if update_info.get('is_latest'):
        if plugins_downloaded:
            return {'success': True, 'bin_name': bin_name, 'version': update_info['current_version'],
                    'message': 'plugins downloaded: ' + ', '.join(plugins_downloaded)}
        return {'success': False, 'message': 'already_latest', 'current': update_info['current_version']}

    # 找到对应平台的 asset
    asset = None
    for a in update_info['assets']:
        if a['platform'] == platform_key:
            asset = a
            break

    if not asset:
        return {'success': False, 'message': f'no asset found for platform: {platform_key}'}

    try:
        # 下载主程序
        _download_and_extract(asset, repo_info['exe_names'], bin_dir)

        # 下载插件
        for plugin in plugins:
            _download_plugin(plugin, platform_key, bin_dir)

        return {
            'success': True,
            'bin_name': bin_name,
            'version': update_info['tag_name'],
            'path': bin_dir
        }
    except Exception as e:
        return {'success': False, 'message': str(e)}


def _download_and_extract(asset, exe_names, bin_dir):
    """下载并解压单个二进制"""
    temp_dir = tempfile.mkdtemp()
    try:
        zip_path = os.path.join(temp_dir, asset['name'])

        req = urllib.request.Request(
            asset['url'],
            headers={'User-Agent': 'ProxyHub'}
        )

        with urllib.request.urlopen(req, timeout=60) as resp:
            total_size = int(resp.headers.get('Content-Length', 0))
            downloaded = 0
            chunk_size = 8192

            with open(zip_path, 'wb') as f:
                while True:
                    chunk = resp.read(chunk_size)
                    if not chunk:
                        break
                    f.write(chunk)
                    downloaded += len(chunk)

        # 解压到 bin 目录
        os.makedirs(bin_dir, exist_ok=True)

        with zipfile.ZipFile(zip_path, 'r') as zf:
            for name in zf.namelist():
                basename = os.path.basename(name)
                if basename in exe_names:
                    target_path = os.path.join(bin_dir, basename)
                    with zf.open(name) as src, open(target_path, 'wb') as dst:
                        dst.write(src.read())
                    break
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def _download_plugin(plugin_info, platform_key, bin_dir):
    """下载插件"""
    repo = plugin_info['repo']
    exe_names = plugin_info['exe_names']
    asset_patterns = plugin_info.get('asset_patterns', {})

    # 检查插件是否已存在
    for exe_name in exe_names:
        if os.path.exists(os.path.join(bin_dir, exe_name)):
            return  # 已存在，跳过

    github_api = f"https://api.github.com/repos/{repo}/releases/latest"

    try:
        req = urllib.request.Request(
            github_api,
            headers={'User-Agent': 'ProxyHub'}
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())

        # 找到对应平台的 asset
        asset = None
        for a in data.get('assets', []):
            name = a['name']
            if name.endswith('.sha256'):
                continue
            patterns = asset_patterns.get(platform_key, [])
            if any(p in name for p in patterns):
                asset = {
                    'name': name,
                    'url': a['browser_download_url'],
                    'size': a['size']
                }
                break

        if asset:
            _download_and_extract(asset, exe_names, bin_dir)
    except Exception:
        pass  # 插件下载失败不阻塞主程序
