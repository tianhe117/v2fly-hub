from flask import Flask, render_template, request, jsonify, Response, session, redirect, url_for
from datetime import datetime
from functools import wraps
from . import db
from . import bin_manager
from . import upgrade
from . import subscription
from . import checker
from .logger import web_logger
import json
import hashlib
import os

app = Flask(__name__, template_folder='../templates')
app.secret_key = os.urandom(24)

APP_NAME = 'ProxyHub'
boot_time = datetime.now().strftime('%H:%M:%S')


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


@app.route('/api/upgrade/download/<bin_name>', methods=['GET'])
@auth_required
def api_upgrade_download(bin_name):
    """下载指定二进制的更新（SSE 流式响应）"""
    if bin_name not in upgrade.BIN_REPOS:
        return jsonify({'success': False, 'message': f'unknown binary: {bin_name}'}), 400

    def generate():
        result = upgrade.download_binary(bin_name)

        if result['success']:
            restart_result = bin_manager.restart(bin_name)
            yield f"data: {json.dumps({'type': 'complete', 'version': result['version'], 'restart': restart_result})}\n\n"
        else:
            error_type = result.get('error_type', 'unknown')
            yield f"data: {json.dumps({'type': 'error', 'message': result['message'], 'error_type': error_type})}\n\n"

    return Response(generate(), mimetype='text/event-stream')


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

    # 应用关键字筛选
    filter_kws = [k.strip() for k in sub['filter_keywords'].split(',') if k.strip()]
    exclude_kws = [k.strip() for k in sub['exclude_keywords'].split(',') if k.strip()]

    if filter_kws:
        nodes = [n for n in nodes if any(kw.lower() in n['name'].lower() for kw in filter_kws)]
    if exclude_kws:
        nodes = [n for n in nodes if not any(kw.lower() in n['name'].lower() for kw in exclude_kws)]

    # 清空旧节点，添加新节点
    db.clear_nodes_by_sub(sub_id)
    db.add_nodes(sub_id, nodes)
    db.set_subscription_updated(sub_id)

    return {'success': True, 'count': len(nodes)}


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
    """检测节点延迟"""
    data = request.json
    node_ids = data.get('node_ids', [])
    check_all = data.get('all', False)

    results = checker.check_nodes(node_ids=node_ids, check_all=check_all)

    if not results:
        return jsonify({'success': False, 'message': 'no nodes to check'})

    return jsonify({'success': True, 'results': results})


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
