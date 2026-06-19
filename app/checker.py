"""
Node connectivity checker — Python orchestration layer.

Calls platform-specific test scripts (scripts/test.sh or scripts/test.ps1)
as subprocesses. Handles config generation, temp file management, and result
parsing.

Design (learned from PassWall2):
  - Single node per script invocation (no batch in script)
  - Script is synchronous — it starts proxy, tests, cleans up, returns JSON
  - Three-layer process cleanup inside the script prevents orphans
  - Python wraps subprocess with a timeout as last-resort safety net
"""

import json
import os
import platform
import subprocess
import threading
import time

from . import db
from .config import generate_config

# Project root (two levels up from app/checker.py)
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
SCRIPTS_DIR = os.path.join(PROJECT_ROOT, 'scripts')
TEMP_CONFIG_DIR = os.path.join(PROJECT_ROOT, 'data', 'temp_configs')

IS_WINDOWS = platform.system() == 'Windows'

# Global busy flag — prevent concurrent checks (single + batch)
_busy = False
_busy_lock = threading.Lock()


def _acquire_busy():
    """Try to acquire the global check lock. Returns True if acquired."""
    with _busy_lock:
        global _busy
        if _busy:
            return False
        _busy = True
        return True


def _release_busy():
    """Release the global check lock."""
    with _busy_lock:
        global _busy
        _busy = False


def _get_script_path():
    """Return the path to the platform-appropriate test script."""
    if IS_WINDOWS:
        return os.path.join(SCRIPTS_DIR, 'test.ps1')
    return os.path.join(SCRIPTS_DIR, 'test.sh')


def _make_tag(node_id):
    """Generate a unique tag for this test invocation."""
    return f"ph_{node_id}_{int(time.time() * 1000)}"


def _check_script():
    """Verify the test script exists. Returns True if OK."""
    return os.path.isfile(_get_script_path())


# ============================================================
# TCP Ping
# ============================================================

def tcp_ping(node):
    """Perform TCP connect latency test to a node's address:port.

    Args:
        node: dict with 'id', 'address', 'port'

    Returns:
        dict: {'success': bool, 'latency_ms': int | None, 'error': str | None}
    """
    if not _check_script():
        return {'success': False, 'error': 'test script not found'}

    settings = db.get_all_settings()
    timeout = int(settings.get('tcp_timeout', 3))
    tag = _make_tag(node['id'])
    script = _get_script_path()

    if IS_WINDOWS:
        cmd = [
            'powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass',
            '-File', script,
            '-Action', 'tcp_ping',
            '-Address', str(node['address']),
            '-Port', str(node['port']),
            '-Timeout', str(timeout),
            '-Tag', tag,
        ]
    else:
        cmd = [
            'bash', script,
            'tcp_ping',
            str(node['address']),
            str(node['port']),
            str(timeout),
            tag,
        ]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout + 5,  # script overhead buffer
            cwd=PROJECT_ROOT,
        )
        output = result.stdout.strip()
        if output:
            return json.loads(output)
        return {'success': False, 'error': 'script produced no output'}
    except subprocess.TimeoutExpired:
        return {'success': False, 'error': 'tcp ping timed out'}
    except json.JSONDecodeError:
        return {'success': False, 'error': f'invalid JSON from script: {result.stdout[:200] if result.stdout else ""}'}
    except FileNotFoundError:
        return {'success': False, 'error': f'test script not found: {script}'}
    except Exception as e:
        return {'success': False, 'error': str(e)}


# ============================================================
# URL Test
# ============================================================

def url_test(node):
    """Full proxy reachability test — generates config, starts binary, curls through SOCKS5.

    Args:
        node: dict with all node fields (id, bin_type, address, port, ...)

    Returns:
        dict: {'success': bool, 'http_code': int | None, 'latency_ms': int | None, 'error': str | None}
    """
    if not _check_script():
        return {'success': False, 'error': 'test script not found'}

    settings = db.get_all_settings()
    tag = _make_tag(node['id'])
    bin_type = node.get('bin_type', 'xray')

    # 1. Generate config
    config_result = generate_config(node)
    config_dict = config_result['config']
    local_port = config_result['local_port']

    # 2. Write temp config file
    os.makedirs(TEMP_CONFIG_DIR, exist_ok=True)
    config_filename = f'{bin_type}_{tag}.json'
    config_path = os.path.join(TEMP_CONFIG_DIR, config_filename)

    try:
        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(config_dict, f, indent=2)
    except OSError as e:
        return {'success': False, 'error': f'cannot write config: {e}'}

    # 3. Resolve binary path
    from .bin_manager import get_bin_path
    bin_path = get_bin_path(bin_type)
    if not bin_path:
        _cleanup_file(config_path)
        return {'success': False, 'error': f'bin path not configured for {bin_type}'}

    # Resolve relative paths against project root
    if not os.path.isabs(bin_path):
        bin_path = os.path.join(PROJECT_ROOT, bin_path)

    if not os.path.exists(bin_path):
        _cleanup_file(config_path)
        return {'success': False, 'error': f'binary not found: {bin_path}'}

    # 4. Build script arguments
    test_url = settings.get('test_url', 'http://www.gstatic.com/generate_204')
    curl_timeout = int(settings.get('curl_timeout', 5))
    script = _get_script_path()

    if IS_WINDOWS:
        cmd = [
            'powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass',
            '-File', script,
            '-Action', 'url_test',
            '-ConfigPath', config_path,
            '-BinType', bin_type,
            '-BinPath', bin_path,
            '-LocalPort', str(local_port),
            '-TestUrl', test_url,
            '-CurlTimeout', str(curl_timeout),
            '-Tag', tag,
        ]
        stdin_input = None
    else:
        cmd = ['bash', script, 'url_test']
        stdin_input = json.dumps({
            'config_path': config_path,
            'bin_type': bin_type,
            'bin_path': bin_path,
            'local_port': local_port,
            'test_url': test_url,
            'curl_timeout': curl_timeout,
            'tag': tag,
        })

    # 5. Execute script (timeout = port_wait(15s) + curl_timeout + 5s buffer)
    total_timeout = 15 + curl_timeout + 5

    try:
        result = subprocess.run(
            cmd,
            input=stdin_input,
            capture_output=True,
            text=True,
            timeout=total_timeout,
            cwd=PROJECT_ROOT,
        )
        output = result.stdout.strip()
        if output:
            return json.loads(output)
        return {'success': False, 'error': 'script produced no output'}
    except subprocess.TimeoutExpired:
        _emergency_cleanup(tag, config_path)
        return {'success': False, 'error': 'url test timed out'}
    except json.JSONDecodeError:
        return {'success': False, 'error': f'invalid JSON from script: {result.stdout[:200] if result.stdout else ""}'}
    except FileNotFoundError:
        return {'success': False, 'error': f'test script not found: {script}'}
    except Exception as e:
        _emergency_cleanup(tag, config_path)
        return {'success': False, 'error': str(e)}
    finally:
        _cleanup_file(config_path)


def _emergency_cleanup(tag, config_path):
    """Emergency cleanup when script times out or crashes.
    Kills orphan processes by tag pattern as last resort.
    """
    pid_file = config_path + '.pid'

    # Try to read PID and kill process tree
    if os.path.exists(pid_file):
        try:
            with open(pid_file, 'r') as f:
                pid = int(f.read().strip())
            if IS_WINDOWS:
                subprocess.run(
                    ['taskkill', '/F', '/T', '/PID', str(pid)],
                    capture_output=True, timeout=5,
                )
            else:
                try:
                    os.kill(pid, 9)
                except ProcessLookupError:
                    pass
        except (ValueError, OSError):
            pass
        _cleanup_file(pid_file)

    _cleanup_file(config_path)

    # Pattern-based cleanup by tag (Linux)
    if not IS_WINDOWS:
        try:
            subprocess.run(
                ['pgrep', '-af', tag],
                capture_output=True, timeout=3,
            )
        except Exception:
            pass


def _cleanup_file(path):
    """Remove a file if it exists."""
    try:
        if path and os.path.exists(path):
            os.remove(path)
    except OSError:
        pass


# ============================================================
# Batch check entry point
# ============================================================

def check_nodes(node_ids, check_type='both'):
    """Check connectivity for specified nodes (synchronous, blocks HTTP response).

    Args:
        node_ids: list of node IDs
        check_type: 'tcp' (TCP only), 'url' (URL only via proxy), 'both' (default)

    Returns:
        list of result dicts, or None if busy
    """
    if not _acquire_busy():
        return None

    try:
        return _check_nodes_impl(node_ids, check_type)
    finally:
        _release_busy()


def _check_nodes_impl(node_ids, check_type):
    conn = db.get_db()
    results = []

    for nid in node_ids:
        row = conn.execute('SELECT * FROM nodes WHERE id = ?', (nid,)).fetchone()
        if not row:
            continue
        node = dict(row)

        node_result = {
            'node_id': node['id'],
            'name': node['name'],
            'tcp': None,
            'url': None,
        }

        if check_type in ('tcp', 'both'):
            tcp = tcp_ping(node)
            node_result['tcp'] = tcp

        if check_type in ('url', 'both'):
            # Skip URL test if TCP failed (optimization)
            tcp_ok = node_result.get('tcp', {}).get('success') if node_result.get('tcp') else True
            if tcp_ok:
                url = url_test(node)
            else:
                url = {'success': False, 'error': 'skipped (tcp failed)'}
            node_result['url'] = url

        # Update DB latencies
        tcp_lat = node_result['tcp'].get('latency_ms') if node_result.get('tcp') and node_result['tcp'].get('success') else None
        curl_lat = node_result['url'].get('latency_ms') if node_result.get('url') and node_result['url'].get('success') else None
        db.update_node_latency(node['id'], tcp_lat, curl_lat)

        results.append(node_result)

    conn.close()
    return results


# ============================================================
# Background task management (for batch check)
# ============================================================

import uuid

_tasks = {}
_tasks_lock = threading.Lock()


def start_batch_check(node_ids, check_type='both'):
    """Start a background batch check. Returns task_id immediately, or None if busy.

    The task runs in a daemon thread, processing nodes sequentially.
    Results can be polled via get_task_status(task_id).
    """
    if not _acquire_busy():
        return None

    task_id = uuid.uuid4().hex[:12]

    conn = db.get_db()
    nodes_data = []
    for nid in node_ids:
        row = conn.execute('SELECT * FROM nodes WHERE id = ?', (nid,)).fetchone()
        if row:
            nodes_data.append(dict(row))
    conn.close()

    if not nodes_data:
        _release_busy()
        return None

    with _tasks_lock:
        _tasks[task_id] = {
            'running': True,
            'check_type': check_type,
            'total': len(nodes_data),
            'done': 0,
            'results': {},     # {str(node_id): {node_id, name, tcp: {...}, url: {...}}}
            'started_at': time.time(),
        }

    def _run():
        try:
            _run_impl()
        finally:
            with _tasks_lock:
                if task_id in _tasks:
                    _tasks[task_id]['running'] = False
            _release_busy()

    def _run_impl():
        for node in nodes_data:
            with _tasks_lock:
                if task_id not in _tasks:
                    return  # Task was cancelled

            result = {
                'node_id': node['id'],
                'name': node['name'],
                'tcp': None,
                'url': None,
            }

            if check_type in ('tcp', 'both'):
                tcp = tcp_ping(node)
                result['tcp'] = tcp

            if check_type in ('url', 'both'):
                tcp_ok = result.get('tcp', {}).get('success') if result.get('tcp') else True
                if tcp_ok:
                    url = url_test(node)
                else:
                    url = {'success': False, 'error': 'skipped (tcp failed)'}
                result['url'] = url

            # Update DB
            tcp_lat = result['tcp'].get('latency_ms') if result.get('tcp') and result['tcp'].get('success') else None
            curl_lat = result['url'].get('latency_ms') if result.get('url') and result['url'].get('success') else None
            db.update_node_latency(node['id'], tcp_lat, curl_lat)

            # Update task state
            with _tasks_lock:
                if task_id not in _tasks:
                    return
                _tasks[task_id]['results'][str(node['id'])] = result
                _tasks[task_id]['done'] += 1

    t = threading.Thread(target=_run, daemon=True)
    t.start()

    _cleanup_expired_tasks()
    return task_id


def get_task_status(task_id):
    """Get current progress of a batch check task.

    Returns None if task not found, or:
        {running, check_type, total, done, results: {str(id): {...}}}
    """
    with _tasks_lock:
        task = _tasks.get(task_id)
        if not task:
            return None
        return {
            'running': task['running'],
            'check_type': task['check_type'],
            'total': task['total'],
            'done': task['done'],
            'results': dict(task['results']),
        }


def _cleanup_expired_tasks():
    """Remove completed tasks older than 10 minutes."""
    now = time.time()
    with _tasks_lock:
        expired = [
            tid for tid, t in _tasks.items()
            if not t['running'] and (now - t.get('started_at', now)) > 600
        ]
        for tid in expired:
            del _tasks[tid]
