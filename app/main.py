from flask import Flask, render_template, request, jsonify, Response, session, redirect, url_for
from datetime import datetime
from functools import wraps
from . import db
from . import bin_manager
from . import upgrade
from . import subscription
from .subscription import VALID_BIN_TYPES
from .logger import web_logger
import json
import hashlib
import os
import threading
import time

app = Flask(__name__, template_folder='../templates')
app.secret_key = os.urandom(24)

APP_NAME = 'ProxyHub'
boot_time = datetime.now().strftime('%H:%M:%S')

# 需要清理的进程名
BIN_PROCESS_NAMES = ['xray.exe', 'xray', 'sslocal.exe', 'sslocal', 'sing-box.exe', 'sing-box', 'obfs-local.exe', 'obfs-local']


def kill_all_bin_processes():
    """启动时清理所有残留的代理进程"""
    import subprocess
    web_logger.add('info', 'system', 'cleaning up existing processes...')

    for proc_name in BIN_PROCESS_NAMES:
        try:
            if os.name == 'nt':
                # Windows: 使用 shell=True 确保命令正确执行
                cmd = f'taskkill /F /IM {proc_name}'
                result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=5)
                if result.returncode == 0:
                    web_logger.add('info', 'system', f'killed {proc_name}')
            else:
                cmd = f'pkill -f {proc_name}'
                result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=5)
                if result.returncode == 0:
                    web_logger.add('info', 'system', f'killed {proc_name}')
        except Exception:
            pass

    # 清理所有 PID 文件
    pid_dir = os.path.join(os.path.dirname(__file__), '..', 'data')
    if os.path.exists(pid_dir):
        for filename in os.listdir(pid_dir):
            if filename.endswith('.pid'):
                try:
                    os.remove(os.path.join(pid_dir, filename))
                except OSError:
                    pass

    web_logger.add('info', 'system', 'process cleanup done')


def auto_start_services():
    """自动启动设置了 auto-start 的服务"""
    # 先清理所有残留进程
    kill_all_bin_processes()
    time.sleep(1)  # 等待进程完全退出

    time.sleep(10)  # 等待 10 秒
    services = db.get_auto_start_services()
    if not services:
        return

    web_logger.add('info', 'system', f'auto-start: found {len(services)} service(s)')

    for svc in services:
        service_id = svc['id']
        service_name = svc['name']
        web_logger.add('info', 'system', f'auto-start: starting {service_name}...')

        # 调用 start 逻辑
        try:
            from . import config_generator
            result = config_generator.generate_service_config(service_id)
            if not result['success']:
                web_logger.add('error', 'system', f'auto-start: {service_name} config failed: {result["message"]}')
                continue

            paths = config_generator.save_service_config(
                result['service_name'],
                result['xray_in'],
                result['outbound_bin'],
                result['outbound_config']
            )

            # 启动 xray
            xray_result = bin_manager.start(service_name, 'xray', config_path=paths['xray_in'])
            if not xray_result['success']:
                web_logger.add('error', 'system', f'auto-start: {service_name} xray failed: {xray_result["message"]}')
                continue

            # 启动出站 bin
            out_bin = result['outbound_bin']
            out_result = bin_manager.start(service_name, out_bin, config_path=paths['outbound'])
            if not out_result['success']:
                bin_manager.stop(service_name, 'xray')
                web_logger.add('error', 'system', f'auto-start: {service_name} {out_bin} failed: {out_result["message"]}')
                continue

            db.update_service_status(service_id, 'running')
            web_logger.add('ok', 'system', f'auto-start: {service_name} started')
        except Exception as e:
            web_logger.add('error', 'system', f'auto-start: {service_name} error: {str(e)}')


# 启动 auto-start 线程
auto_start_thread = threading.Thread(target=auto_start_services, daemon=True)
auto_start_thread.start()


@app.context_processor
def inject_app_name():
    return dict(app_name=APP_NAME)


def auth_required(f):
    """认证装饰器"""
    @wraps(f)
    def decorated(*args, **kwargs):
        # 检查是否设置了密码
        password = db.get_setting('web_password')
        if not password:
            return f(*args, **kwargs)

        if session.get('authenticated'):
            return f(*args, **kwargs)

        if request.path.startswith('/api/'):
            return jsonify({'success': False, 'message': 'unauthorized'}), 401

        return redirect('/login')

    return decorated


@app.route('/login', methods=['GET', 'POST'])
def login():
    """登录页面"""
    password = db.get_setting('web_password')
    if not password:
        return redirect('/')

    if session.get('authenticated'):
        return redirect('/dashboard')

    if request.method == 'POST':
        username = request.form.get('username', '')
        password_input = request.form.get('password', '')
        expected_username = db.get_setting('web_username')
        expected_password = db.get_setting('web_password')

        if username == expected_username and password_input == expected_password:
            session['authenticated'] = True
            return redirect('/dashboard')
        else:
            return render_template('login.html', error='invalid username or password')

    return render_template('login.html')


@app.route('/logout')
def logout():
    """登出"""
    session.pop('authenticated', None)
    return redirect('/login')


# ========== 页面路由 ==========

@app.route('/')
@auth_required
def index():
    return redirect('/dashboard')


@app.route('/dashboard')
@auth_required
def dashboard():
    return render_template('dashboard.html', page='dashboard', boot_time=boot_time)


@app.route('/inbounds')
@auth_required
def inbounds():
    return render_template('inbounds.html', page='inbounds', boot_time=boot_time)


@app.route('/outbounds')
@auth_required
def outbounds():
    return render_template('outbounds.html', page='outbounds', boot_time=boot_time)


@app.route('/subscriptions')
@auth_required
def subscriptions():
    return render_template('subscriptions.html', page='subscriptions', boot_time=boot_time)


@app.route('/nodes')
@auth_required
def nodes():
    return render_template('nodes.html', page='nodes', boot_time=boot_time)


@app.route('/settings')
@auth_required
def settings():
    return render_template('settings.html', page='settings', boot_time=boot_time)


# ========== 设置 API ==========

@app.route('/api/settings', methods=['GET'])
@auth_required
def api_get_settings():
    """获取所有设置"""
    settings = db.get_all_settings()
    if settings.get('web_password'):
        settings['web_password'] = '***'
    return jsonify(settings)


@app.route('/api/settings', methods=['POST'])
@auth_required
def api_update_settings():
    """更新设置"""
    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'message': 'no data'}), 400

    password = data.get('web_password')
    password_confirm = data.pop('web_password_confirm', None)

    if password == '***':
        data.pop('web_password', None)
    elif password:
        if password != password_confirm:
            return jsonify({'success': False, 'message': 'passwords do not match'}), 400

    db.update_settings(data)
    return jsonify({'success': True})


@app.route('/api/settings/reset', methods=['POST'])
@auth_required
def api_reset_settings():
    """重置所有设置"""
    db.reset_settings()
    session.pop('authenticated', None)
    return jsonify({'success': True})


# ========== 二进制管理 API ==========

@app.route('/api/bins/status', methods=['GET'])
@auth_required
def api_bins_status():
    """获取所有二进制状态"""
    return jsonify(bin_manager.get_all_status())


@app.route('/api/bins/<bin_name>/start', methods=['POST'])
@auth_required
def api_bin_start(bin_name):
    """启动指定二进制"""
    if bin_name not in bin_manager.BIN_REGISTRY:
        return jsonify({'success': False, 'message': f'unknown binary: {bin_name}'}), 400
    result = bin_manager.start(bin_name)
    return jsonify(result)


@app.route('/api/bins/<bin_name>/stop', methods=['POST'])
@auth_required
def api_bin_stop(bin_name):
    """停止指定二进制"""
    if bin_name not in bin_manager.BIN_REGISTRY:
        return jsonify({'success': False, 'message': f'unknown binary: {bin_name}'}), 400
    result = bin_manager.stop(bin_name)
    return jsonify(result)


@app.route('/api/bins/<bin_name>/restart', methods=['POST'])
@auth_required
def api_bin_restart(bin_name):
    """重启指定二进制"""
    if bin_name not in bin_manager.BIN_REGISTRY:
        return jsonify({'success': False, 'message': f'unknown binary: {bin_name}'}), 400
    result = bin_manager.restart(bin_name)
    return jsonify(result)


# ========== 升级 API ==========

@app.route('/api/upgrade/check/<bin_name>', methods=['GET'])
@auth_required
def api_upgrade_check(bin_name):
    """检查指定二进制的更新"""
    if bin_name not in upgrade.BIN_REPOS:
        return jsonify({'success': False, 'message': f'unknown binary: {bin_name}'}), 400
    result = upgrade.check_update(bin_name)
    return jsonify(result)


@app.route('/api/upgrade/download/<bin_name>', methods=['POST'])
@auth_required
def api_upgrade_download(bin_name):
    """下载指定二进制的更新"""
    if bin_name not in upgrade.BIN_REPOS:
        return jsonify({'success': False, 'message': f'unknown binary: {bin_name}'}), 400

    result = upgrade.download_binary(bin_name)

    if result['success']:
        restart_result = bin_manager.restart(bin_name)
        return jsonify({'success': True, 'version': result['version'], 'restart': restart_result})
    else:
        return jsonify({'success': False, 'message': result['message']})


# ========== 危险操作 API ==========

@app.route('/api/nodes/clear', methods=['POST'])
@auth_required
def api_clear_nodes():
    """清空节点"""
    db.clear_nodes()
    return jsonify({'success': True})


@app.route('/api/database/clear', methods=['POST'])
@auth_required
def api_clear_database():
    """清空数据库"""
    db.clear_database()
    session.pop('authenticated', None)
    return jsonify({'success': True})


# ========== 系统信息 API ==========

@app.route('/api/system/info', methods=['GET'])
@auth_required
def api_system_info():
    """获取系统信息"""
    db_path = db.DB_PATH
    db_size = os.path.getsize(db_path) if os.path.exists(db_path) else 0

    # 获取所有二进制状态
    bins_status = bin_manager.get_all_status()

    # 获取平台信息
    platform_info = bin_manager.get_platform()

    return jsonify({
        'bins': bins_status,
        'platform': platform_info['key'],
        'platform_supported': platform_info['supported'],
        'platform_message': platform_info['message'],
        'db_size': db_size,
        'db_size_human': format_size(db_size)
    })


def format_size(size):
    """格式化文件大小"""
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size < 1024:
            return f'{size:.1f} {unit}'
        size /= 1024
    return f'{size:.1f} TB'


# ========== 订阅 API ==========

@app.route('/api/subscriptions', methods=['GET'])
@auth_required
def api_get_subscriptions():
    """获取所有订阅"""
    subs = db.get_all_subscriptions()
    for sub in subs:
        nodes = db.get_nodes_by_sub(sub['id'])
        sub['node_count'] = len(nodes)
    return jsonify(subs)


@app.route('/api/subscriptions', methods=['POST'])
@auth_required
def api_create_subscription():
    """添加订阅（只创建记录，不立即刷新）"""
    data = request.get_json()
    if not data or not data.get('name') or not data.get('url'):
        return jsonify({'success': False, 'message': 'name and url required'}), 400

    sub_id = db.create_subscription(data['name'], data['url'])
    return jsonify({'success': True, 'id': sub_id})


@app.route('/api/subscriptions/<int:sub_id>', methods=['PUT'])
@auth_required
def api_update_subscription(sub_id):
    """更新订阅"""
    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'message': 'no data'}), 400
    db.update_subscription(sub_id, data)
    return jsonify({'success': True})


@app.route('/api/subscriptions/<int:sub_id>', methods=['DELETE'])
@auth_required
def api_delete_subscription(sub_id):
    """删除订阅"""
    db.delete_subscription(sub_id)
    return jsonify({'success': True})


@app.route('/api/subscriptions/<int:sub_id>/refresh', methods=['POST'])
@auth_required
def api_refresh_subscription(sub_id):
    """刷新订阅"""
    result = refresh_subscription(sub_id)
    return jsonify(result)


def refresh_subscription(sub_id):
    """刷新订阅（获取并解析节点）"""
    sub = db.get_subscription(sub_id)
    if not sub:
        return {'success': False, 'message': 'subscription not found'}

    # 获取订阅内容
    result = subscription.fetch_subscription(sub['url'])
    if not result['success']:
        return {'success': False, 'message': result['message']}

    # 更新流量信息
    if result.get('info'):
        db.update_subscription_traffic(sub_id, result['info'])

    # 解析节点（自动设置 bin_type）
    nodes = subscription.parse_nodes(result['content'])

    # 应用关键字筛选（换行或逗号分隔，OR 关系）
    def _split_keywords(raw):
        return [k.strip() for k in raw.replace('\n', ',').split(',') if k.strip()]

    filter_kws = _split_keywords(sub['filter_keywords'])
    exclude_kws = _split_keywords(sub['exclude_keywords'])

    if filter_kws:
        nodes = [n for n in nodes if any(kw.lower() in n['name'].lower() for kw in filter_kws)]
    if exclude_kws:
        nodes = [n for n in nodes if not any(kw.lower() in n['name'].lower() for kw in exclude_kws)]

    # 清空旧节点，添加新节点
    db.clear_nodes_by_sub(sub_id)
    db.add_nodes(sub_id, nodes)
    db.set_subscription_updated(sub_id)

    return {'success': True, 'count': len(nodes)}


# ========== 入站 API ==========

@app.route('/api/inbounds', methods=['GET'])
@auth_required
def api_get_inbounds():
    """获取所有入站"""
    inbounds = db.get_all_inbounds()
    return jsonify(inbounds)


@app.route('/api/inbounds', methods=['POST'])
@auth_required
def api_create_inbound():
    """创建入站"""
    data = request.get_json()
    if not data or not data.get('name') or not data.get('protocol') or not data.get('port'):
        return jsonify({'success': False, 'message': 'name, protocol, port required'}), 400

    name = data['name'].strip()
    protocol = data['protocol'].strip()
    listen_addr = data.get('listen_addr', '0.0.0.0').strip() or '0.0.0.0'
    port = int(data['port'])
    params_json = data.get('params_json', '{}')

    if protocol not in ('http', 'socks', 'ss', 'vmess'):
        return jsonify({'success': False, 'message': 'invalid protocol'}), 400

    if port < 1 or port > 65535:
        return jsonify({'success': False, 'message': 'port out of range'}), 400

    if not isinstance(params_json, str):
        params_json = json.dumps(params_json)

    inbound_id = db.create_inbound(name, protocol, listen_addr, port, params_json)
    return jsonify({'success': True, 'id': inbound_id})


@app.route('/api/inbounds/<int:inbound_id>', methods=['PUT'])
@auth_required
def api_update_inbound(inbound_id):
    """更新入站"""
    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'message': 'no data'}), 400

    existing = db.get_inbound(inbound_id)
    if not existing:
        return jsonify({'success': False, 'message': 'inbound not found'}), 404

    name = data.get('name', existing['name']).strip()
    protocol = data.get('protocol', existing['protocol']).strip()
    listen_addr = data.get('listen_addr', existing['listen_addr']).strip() or '0.0.0.0'
    port = int(data.get('port', existing['port']))
    params_json = data.get('params_json', existing['params_json'])

    if protocol not in ('http', 'socks', 'ss', 'vmess'):
        return jsonify({'success': False, 'message': 'invalid protocol'}), 400

    if not isinstance(params_json, str):
        params_json = json.dumps(params_json)

    db.update_inbound(inbound_id, name, protocol, listen_addr, port, params_json)
    return jsonify({'success': True})


@app.route('/api/inbounds/<int:inbound_id>', methods=['DELETE'])
@auth_required
def api_delete_inbound(inbound_id):
    """删除入站"""
    db.delete_inbound(inbound_id)
    return jsonify({'success': True})


# ========== 出站 API ==========

@app.route('/api/outbounds', methods=['GET'])
@auth_required
def api_get_outbounds():
    """获取所有出站（含节点池信息）"""
    outbounds = db.get_all_outbounds()
    for ob in outbounds:
        if ob['type'] == 'auto':
            pool = db.get_outbound_nodes(ob['id'])
            ob['pool'] = pool
        elif ob['type'] == 'single':
            config = json.loads(ob['config_json'])
            node_id = config.get('node_id')
            if node_id:
                conn = db.get_db()
                node = conn.execute('SELECT * FROM nodes WHERE id = ?', (node_id,)).fetchone()
                conn.close()
                ob['node'] = dict(node) if node else None
    return jsonify(outbounds)


@app.route('/api/outbounds', methods=['POST'])
@auth_required
def api_create_outbound():
    """创建出站"""
    data = request.get_json()
    if not data or not data.get('name') or not data.get('type'):
        return jsonify({'success': False, 'message': 'name and type required'}), 400

    name = data['name'].strip()
    out_type = data['type'].strip()

    if out_type not in ('single', 'auto'):
        return jsonify({'success': False, 'message': 'type must be single or auto'}), 400

    config = {}
    if out_type == 'single':
        node_id = data.get('node_id')
        if not node_id:
            return jsonify({'success': False, 'message': 'node_id required for single type'}), 400
        config['node_id'] = int(node_id)
    elif out_type == 'auto':
        config['check_interval'] = int(db.get_setting('check_interval_normal') or 240)
        config['test_url'] = db.get_setting('test_url') or 'http://www.gstatic.com/generate_204'

    outbound_id = db.create_outbound(name, out_type, json.dumps(config))
    return jsonify({'success': True, 'id': outbound_id})


@app.route('/api/outbounds/<int:outbound_id>', methods=['PUT'])
@auth_required
def api_update_outbound(outbound_id):
    """更新出站"""
    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'message': 'no data'}), 400

    existing = db.get_outbound(outbound_id)
    if not existing:
        return jsonify({'success': False, 'message': 'outbound not found'}), 404

    name = data.get('name', existing['name']).strip()
    out_type = data.get('type', existing['type']).strip()

    if out_type not in ('single', 'auto'):
        return jsonify({'success': False, 'message': 'type must be single or auto'}), 400

    config = {}
    if out_type == 'single':
        node_id = data.get('node_id')
        if not node_id:
            return jsonify({'success': False, 'message': 'node_id required for single type'}), 400
        config['node_id'] = int(node_id)
    elif out_type == 'auto':
        config['check_interval'] = int(db.get_setting('check_interval_normal') or 240)
        config['test_url'] = db.get_setting('test_url') or 'http://www.gstatic.com/generate_204'

    db.update_outbound(outbound_id, name, out_type, json.dumps(config))
    return jsonify({'success': True})


@app.route('/api/outbounds/<int:outbound_id>', methods=['DELETE'])
@auth_required
def api_delete_outbound(outbound_id):
    """删除出站"""
    db.delete_outbound(outbound_id)
    return jsonify({'success': True})


@app.route('/api/outbounds/<int:outbound_id>/nodes', methods=['GET'])
@auth_required
def api_get_outbound_nodes(outbound_id):
    """获取出站节点池"""
    pool = db.get_outbound_nodes(outbound_id)
    return jsonify(pool)


@app.route('/api/outbounds/<int:outbound_id>/nodes', methods=['POST'])
@auth_required
def api_add_outbound_node(outbound_id):
    """向出站节点池添加节点"""
    data = request.get_json()
    if not data or not data.get('node_id'):
        return jsonify({'success': False, 'message': 'node_id required'}), 400

    node_id = int(data['node_id'])
    # 检查是否已在池中
    pool = db.get_outbound_nodes(outbound_id)
    if any(n['id'] == node_id for n in pool):
        return jsonify({'success': False, 'message': 'node already in pool'})
    max_priority = max([n['priority'] for n in pool], default=0)
    db.add_outbound_node(outbound_id, node_id, max_priority + 1)
    return jsonify({'success': True})


@app.route('/api/outbounds/nodes/<int:pool_id>', methods=['DELETE'])
@auth_required
def api_remove_outbound_node(pool_id):
    """从出站节点池移除节点"""
    db.remove_outbound_node(pool_id)
    return jsonify({'success': True})


@app.route('/api/outbounds/<int:outbound_id>/nodes/reorder', methods=['POST'])
@auth_required
def api_reorder_outbound_nodes(outbound_id):
    """重新排序出站节点池"""
    data = request.get_json()
    if not data or not data.get('node_ids'):
        return jsonify({'success': False, 'message': 'node_ids required'}), 400
    db.reorder_outbound_nodes(outbound_id, data['node_ids'])
    return jsonify({'success': True})


# ========== 节点 API ==========

@app.route('/api/nodes', methods=['GET'])
@auth_required
def api_get_nodes():
    """获取所有节点"""
    nodes = db.get_all_nodes()
    return jsonify(nodes)


@app.route('/api/nodes/by-sub/<int:sub_id>', methods=['GET'])
@auth_required
def api_get_nodes_by_sub(sub_id):
    """获取订阅下的节点"""
    nodes = db.get_nodes_by_sub(sub_id)
    return jsonify(nodes)


@app.route('/api/nodes/grouped', methods=['GET'])
@auth_required
def api_get_nodes_grouped():
    """获取按订阅分组的节点"""
    groups = db.get_nodes_grouped()
    return jsonify(groups)


@app.route('/api/nodes', methods=['POST'])
@auth_required
def api_add_node():
    """添加用户自定义节点"""
    data = request.json
    name = data.get('name', '').strip()
    protocol = data.get('protocol', '').strip()
    address = data.get('address', '').strip()
    port = data.get('port', 0)
    config_json = data.get('config_json', '{}')
    bin_type = data.get('bin_type', 'xray')

    if not name or not protocol or not address or not port:
        return jsonify({'success': False, 'message': 'missing required fields'})

    # 验证 protocol 和 bin_type 的匹配
    valid_bins = VALID_BIN_TYPES.get(protocol)
    if valid_bins and bin_type not in valid_bins:
        return jsonify({'success': False, 'message': f'invalid bin_type "{bin_type}" for protocol "{protocol}", allowed: {", ".join(valid_bins)}'})

    # SS 协议且 bin=xray 时，不能有插件
    if protocol == 'ss' and bin_type == 'xray':
        try:
            config = json.loads(config_json)
            if config.get('plugin'):
                return jsonify({'success': False, 'message': 'xray does not support SS with plugin, use sslocal instead'})
        except json.JSONDecodeError:
            pass

    node_id = db.add_custom_node(name, protocol, address, port, config_json, bin_type)
    return jsonify({'success': True, 'id': node_id})


@app.route('/api/nodes/<int:node_id>', methods=['PUT'])
@auth_required
def api_update_node(node_id):
    """更新节点"""
    data = request.json
    name = data.get('name', '').strip()
    protocol = data.get('protocol', '').strip()
    address = data.get('address', '').strip()
    port = data.get('port', 0)
    config_json = data.get('config_json', '{}')
    bin_type = data.get('bin_type', 'xray')

    if not name or not protocol or not address or not port:
        return jsonify({'success': False, 'message': 'missing required fields'})

    # 验证 protocol 和 bin_type 的匹配
    valid_bins = VALID_BIN_TYPES.get(protocol)
    if valid_bins and bin_type not in valid_bins:
        return jsonify({'success': False, 'message': f'invalid bin_type "{bin_type}" for protocol "{protocol}", allowed: {", ".join(valid_bins)}'})

    # SS 协议且 bin=xray 时，不能有插件
    if protocol == 'ss' and bin_type == 'xray':
        try:
            config = json.loads(config_json)
            if config.get('plugin'):
                return jsonify({'success': False, 'message': 'xray does not support SS with plugin, use sslocal instead'})
        except json.JSONDecodeError:
            pass

    db.update_node(node_id, name, protocol, address, port, config_json, bin_type)
    return jsonify({'success': True})


@app.route('/api/nodes/<int:node_id>', methods=['DELETE'])
@auth_required
def api_delete_node(node_id):
    """删除节点"""
    db.delete_node(node_id)
    return jsonify({'success': True})


@app.route('/api/nodes/check', methods=['POST'])
@auth_required
def api_check_nodes():
    """节点连通性检测 — 单节点同步返回，多节点后台异步执行

    Body (JSON, optional):
      node_ids: [1, 2, ...]   — 指定节点，不传则检测全部
      check_type: 'tcp'|'url'|'both'  — 默认 'both'

    单节点返回: {success: true, results: [{...}]}
    多节点返回: {success: true, task_id: 'xxx', count: N}
    """
    data = request.get_json(silent=True) or {}
    node_ids = data.get('node_ids')
    check_type = data.get('check_type', 'both')

    if check_type not in ('tcp', 'url', 'both'):
        return jsonify({'success': False, 'message': 'check_type must be tcp, url, or both'}), 400

    from . import checker

    # Collect node IDs
    conn = db.get_db()
    if node_ids:
        ids = []
        for nid in node_ids:
            row = conn.execute('SELECT id FROM nodes WHERE id = ?', (nid,)).fetchone()
            if row:
                ids.append(row['id'])
    else:
        rows = conn.execute('SELECT id FROM nodes').fetchall()
        ids = [r['id'] for r in rows]
    conn.close()

    if not ids:
        return jsonify({'success': False, 'message': 'no nodes found'}), 404

    # Single node: synchronous, return results immediately
    if len(ids) == 1:
        results = checker.check_nodes(ids, check_type)
        if results is None:
            return jsonify({'success': False, 'message': 'a check is already running'}), 409
        return jsonify({'success': True, 'results': results, 'check_type': check_type})

    # Multiple nodes: background task, return task_id
    task_id = checker.start_batch_check(ids, check_type)
    if task_id is None:
        return jsonify({'success': False, 'message': 'a check is already running'}), 409

    return jsonify({'success': True, 'task_id': task_id, 'count': len(ids), 'check_type': check_type})


@app.route('/api/nodes/check/<task_id>/status', methods=['GET'])
@auth_required
def api_check_status(task_id):
    """查询批量检测任务进度"""
    from . import checker
    status = checker.get_task_status(task_id)
    if status is None:
        return jsonify({'success': False, 'message': 'task not found'}), 404
    return jsonify({'success': True, **status})


# ========== 服务 API ==========

@app.route('/api/services', methods=['GET'])
@auth_required
def api_get_services():
    """获取所有服务"""
    services = db.get_all_services()
    return jsonify(services)


@app.route('/api/services/<int:service_id>', methods=['GET'])
@auth_required
def api_get_service(service_id):
    """获取单个服务"""
    service = db.get_service(service_id)
    if not service:
        return jsonify({'success': False, 'message': 'service not found'}), 404
    return jsonify(service)


@app.route('/api/services', methods=['POST'])
@auth_required
def api_create_service():
    """创建服务"""
    data = request.get_json()
    if not data or not data.get('name') or not data.get('inbound_id') or not data.get('outbound_id'):
        return jsonify({'success': False, 'message': 'name, inbound_id, outbound_id required'}), 400

    # 验证 inbound 和 outbound 存在
    inbound = db.get_inbound(data['inbound_id'])
    if not inbound:
        return jsonify({'success': False, 'message': 'inbound not found'}), 404
    outbound = db.get_outbound(data['outbound_id'])
    if not outbound:
        return jsonify({'success': False, 'message': 'outbound not found'}), 404

    service_id = db.create_service(data['name'], data['inbound_id'], data['outbound_id'])
    return jsonify({'success': True, 'id': service_id})


@app.route('/api/services/<int:service_id>', methods=['PUT'])
@auth_required
def api_update_service(service_id):
    """更新服务"""
    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'message': 'no data'}), 400

    existing = db.get_service(service_id)
    if not existing:
        return jsonify({'success': False, 'message': 'service not found'}), 404

    db.update_service(
        service_id,
        name=data.get('name'),
        inbound_id=data.get('inbound_id'),
        outbound_id=data.get('outbound_id'),
        auto_start=data.get('auto_start')
    )
    return jsonify({'success': True})


@app.route('/api/services/<int:service_id>', methods=['DELETE'])
@auth_required
def api_delete_service(service_id):
    """删除服务"""
    existing = db.get_service(service_id)
    if not existing:
        return jsonify({'success': False, 'message': 'service not found'}), 404
    db.delete_service(service_id)
    return jsonify({'success': True})


@app.route('/api/services/<int:service_id>/start', methods=['POST'])
@auth_required
def api_start_service(service_id):
    """生成配置并启动进程"""
    from . import config_generator
    from .logger import web_logger

    existing = db.get_service(service_id)
    if not existing:
        return jsonify({'success': False, 'message': 'service not found'}), 404

    service_name = existing['name']

    # 检查是否已在运行
    if bin_manager.is_running(service_name, 'xray'):
        return jsonify({'success': False, 'message': 'service is already running'})

    # 生成配置
    result = config_generator.generate_service_config(service_id)
    if not result['success']:
        web_logger.add('error', 'config', f'config generation failed: {result["message"]}')
        return jsonify(result)

    # 保存配置文件
    paths = config_generator.save_service_config(
        result['service_name'],
        result['xray_in'],
        result['outbound_bin'],
        result['outbound_config']
    )

    web_logger.add('info', 'config', f'generated config for {service_name}')

    # 启动 xray 入站进程
    xray_result = bin_manager.start(service_name, 'xray', config_path=paths['xray_in'])
    if not xray_result['success']:
        db.update_service_status(service_id, 'error')
        return jsonify({'success': False, 'message': f'xray start failed: {xray_result["message"]}'})

    web_logger.add('info', 'service', f'xray started for {service_name}, pid={xray_result.get("pid")}')

    # 启动出站 bin 进程
    out_bin = result['outbound_bin']
    out_result = bin_manager.start(service_name, out_bin, config_path=paths['outbound'])
    if not out_result['success']:
        # 回滚：停止 xray
        bin_manager.stop(service_name, 'xray')
        db.update_service_status(service_id, 'error')
        return jsonify({'success': False, 'message': f'{out_bin} start failed: {out_result["message"]}'})

    web_logger.add('info', 'service', f'{out_bin} started for {service_name}, pid={out_result.get("pid")}')

    db.update_service_status(service_id, 'running')
    return jsonify({
        'success': True,
        'socks_port': result['socks_port'],
        'inbound_port': result['inbound_port'],
        'node': result['node_name']
    })


@app.route('/api/services/<int:service_id>/stop', methods=['POST'])
@auth_required
def api_stop_service(service_id):
    """停止服务：停止相关进程"""
    from .logger import web_logger

    existing = db.get_service(service_id)
    if not existing:
        return jsonify({'success': False, 'message': 'service not found'}), 404

    service_name = existing['name']

    # 停止所有进程
    results = bin_manager.stop_service(service_name)

    # 检查结果并记录日志
    all_stopped = True
    for bin_name, result in results.items():
        if result.get('pid'):
            if result['success']:
                web_logger.add('info', 'service', f'{bin_name} (pid={result["pid"]}) stopped')
            else:
                web_logger.add('error', 'service', f'{bin_name} stop failed: {result.get("message")}')
                all_stopped = False

    if all_stopped:
        db.update_service_status(service_id, 'stopped')
        web_logger.add('info', 'service', f'service {service_name} stopped')
        return jsonify({'success': True})
    else:
        db.update_service_status(service_id, 'error')
        return jsonify({'success': False, 'message': 'some processes failed to stop'})


@app.route('/api/services/<int:service_id>/restart', methods=['POST'])
@auth_required
def api_restart_service(service_id):
    """重启服务：stop 成功后再 start"""
    existing = db.get_service(service_id)
    if not existing:
        return jsonify({'success': False, 'message': 'service not found'}), 404

    # 先停止
    stop_response = api_stop_service(service_id)
    stop_result = stop_response.get_json()

    if not stop_result.get('success'):
        return jsonify({'success': False, 'message': 'stop failed, restart aborted'})

    # 再启动
    return api_start_service(service_id)


# ========== 日志 API ==========

@app.route('/api/logs', methods=['GET'])
@auth_required
def api_get_logs():
    """获取日志"""
    since = request.args.get('since', 0, type=int)
    logs = web_logger.get_logs(since)
    return jsonify({
        'logs': logs,
        'total': web_logger.get_count()
    })


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=8080)
