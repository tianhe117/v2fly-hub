import urllib.request
import json
import os
import zipfile
import tempfile
import shutil
from datetime import datetime

GITHUB_API = 'https://api.github.com/repos/v2fly/v2ray-core/releases/latest'


def get_bin_dir():
    """获取 bin 目录路径"""
    return os.path.join(os.path.dirname(__file__), '..', 'bin')


def get_backup_dir():
    """获取备份目录路径"""
    return os.path.join(os.path.dirname(__file__), '..', 'bin', 'backup')


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

        # 检查是否有备份
        backup_info = get_backup_info()

        return {
            'success': True,
            'tag_name': data['tag_name'],
            'published_at': data['published_at'][:10],
            'assets': assets,
            'current_version': current_version,
            'is_latest': is_latest,
            'has_backup': backup_info is not None,
            'backup_info': backup_info
        }
    except Exception as e:
        return {'success': False, 'message': str(e)}


def get_backup_info():
    """获取备份信息"""
    backup_dir = get_backup_dir()
    info_file = os.path.join(backup_dir, 'backup_info.json')

    if not os.path.exists(info_file):
        return None

    try:
        with open(info_file, 'r') as f:
            return json.load(f)
    except Exception:
        return None


def backup_current():
    """备份当前版本"""
    bin_dir = get_bin_dir()
    backup_dir = get_backup_dir()

    # 确定可执行文件名
    import platform
    exe_name = 'v2ray.exe' if platform.system() == 'Windows' else 'v2ray'
    exe_path = os.path.join(bin_dir, exe_name)

    if not os.path.exists(exe_path):
        return {'success': False, 'message': 'current binary not found'}

    try:
        # 创建备份目录
        os.makedirs(backup_dir, exist_ok=True)

        # 获取当前版本
        current_version = get_current_version() or 'unknown'

        # 备份文件名带时间戳
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_name = f'{exe_name}.{timestamp}.bak'
        backup_path = os.path.join(backup_dir, backup_name)

        # 复制文件
        shutil.copy2(exe_path, backup_path)

        # 保存备份信息
        backup_info = {
            'version': current_version,
            'timestamp': timestamp,
            'filename': backup_name,
            'platform': get_platform_key(),
            'created_at': datetime.now().isoformat()
        }

        with open(os.path.join(backup_dir, 'backup_info.json'), 'w') as f:
            json.dump(backup_info, f, indent=2)

        return {'success': True, 'backup_path': backup_path, 'version': current_version}
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

    # 先备份当前版本
    backup_result = backup_current()
    if not backup_result['success']:
        return {'success': False, 'message': f'backup failed: {backup_result["message"]}'}

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

        # 解压到 bin 目录
        bin_dir = get_bin_dir()

        with zipfile.ZipFile(zip_path, 'r') as zf:
            # 找到 v2ray 可执行文件
            for name in zf.namelist():
                if name.endswith('.exe') or name == 'v2ray':
                    target_path = os.path.join(bin_dir, os.path.basename(name))
                    with zf.open(name) as src, open(target_path, 'wb') as dst:
                        dst.write(src.read())
                    # 设置可执行权限（Linux）
                    if not name.endswith('.exe'):
                        os.chmod(target_path, 0o755)

        # 清理临时文件
        shutil.rmtree(temp_dir, ignore_errors=True)

        return {
            'success': True,
            'version': update_info['tag_name'],
            'backup_version': backup_result['version'],
            'path': bin_dir
        }
    except Exception as e:
        # 清理临时文件
        try:
            shutil.rmtree(temp_dir, ignore_errors=True)
        except Exception:
            pass
        return {'success': False, 'message': str(e)}


def restore_backup():
    """恢复备份版本"""
    bin_dir = get_bin_dir()
    backup_dir = get_backup_dir()

    # 读取备份信息
    backup_info = get_backup_info()
    if not backup_info:
        return {'success': False, 'message': 'no backup found'}

    import platform
    exe_name = 'v2ray.exe' if platform.system() == 'Windows' else 'v2ray'

    backup_path = os.path.join(backup_dir, backup_info['filename'])
    target_path = os.path.join(bin_dir, exe_name)

    if not os.path.exists(backup_path):
        return {'success': False, 'message': 'backup file not found'}

    try:
        # 备份当前版本（以防万一）
        current_backup = backup_current()

        # 恢复备份
        shutil.copy2(backup_path, target_path)

        # 删除备份信息文件（已恢复）
        info_file = os.path.join(backup_dir, 'backup_info.json')
        if os.path.exists(info_file):
            os.remove(info_file)

        return {
            'success': True,
            'restored_version': backup_info['version'],
            'current_backup': current_backup.get('version')
        }
    except Exception as e:
        return {'success': False, 'message': str(e)}
