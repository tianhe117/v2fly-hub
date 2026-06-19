import subprocess
import os
import time
import signal

# PID 文件路径：相对于项目根目录的 data/ 目录
PID_FILE = os.path.join(os.path.dirname(__file__), '..', 'data', 'v2fly.pid')


def get_bin_path():
    """获取 v2fly 可执行文件路径"""
    from .db import get_setting
    return get_setting('v2fly_bin_path')


def get_config_dir():
    """获取配置目录路径"""
    from .db import get_setting
    return get_setting('v2fly_config_dir')


def get_version():
    """获取 v2fly 版本"""
    bin_path = get_bin_path()
    if not os.path.exists(bin_path):
        return None
    try:
        result = subprocess.run(
            [bin_path, 'version'],
            capture_output=True,
            text=True,
            timeout=5
        )
        # 解析第一行，格式如 "V2Ray 5.16.1 (V2Fly, v5.16.1)"
        for line in result.stdout.split('\n'):
            if line.strip():
                return line.strip()
        return 'unknown'
    except Exception:
        return 'unknown'


def get_pid():
    """获取运行中的 v2fly PID"""
    if not os.path.exists(PID_FILE):
        return None
    try:
        with open(PID_FILE, 'r') as f:
            pid = int(f.read().strip())
        # 检查进程是否存在
        os.kill(pid, 0)
        return pid
    except (ValueError, ProcessLookupError, PermissionError, OSError):
        # PID 文件无效或进程不存在，清理
        try:
            os.remove(PID_FILE)
        except OSError:
            pass
        return None


def is_running():
    """检查 v2fly 是否正在运行"""
    return get_pid() is not None


def get_uptime():
    """获取进程运行时长（秒）"""
    pid = get_pid()
    if pid is None:
        return None
    try:
        # Windows: 使用 tasklist 获取进程启动时间
        import platform
        if platform.system() == 'Windows':
            result = subprocess.run(
                ['tasklist', '/FI', f'PID eq {pid}', '/FO', 'CSV', '/NH'],
                capture_output=True,
                text=True
            )
            if str(pid) in result.stdout:
                # 简化处理：返回进程存在
                return 0  # 具体时长需要更复杂的实现
        else:
            # Linux: 读取 /proc/pid/stat
            stat = os.stat(f'/proc/{pid}')
            return int(time.time() - stat.st_ctime)
    except Exception:
        return None


def start():
    """启动 v2fly 进程"""
    if is_running():
        return {'success': False, 'message': 'v2fly is already running'}

    bin_path = get_bin_path()
    config_dir = get_config_dir()

    if not os.path.exists(bin_path):
        return {'success': False, 'message': f'binary not found: {bin_path}'}

    config_file = os.path.join(config_dir, 'config.json')
    if not os.path.exists(config_file):
        return {'success': False, 'message': f'config not found: {config_file}'}

    try:
        # 启动进程
        process = subprocess.Popen(
            [bin_path, 'run', '-config', config_file],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
        )

        # 保存 PID
        os.makedirs(os.path.dirname(PID_FILE), exist_ok=True)
        with open(PID_FILE, 'w') as f:
            f.write(str(process.pid))

        # 等待一下确认进程启动
        time.sleep(0.5)
        if process.poll() is not None:
            return {'success': False, 'message': 'v2fly failed to start'}

        return {'success': True, 'pid': process.pid}
    except Exception as e:
        return {'success': False, 'message': str(e)}


def stop():
    """停止 v2fly 进程"""
    pid = get_pid()
    if pid is None:
        return {'success': True, 'message': 'v2fly is not running'}

    try:
        os.kill(pid, signal.SIGTERM)
        # 等待进程退出
        for _ in range(10):
            time.sleep(0.3)
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                break
        else:
            # 强制杀死
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass

        # 清理 PID 文件
        try:
            os.remove(PID_FILE)
        except OSError:
            pass

        return {'success': True}
    except ProcessLookupError:
        # 进程已不存在
        try:
            os.remove(PID_FILE)
        except OSError:
            pass
        return {'success': True}
    except Exception as e:
        return {'success': False, 'message': str(e)}


def restart():
    """重启 v2fly 进程"""
    stop_result = stop()
    if not stop_result['success']:
        return stop_result
    time.sleep(0.5)
    return start()


def get_status():
    """获取 v2fly 完整状态"""
    pid = get_pid()
    version = get_version()
    platform_info = get_platform()

    if pid is not None:
        uptime = get_uptime()
        return {
            'version': version or 'unknown',
            'status': 'running',
            'pid': pid,
            'uptime': uptime,
            'platform': platform_info['key'],
            'platform_supported': platform_info['supported'],
            'platform_message': platform_info['message']
        }
    else:
        return {
            'version': version or 'unknown',
            'status': 'stopped',
            'pid': None,
            'uptime': None,
            'platform': platform_info['key'],
            'platform_supported': platform_info['supported'],
            'platform_message': platform_info['message']
        }


def get_platform():
    """获取平台信息，返回 (platform_key, supported, message)"""
    import platform
    system = platform.system().lower()
    release = platform.release()
    machine = platform.machine().lower()

    if system == 'windows':
        # 检查 Windows 10+ (版本号 >= 10)
        try:
            version = int(release.split('.')[0])
            if version < 10:
                return {
                    'key': f'windows-{machine}',
                    'supported': False,
                    'message': f'Windows {release} is not supported. Requires Windows 10 or later.'
                }
        except (ValueError, IndexError):
            pass

        if '64' in machine or 'amd64' in machine:
            return {'key': 'windows-64', 'supported': True, 'message': 'OK'}
        return {
            'key': f'windows-{machine}',
            'supported': False,
            'message': 'Only x86_64 architecture is supported on Windows.'
        }
    elif system == 'linux':
        if '64' in machine or 'amd64' in machine:
            return {'key': 'linux-64', 'supported': True, 'message': 'OK'}
        return {
            'key': f'linux-{machine}',
            'supported': False,
            'message': 'Only amd64 architecture is supported on Linux.'
        }
    else:
        return {
            'key': f'{system}-{machine}',
            'supported': False,
            'message': f'{system} is not supported. Only Windows 10+ and Linux amd64 are supported.'
        }
