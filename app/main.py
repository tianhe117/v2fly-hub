from flask import Flask, render_template, request, jsonify, Response
from datetime import datetime
from . import db
from . import v2fly_manager
from . import upgrade
import json

app = Flask(__name__, template_folder='../templates')

boot_time = datetime.now().strftime('%H:%M:%S')


# ========== 页面路由 ==========

@app.route('/')
def dashboard():
    return render_template('dashboard.html', page='dashboard', boot_time=boot_time)


@app.route('/inbounds')
def inbounds():
    return render_template('inbounds.html', page='inbounds', boot_time=boot_time)


@app.route('/outbounds')
def outbounds():
    return render_template('outbounds.html', page='outbounds', boot_time=boot_time)


@app.route('/subscriptions')
def subscriptions():
    return render_template('subscriptions.html', page='subscriptions', boot_time=boot_time)


@app.route('/nodes')
def nodes():
    return render_template('nodes.html', page='nodes', boot_time=boot_time)


@app.route('/settings')
def settings():
    return render_template('settings.html', page='settings', boot_time=boot_time)


# ========== 设置 API ==========

@app.route('/api/settings', methods=['GET'])
def api_get_settings():
    """获取所有设置"""
    return jsonify(db.get_all_settings())


@app.route('/api/settings', methods=['POST'])
def api_update_settings():
    """更新设置"""
    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'message': 'no data'}), 400
    db.update_settings(data)
    return jsonify({'success': True})


@app.route('/api/settings/reset', methods=['POST'])
def api_reset_settings():
    """重置所有设置"""
    db.reset_settings()
    return jsonify({'success': True})


# ========== v2fly 管理 API ==========

@app.route('/api/v2fly/status', methods=['GET'])
def api_v2fly_status():
    """获取 v2fly 状态"""
    return jsonify(v2fly_manager.get_status())


@app.route('/api/v2fly/start', methods=['POST'])
def api_v2fly_start():
    """启动 v2fly"""
    result = v2fly_manager.start()
    return jsonify(result)


@app.route('/api/v2fly/stop', methods=['POST'])
def api_v2fly_stop():
    """停止 v2fly"""
    result = v2fly_manager.stop()
    return jsonify(result)


@app.route('/api/v2fly/restart', methods=['POST'])
def api_v2fly_restart():
    """重启 v2fly"""
    result = v2fly_manager.restart()
    return jsonify(result)


# ========== 升级 API ==========

@app.route('/api/upgrade/check', methods=['GET'])
def api_upgrade_check():
    """检查更新"""
    result = upgrade.check_update()
    return jsonify(result)


@app.route('/api/upgrade/download', methods=['GET'])
def api_upgrade_download():
    """下载更新（SSE 流式响应）"""
    platform = request.args.get('platform', 'windows-64')

    def generate():
        def progress(downloaded, total):
            pct = int(downloaded * 100 / total) if total > 0 else 0
            yield f"data: {json.dumps({'type': 'progress', 'pct': pct})}\n\n"

        result = upgrade.download_binary(platform, lambda d, t: None)

        if result['success']:
            # 重启 v2fly
            restart_result = v2fly_manager.restart()
            yield f"data: {json.dumps({'type': 'complete', 'version': result['version'], 'restart': restart_result})}\n\n"
        else:
            yield f"data: {json.dumps({'type': 'error', 'message': result['message']})}\n\n"

    return Response(generate(), mimetype='text/event-stream')


# ========== 危险操作 API ==========

@app.route('/api/nodes/clear', methods=['POST'])
def api_clear_nodes():
    """清空节点"""
    db.clear_nodes()
    return jsonify({'success': True})


@app.route('/api/database/clear', methods=['POST'])
def api_clear_database():
    """清空数据库"""
    db.clear_database()
    return jsonify({'success': True})


# ========== 系统信息 API ==========

@app.route('/api/system/info', methods=['GET'])
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


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=8080)
