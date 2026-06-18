from flask import Flask, render_template
from datetime import datetime

app = Flask(__name__)

boot_time = datetime.now().strftime('%H:%M:%S')


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


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=8080)
