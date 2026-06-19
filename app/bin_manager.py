import subprocess
import os
import time
import signal

# 数据目录
DATA_DIR = os.path.join(os.path.dirname(__file__), '..', 'data')

# 二进制注册表：每个二进制的启动参数和版本命令
BIN_REGISTRY = {
    'xray': {
        'exe': 'xray.exe',
        'version_args': ['version'],
        'run_args': ['run', '-config', '{config}'],
    },
    'sslocal': {
        'exe': 'sslocal.exe',
        'version_args': ['--version'],
        'run_args': ['-c', '{config}'],
    },
    'sing-box': {
        'exe': 'sing-box.exe',
        'version_args': ['version'],
        'run_args': ['run', '-c', '{config}'],
    },
}


def _pid_file(service_name, bin_name):
    """获取 service 级别的 PID 文件路径"""
    return os.path.join(DATA_DIR, f'{service_name}_{bin_name}.pid')


def get_bin_path(bin_name):
    """获取二进制可执行文件路径"""
    from .db import get_setting
    if bin_name == 'xray':
        return get_setting('bin_path_xray')
    elif bin_name == 'sslocal':
        return get_setting('bin_path_sslocal')
    elif bin_name == 'sing-box':
        return get_setting('bin_path_singbox')
    return None


def get_config_dir():
    """获取配置目录路径"""
    from .db import get_setting
    return get_setting('config_dir')


def get_version(bin_name):
    """获取二进制版本"""
    bin_path = get_bin_path(bin_name)
    if not bin_path or not os.path.exists(bin_path):
        return None
    reg = BIN_REGISTRY.get(bin_name)
    if not reg:
        return None
    try:
        result = subprocess.run(
            [bin_path] + reg['version_args'],
            capture_output=True,
            text=True,
            timeout=5
        )
        # 解析第一行
        for line in result.stdout.split('\n'):
            if line.strip():
                return line.strip()
        return 'unknown'
    except Exception:
        return 'unknown'


def get_pid(service_name, bin_name):
    """获取运行中的进程 PID"""
    pid_file = _pid_file(service_name, bin_name)
    if not os.path.exists(pid_file):
        return None
    try:
        with open(pid_file, 'r') as f:
            pid = int(f.read().strip())
        # 检查进程是否存在
        if os.name == 'nt':
            # Windows: 用 tasklist 检查更可靠
            result = subprocess.run(
                ['tasklist', '/FI', f'PID eq {pid}', '/FO', 'CSV', '/NH'],
                capture_output=True, text=True, timeout=5
            )
            if str(pid) in result.stdout:
                return pid
        else:
            # Linux: os.kill(pid, 0) 检查
            os.kill(pid, 0)
            return pid
    except (ValueError, ProcessLookupError, PermissionError, OSError):
        pass
    # 进程不存在，清理 PID 文件
    try:
        os.remove(pid_file)
    except OSError:
        pass
    return None


def is_running(service_name, bin_name):
    """检查进程是否正在运行"""
    return get_pid(service_name, bin_name) is not None


def get_uptime(service_name, bin_name):
    """获取进程运行时长（秒）"""
    pid = get_pid(service_name, bin_name)
    if pid is None:
        return None
    try:
        import platform
        if platform.system() == 'Windows':
            result = subprocess.run(
                ['tasklist', '/FI', f'PID eq {pid}', '/FO', 'CSV', '/NH'],
                capture_output=True,
                text=True
            )
            if str(pid) in result.stdout:
                return 0
        else:
            stat = os.stat(f'/proc/{pid}')
            return int(time.time() - stat.st_ctime)
    except Exception:
        return None


def start(service_name, bin_name, config_path=None):
    """启动进程（service 级别）"""
    if is_running(service_name, bin_name):
        return {'success': False, 'message': f'{service_name}/{bin_name} is already running'}

    bin_path = get_bin_path(bin_name)
    if not bin_path or not os.path.exists(bin_path):
        return {'success': False, 'message': f'binary not found: {bin_path}'}

    reg = BIN_REGISTRY.get(bin_name)
    if not reg:
        return {'success': False, 'message': f'unknown binary: {bin_name}'}

    # 如果没指定配置文件，使用默认路径
    if not config_path:
        config_dir = get_config_dir()
        config_path = os.path.join(config_dir, service_name, f'{bin_name}.json')

    if not os.path.exists(config_path):
        return {'success': False, 'message': f'config not found: {config_path}'}

    try:
        # 构建启动命令
        args = [bin_path] + [a.replace('{config}', config_path) for a in reg['run_args']]

        process = subprocess.Popen(
            args,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
        )

        # 保存 PID
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(_pid_file(service_name, bin_name), 'w') as f:
            f.write(str(process.pid))

        # 等待确认进程启动
        time.sleep(0.5)
        if process.poll() is not None:
            return {'success': False, 'message': f'{bin_name} failed to start'}

        return {'success': True, 'pid': process.pid}
    except Exception as e:
        return {'success': False, 'message': str(e)}


def stop(service_name, bin_name):
    """停止进程（service 级别）"""
    pid = get_pid(service_name, bin_name)
    pid_file = _pid_file(service_name, bin_name)

    if pid is None:
        # 确保清理可能残留的 PID 文件
        if os.path.exists(pid_file):
            try:
                os.remove(pid_file)
            except OSError:
                pass
        return {'success': True, 'message': f'{service_name}/{bin_name} is not running', 'pid': None}

    try:
        # Windows 上使用 taskkill，更可靠
        if os.name == 'nt':
            subprocess.run(['taskkill', '/F', '/PID', str(pid)],
                         capture_output=True, timeout=5)
        else:
            os.kill(pid, signal.SIGTERM)
            for _ in range(10):
                time.sleep(0.3)
                try:
                    os.kill(pid, 0)
                except ProcessLookupError:
                    break
            else:
                try:
                    os.kill(pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass

        # 等待确认进程停止
        time.sleep(0.5)
        still_running = is_running(service_name, bin_name)

        # 清理 PID 文件
        try:
            os.remove(pid_file)
        except OSError:
            pass

        if still_running:
            return {'success': False, 'message': f'{service_name}/{bin_name} failed to stop (pid={pid})', 'pid': pid}

        return {'success': True, 'pid': pid}
    except ProcessLookupError:
        # 进程已不存在，清理 PID 文件
        try:
            os.remove(pid_file)
        except OSError:
            pass
        return {'success': True, 'pid': pid}
    except Exception as e:
        # 出错时也清理 PID 文件
        try:
            os.remove(pid_file)
        except OSError:
            pass
        return {'success': False, 'message': str(e), 'pid': pid}


def restart(service_name, bin_name, config_path=None):
    """重启进程（service 级别）"""
    stop_result = stop(service_name, bin_name)
    if not stop_result['success']:
        return stop_result
    time.sleep(0.5)
    return start(service_name, bin_name, config_path)


def get_status(service_name, bin_name):
    """获取单个进程的完整状态"""
    pid = get_pid(service_name, bin_name)

    if pid is not None:
        uptime = get_uptime(service_name, bin_name)
        return {
            'status': 'running',
            'pid': pid,
            'uptime': uptime,
        }
    else:
        return {
            'status': 'stopped',
            'pid': None,
            'uptime': None,
        }


def get_service_status(service_name):
    """获取 service 下所有进程的状态"""
    result = {}
    for bin_name in BIN_REGISTRY:
        if is_running(service_name, bin_name):
            result[bin_name] = get_status(service_name, bin_name)
    return result


def stop_service(service_name):
    """停止 service 的所有进程"""
    results = {}
    for bin_name in BIN_REGISTRY:
        if is_running(service_name, bin_name):
            results[bin_name] = stop(service_name, bin_name)
    return results


# ========== 兼容旧接口（全局级别，用于 settings 页面管理 bin） ==========

def _global_pid_file(bin_name):
    """全局 PID 文件路径"""
    return os.path.join(DATA_DIR, f'{bin_name}.pid')


def get_global_pid(bin_name):
    """获取全局进程 PID"""
    pid_file = _global_pid_file(bin_name)
    if not os.path.exists(pid_file):
        return None
    try:
        with open(pid_file, 'r') as f:
            pid = int(f.read().strip())
        os.kill(pid, 0)
        return pid
    except (ValueError, ProcessLookupError, PermissionError, OSError):
        try:
            os.remove(pid_file)
        except OSError:
            pass
        return None


def is_global_running(bin_name):
    """检查全局进程是否运行"""
    return get_global_pid(bin_name) is not None


def get_all_status():
    """获取所有二进制的状态（检查全局 + 所有 service 级别的进程）"""
    result = {}

    # 先收集所有 service 级别正在运行的 bin
    running_bins = set()
    if os.path.exists(DATA_DIR):
        for filename in os.listdir(DATA_DIR):
            if filename.endswith('.pid'):
                # 格式: <service>_<bin>.pid 或 <bin>.pid
                parts = filename[:-4].rsplit('_', 1)
                if len(parts) == 2 and parts[1] in BIN_REGISTRY:
                    # service 级别: ss-forward_xray.pid
                    bin_name = parts[1]
                elif parts[0] in BIN_REGISTRY:
                    # 全局: xray.pid
                    bin_name = parts[0]
                else:
                    continue

                # 检查进程是否真的在运行
                pid_file = os.path.join(DATA_DIR, filename)
                try:
                    with open(pid_file, 'r') as f:
                        pid = int(f.read().strip())
                    if os.name == 'nt':
                        result_proc = subprocess.run(
                            ['tasklist', '/FI', f'PID eq {pid}', '/FO', 'CSV', '/NH'],
                            capture_output=True, text=True, timeout=5
                        )
                        if str(pid) in result_proc.stdout:
                            running_bins.add(bin_name)
                    else:
                        os.kill(pid, 0)
                        running_bins.add(bin_name)
                except (ValueError, ProcessLookupError, PermissionError, OSError):
                    # 清理无效的 PID 文件
                    try:
                        os.remove(pid_file)
                    except OSError:
                        pass

    for bin_name in BIN_REGISTRY:
        version = get_version(bin_name)
        if bin_name in running_bins:
            result[bin_name] = {
                'version': version or 'unknown',
                'status': 'running',
            }
        else:
            result[bin_name] = {
                'version': version or 'unknown',
                'status': 'stopped',
            }
    return result


def get_platform():
    """获取平台信息"""
    import platform
    system = platform.system().lower()
    release = platform.release()
    machine = platform.machine().lower()

    if system == 'windows':
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
