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
    },
    'sslocal': {
        'repo': 'shadowsocks/shadowsocks-rust',
        'exe_names': ['sslocal.exe', 'sslocal'],
    },
    'sing-box': {
        'repo': 'SagerNet/sing-box',
        'exe_names': ['sing-box.exe', 'sing-box'],
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
        assets = []
        for asset in data.get('assets', []):
            name = asset['name']
            if 'linux-64' in name or 'windows-64' in name or 'linux-amd64' in name or 'windows-amd64' in name:
                if 'linux' in name:
                    platform = 'linux-64'
                else:
                    platform = 'windows-64'
                assets.append({
                    'name': name,
                    'platform': platform,
                    'url': asset['browser_download_url'],
                    'size': asset['size']
                })

        current_version = get_current_version(bin_name)
        latest_version = data['tag_name'].lstrip('v')

        is_latest = False
        if current_version and latest_version:
            is_latest = current_version == latest_version

        return {
            'success': True,
            'bin_name': bin_name,
            'tag_name': data['tag_name'],
            'published_at': data['published_at'][:10],
            'assets': assets,
            'current_version': current_version,
            'is_latest': is_latest
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

    if update_info.get('is_latest'):
        return {'success': False, 'message': 'already_latest', 'current': update_info['current_version']}

    # 找到对应平台的 asset
    asset = None
    for a in update_info['assets']:
        if a['platform'] == platform_key:
            asset = a
            break

    if not asset:
        return {'success': False, 'message': f'no asset found for platform: {platform_key}'}

    bin_dir = get_bin_dir()
    try:
        temp_dir = tempfile.mkdtemp()
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
                    if progress_callback and total_size > 0:
                        progress_callback(downloaded, total_size)

        # 解压到 bin 目录
        os.makedirs(bin_dir, exist_ok=True)
        exe_names = repo_info['exe_names']

        with zipfile.ZipFile(zip_path, 'r') as zf:
            for name in zf.namelist():
                basename = os.path.basename(name)
                if basename in exe_names:
                    target_path = os.path.join(bin_dir, basename)
                    with zf.open(name) as src, open(target_path, 'wb') as dst:
                        dst.write(src.read())
                    break

        shutil.rmtree(temp_dir, ignore_errors=True)

        return {
            'success': True,
            'bin_name': bin_name,
            'version': update_info['tag_name'],
            'path': bin_dir
        }
    except Exception as e:
        try:
            shutil.rmtree(temp_dir, ignore_errors=True)
        except Exception:
            pass
        return {'success': False, 'message': str(e)}
