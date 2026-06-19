from flask import Flask, render_template, request, jsonify, Response, session, redirect, url_for
from datetime import datetime
from functools import wraps
from . import db
from . import v2fly_manager
from . import upgrade
from . import subscription
from . import checker
from .logger import web_logger
import json
import hashlib
import os

app = Flask(__name__, template_folder='../templates')
app.secret_key = os.urandom(24)

APP_NAME = 'V2Fly-hub'
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
            # 没有密码，直接放行
            return f(*args, **kwargs)

        # 检查 session 中是否已登录
        if session.get('authenticated'):
            return f(*args, **kwargs)

        # API 请求返回 401
        if request.path.startswith('/api/'):
            return jsonify({'success': False, 'message': 'unauthorized'}), 401

        # 页面请求重定向到登录页
        return redirect('/login')

    return decorated


@app.route('/login', methods=['GET', 'POST'])
def login():
    """登录页面"""
    # 检查是否设置了密码
    password = db.get_setting('web_password')
    if not password:
        # 没有密码，直接跳转首页
        return redirect('/')

    # 已登录直接跳转 dashboard
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
    # 密码用 *** 代替
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

    # 处理密码
    password = data.get('web_password')
    password_confirm = data.pop('web_password_confirm', None)

    if password == '***':
        # 密码未修改，不更新
        data.pop('web_password', None)
    elif password:
        # 有新密码，检查确认密码
        if password != password_confirm:
            return jsonify({'success': False, 'message': 'passwords do not match'}), 400
    # password 为空表示清空密码，允许

    db.update_settings(data)
    return jsonify({'success': True})


@app.route('/api/settings/reset', methods=['POST'])
@auth_required
def api_reset_settings():
    """重置所有设置"""
    db.reset_settings()
    session.pop('authenticated', None)
    return jsonify({'success': True})


# ========== v2fly 管理 API ==========

@app.route('/api/v2fly/status', methods=['GET'])
@auth_required
def api_v2fly_status():
    """获取 v2fly 状态"""
    return jsonify(v2fly_manager.get_status())


@app.route('/api/v2fly/start', methods=['POST'])
@auth_required
def api_v2fly_start():
    """启动 v2fly"""
    result = v2fly_manager.start()
    return jsonify(result)


@app.route('/api/v2fly/stop', methods=['POST'])
@auth_required
def api_v2fly_stop():
    """停止 v2fly"""
    result = v2fly_manager.stop()
    return jsonify(result)


@app.route('/api/v2fly/restart', methods=['POST'])
@auth_required
def api_v2fly_restart():
    """重启 v2fly"""
    result = v2fly_manager.restart()
    return jsonify(result)


# ========== 升级 API ==========

@app.route('/api/upgrade/check', methods=['GET'])
@auth_required
def api_upgrade_check():
    """检查更新"""
    result = upgrade.check_update()
    return jsonify(result)


@app.route('/api/upgrade/download', methods=['GET'])
@auth_required
def api_upgrade_download():
    """下载更新（SSE 流式响应）"""

    def generate():
        def progress(downloaded, total):
            pct = int(downloaded * 100 / total) if total > 0 else 0
            yield f"data: {json.dumps({'type': 'progress', 'pct': pct})}\n\n"

        result = upgrade.download_binary(lambda d, t: None)

        if result['success']:
            # 重启 v2fly
            restart_result = v2fly_manager.restart()
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
    import os
    db_path = db.DB_PATH
    db_size = os.path.getsize(db_path) if os.path.exists(db_path) else 0

    status = v2fly_manager.get_status()

    return jsonify({
        'v2fly_version': status['version'],
        'v2fly_status': status['status'],
        'v2fly_pid': status['pid'],
        'v2fly_uptime': status['uptime'],
        'platform': status['platform'],
        'platform_supported': status['platform_supported'],
        'platform_message': status['platform_message'],
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
    # 为每个订阅添加节点数量
    for sub in subs:
        nodes = db.get_nodes_by_sub(sub['id'])
        sub['node_count'] = len(nodes)
    return jsonify(subs)


@app.route('/api/subscriptions', methods=['POST'])
@auth_required
def api_create_subscription():
    """添加订阅"""
    data = request.get_json()
    if not data or not data.get('name') or not data.get('url'):
        return jsonify({'success': False, 'message': 'name and url required'}), 400

    sub_id = db.create_subscription(data['name'], data['url'])

    # 自动刷新订阅
    result = refresh_subscription(sub_id)

    return jsonify({'success': True, 'id': sub_id, 'nodes': result.get('count', 0)})


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

    # 解析节点
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

    if not name or not protocol or not address or not port:
        return jsonify({'success': False, 'message': 'missing required fields'})

    node_id = db.add_custom_node(name, protocol, address, port, config_json)
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

    if not name or not protocol or not address or not port:
        return jsonify({'success': False, 'message': 'missing required fields'})

    db.update_node(node_id, name, protocol, address, port, config_json)
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
