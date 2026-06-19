import urllib.request
import json
import os
import zipfile
import tempfile
import shutil

GITHUB_API = 'https://api.github.com/repos/v2fly/v2ray-core/releases/latest'


def get_bin_dir():
    """获取 bin 目录路径"""
    return os.path.join(os.path.dirname(__file__), '..', 'bin')


def get_current_version():
    """获取当前版本号（从二进制文件解析）"""
    from .v2fly_manager import get_version
    version_str = get_version()
    if not version_str or version_str == 'unknown':
        return None
    # 解析版本号，格式如 "V2Ray 5.49.0 (V2Fly, ...)"
    try:
        parts = version_str.split()
        for part in parts:
            if part[0].isdigit():
                return part
    except Exception:
        pass
    return None


def get_platform_key():
    """获取平台标识"""
    from .v2fly_manager import get_platform
    return get_platform()['key']


def check_platform_supported():
    """检查当前平台是否支持"""
    from .v2fly_manager import get_platform
    info = get_platform()
    return info['supported'], info['message'], info['key']


def check_update():
    """检查最新版本"""
    # 先检查平台支持
    supported, message, platform_key = check_platform_supported()
    if not supported:
        return {'success': False, 'message': message, 'error_type': 'platform_not_supported'}

    try:
        req = urllib.request.Request(
            GITHUB_API,
            headers={'User-Agent': 'v2fly-manager'}
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())

        # 解析 assets
        assets = []
        for asset in data.get('assets', []):
            name = asset['name']
            # 只保留需要的平台
            if 'linux-64' in name or 'windows-64' in name:
                platform = 'linux-64' if 'linux-64' in name else 'windows-64'
                assets.append({
                    'name': name,
                    'platform': platform,
                    'url': asset['browser_download_url'],
                    'size': asset['size']
                })

        # 获取当前版本
        current_version = get_current_version()
        latest_version = data['tag_name'].lstrip('v')

        # 判断是否已是最新版
        is_latest = False
        if current_version and latest_version:
            is_latest = current_version == latest_version

        return {
            'success': True,
            'tag_name': data['tag_name'],
            'published_at': data['published_at'][:10],
            'assets': assets,
            'current_version': current_version,
            'is_latest': is_latest
        }
    except Exception as e:
        return {'success': False, 'message': str(e)}


def download_binary(progress_callback=None):
    """下载最新版本"""
    # 检查平台支持
    supported, message, platform_key = check_platform_supported()
    if not supported:
        return {'success': False, 'message': message}

    # 先检查更新
    update_info = check_update()
    if not update_info['success']:
        return update_info

    # 如果已是最新版，返回提示
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
        # 下载到临时文件
        temp_dir = tempfile.mkdtemp()
        zip_path = os.path.join(temp_dir, asset['name'])

        req = urllib.request.Request(
            asset['url'],
            headers={'User-Agent': 'v2fly-manager'}
        )

        with urllib.request.urlopen(req, timeout=30) as resp:
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

        # 解压到 bin 目录（只提取 v2ray 可执行文件）
        os.makedirs(bin_dir, exist_ok=True)

        with zipfile.ZipFile(zip_path, 'r') as zf:
            for name in zf.namelist():
                basename = os.path.basename(name)
                if basename in ('v2ray.exe', 'v2ray'):
                    target_path = os.path.join(bin_dir, basename)
                    with zf.open(name) as src, open(target_path, 'wb') as dst:
                        dst.write(src.read())
                    break

        # 清理临时文件
        shutil.rmtree(temp_dir, ignore_errors=True)

        return {
            'success': True,
            'version': update_info['tag_name'],
            'path': bin_dir
        }
    except Exception as e:
        # 清理临时文件
        try:
            shutil.rmtree(temp_dir, ignore_errors=True)
        except Exception:
            pass
        return {'success': False, 'message': str(e)}
