from network_host_info.host_info import TrackHost
from network_host_info.InventoryOperations import display_inventory

from flask import Flask, render_template, request, jsonify

app = Flask(__name__)

net = {}


@app.route('/')
def welcome():
    return render_template("welcome.html")


@app.route('/inventory')
def inventory():
    return jsonify(display_inventory())


@app.route('/loaddata')
def load_data():
    global net
    net = TrackHost()
    data = net.load()

    return render_template('loaddata.html', data=data)


@app.route('/hosts/track', methods=['GET', 'POST'])
def trackhosts():
    global net
    if request.method == 'POST':
        ips = list(map(str.strip, request.form['ips'].split(',')))
        data = net.track_and_print(ips, port_type=request.form['port_type'], export=True)
        return render_template('trackhostresult.html', data=data)
    else:
        return render_template('trackhosts.html')


@app.route('/subnet/track', methods=['GET', 'POST'])
def track_subnet():
    global net
    if request.method == 'POST':
        subnet = request.form['subnet']
        eips = list(map(str.strip, request.form['eips'].split(',')))
        data = net.track_subnet(subnet, True, request.form['port_type'], *eips)
        return render_template('trackhostresult.html', data=data)
    else:
        return render_template('tracksubnet.html')


@app.route('/hosts/track/command', methods=['GET', 'POST'])
def track_command():
    if request.method == 'POST':
        ips = list(map(str.strip, request.form['ips'].split(',')))
        commands = list(map(str.strip, request.form['commands'].split(',')))
        data = net.track_command_print(ips, commands, port_type=request.form['port_type'], export=True)
        # for foo in data:
        #    foo['show commands'] = foo['show commands'].replace('\n', '<br/>')
        return render_template('trackhostresult.html', data=data)
    else:
        return render_template('trackhostcommand.html')
