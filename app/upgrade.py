import urllib.request
import json
import os
import zipfile
import tempfile
import shutil

GITHUB_API = 'https://api.github.com/repos/v2fly/v2ray-core/releases/latest'


def check_update():
    """检查最新版本"""
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

        return {
            'success': True,
            'tag_name': data['tag_name'],
            'published_at': data['published_at'][:10],
            'assets': assets
        }
    except Exception as e:
        return {'success': False, 'message': str(e)}


def download_binary(platform, progress_callback=None):
    """下载指定平台的二进制文件"""
    # 先检查更新获取下载链接
    update_info = check_update()
    if not update_info['success']:
        return update_info

    # 找到对应平台的 asset
    asset = None
    for a in update_info['assets']:
        if a['platform'] == platform:
            asset = a
            break

    if not asset:
        return {'success': False, 'message': f'no asset found for platform: {platform}'}

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

        # 解压到 bin 目录（相对于项目根目录）
        bin_dir = os.path.join(os.path.dirname(__file__), '..', 'bin')

        with zipfile.ZipFile(zip_path, 'r') as zf:
            # 找到 v2ray 可执行文件
            for name in zf.namelist():
                if name.endswith('.exe') or name == 'v2ray':
                    # 解压到 bin 目录
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
            'path': bin_dir
        }
    except Exception as e:
        # 清理临时文件
        try:
            shutil.rmtree(temp_dir, ignore_errors=True)
        except Exception:
            pass
        return {'success': False, 'message': str(e)}
