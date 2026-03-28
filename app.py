from flask import Flask, render_template, request, jsonify, send_from_directory, redirect, url_for
import sqlite3
from flask_socketio import SocketIO, emit
import database
import serial
import serial.tools.list_ports
import threading
import time
from datetime import datetime
import os
import json
import logging
import webview

app = Flask(__name__)
socketio = SocketIO(app, async_mode='threading', cors_allowed_origins="*")

# Non-aktifkan log default Flask (Werkzeug) agar terminal tidak penuh spam GET /api/events
log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)

RACE_SETUP_FILE = 'Race_setup.json'

def get_race_setup():
    if not os.path.exists(RACE_SETUP_FILE):
        return {'beep_sound': 'on', 'time_precision': '3'}
    try:
        with open(RACE_SETUP_FILE, 'r') as f:
            return json.load(f)
    except:
        return {'beep_sound': 'on', 'time_precision': '3'}

def save_race_setup(data):
    try:
        with open(RACE_SETUP_FILE, 'w') as f:
            json.dump(data, f)
        return True
    except:
        return False

class SerialManager:
    def __init__(self):
        self.serial_port = None
        self.is_connected = False
        self.reading_thread = None
        self.last_handled_event = None
        self.latest_location = None
        
    def connect(self, port, baudrate=9600):
        try:
            self.serial_port = serial.Serial(port, baudrate, timeout=1)
            self.is_connected = True
            self.start_reading()
            return True
        except Exception as e:
            print(f"Serial Error: {e}")
            return False
    
    def disconnect(self):
        self.is_connected = False
        if self.reading_thread and self.reading_thread.is_alive():
            self.reading_thread.join(timeout=1)
        if self.serial_port and self.serial_port.is_open:
            self.serial_port.close()
    
    def start_reading(self):
        self.reading_thread = threading.Thread(target=self.read_serial_data, daemon=True)
        self.reading_thread.start()
    
    def read_serial_data(self):
        buffer = ""
        while self.is_connected:
            try:
                if self.serial_port and self.serial_port.in_waiting:
                    data = self.serial_port.read(self.serial_port.in_waiting).decode('utf-8', errors='ignore')
                    buffer += data
                    
                    while ';' in buffer:
                        line, buffer = buffer.split(';', 1)
                        if line.strip():
                            self.process_message(line.strip())
                else:
                    time.sleep(0.01) # Mencegah 100% CPU usage saat idle
            except Exception as e:
                print(f"Read error: {e}")
                time.sleep(0.1)
    
    def process_message(self, message):
        if message.startswith('$'):
            message = message[1:]  # Remove $
            
            if message.startswith('LAT:'):
                self.latest_location = message
                return
                
            parts = message.split('*')
            if len(parts) == 2:
                raw_data, checksum = parts
                if self.validate_checksum(raw_data, checksum):
                    self.handle_event(raw_data, checksum)
    
    def validate_checksum(self, data, checksum):
        expected = 0
        for char in data:
            expected ^= ord(char)
        return f"{expected:02X}" == checksum
    
    def handle_event(self, raw_data, checksum=""):
        try:
            line_status, timestamp = raw_data.split(',')
            
            # Format time
            settings = database.get_settings()
            precision = int(settings.get('time_precision', '3'))
            
            if len(timestamp) >= 7 and timestamp.isdigit():
                frac = timestamp[6:6+precision]
                formatted_time = f"{timestamp[0:2]}:{timestamp[2:4]}:{timestamp[4:6]}.{frac}"
            else:
                formatted_time = timestamp

            # Deduplication
            current_event_id = f"{line_status}_{formatted_time}"
            if current_event_id == getattr(self, 'last_handled_event', None):
                return 
            self.last_handled_event = current_event_id

            active_race_id = settings.get('active_race_id')
            current_ss = settings.get('current_ss', '1')
            database.add_timing(active_race_id, line_status, formatted_time, ss_number=current_ss)
            socketio.emit('new_data', {'status': 'event', 'line': line_status})
            print(f"Event: {line_status} @ {formatted_time} (Stored for Race ID: {active_race_id}, SS: {current_ss})")
        except Exception as e:
            print("Handle Event Error", e)
    
    def send_command(self, command, custom_timestamp=None):
        if self.is_connected and self.serial_port:
            try:
                self.serial_port.write(f"${command};".encode())
            except Exception as e:
                print(f"Error sending to serial: {e}")

        # Log manual timing
        if custom_timestamp:
            timestamp = custom_timestamp
        else:
            now = datetime.now()
            timestamp = now.strftime("%H:%M:%S.") + f"{now.microsecond // 1000:03d}"
        
        try:
            settings = database.get_settings()
            active_race_id = settings.get('active_race_id')
            current_ss = settings.get('current_ss', '1')
            database.add_timing(active_race_id, command, timestamp, ss_number=current_ss)
            socketio.emit('new_data', {'status': 'manual', 'line': command})
        except Exception as e:
            print("Error creating manual event log", e)

# Global serial manager
serial_mgr = SerialManager()

@app.route('/api/update_ss', methods=['POST'])
def update_ss_api():
    data = request.json
    ss = data.get('ss')
    if ss:
        database.update_settings({'current_ss': str(ss)})
        return jsonify({'status': 'success'})
    return jsonify({'status': 'error'}), 400

@app.route('/api/sync_db', methods=['POST'])
def sync_db_api():
    success, message = database.sync_sqlite_to_postgres()
    if success:
        return jsonify({'status': 'success', 'message': message})
    else:
        return jsonify({'status': 'error', 'message': message}), 500

def get_current_state():
    state = database.get_full_state()
    race_setup = get_race_setup()
    
    # Ensure event is a dict
    if state.get('event') is None:
        state['event'] = {}
        
    state['race_setup'] = race_setup
    
    # Merge for easier template access (settings will have everything)
    # We keep the originals too for backward compatibility in templates that use event.get
    state['settings'] = {**state['settings'], **state['event'], **state['race_setup']}
    
    return state

@app.route('/')
def index():
    ports = [port.device for port in serial.tools.list_ports.comports()]
    state = get_current_state()
    return render_template('index.html', 
                         ports=ports, 
                         connected=serial_mgr.is_connected,
                         settings=state['settings'],
                         event=state['event'],
                         stats=state['stats'])

@app.route('/connect', methods=['POST'])
def connect_serial():
    data = request.json
    port = data['port']
    baudrate = data.get('baudrate', 9600)
    
    if serial_mgr.connect(port, baudrate):
        state = get_current_state()
        now = datetime.now().strftime("%H:%M:%S")
        database.add_timing(state['active_race_id'], 'SYS', f"Connected to {port}", ns_number="-")
        socketio.emit('new_data', {'status': 'sys'})
        return jsonify({'status': 'connected', 'port': port})
    else:
        state = get_current_state()
        database.add_timing(state['active_race_id'], 'SYS', f"Failed to connect to {port}", ns_number="-")
        return jsonify({'status': 'error', 'message': 'Failed to connect'}), 400

@app.route('/disconnect')
def disconnect_serial():
    state = get_current_state()
    now = datetime.now().strftime("%H:%M:%S")
    database.add_timing(state['active_race_id'], 'SYS', "Disconnected from device", ns_number="-")
    serial_mgr.disconnect()
    return jsonify({'status': 'disconnected'})

@app.route('/api/manual_command', methods=['POST'])
def manual_command():
    data = request.json
    command = data.get('command')
    timestamp = data.get('timestamp')
    if not command:
        return jsonify({'error': 'No command provided'}), 400
        
    serial_mgr.send_command(command, timestamp)
    return jsonify({'status': 'Command sent'})

@app.route('/hq', methods=['GET', 'POST'])
def hq():
    message = request.args.get('message')
    state = get_current_state()
    active_id = state['active_race_id']
    
    # Pendukung Viewer: Pilih event mana yang sedang ditampilkan (default: active_id)
    view_id = request.args.get('view_id') or active_id
    view_event = database.get_event_by_id(view_id)
    
    # Jika event ditemukan, gunakan datanya untuk mengisi form
    if view_event:
        state['settings'].update({
            'Event_Name': view_event.get('Event_Name'),
            'Start_Date': view_event.get('Start_Date'),
            'End_Date': view_event.get('End_Date'),
            'Koordinat': view_event.get('Koordinat'),
            'total_ss': view_event.get('Total_SS'),
            'view_id': view_id,
            'is_active_view': (str(view_id) == str(active_id))
        })
    
    if request.method == 'POST':
        data = request.form
        target_id = data.get('target_id') or active_id
        
        database.update_event_details(target_id, {
            'event_name': data.get('event_name', '').strip() or f"Event {target_id[:5]}",
            'start_date': data.get('start_date', '').strip() or 'none',
            'end_date': data.get('end_date', '').strip() or 'none',
            'koordinat': data.get('koordinat', '').strip() or 'none',
            'total_ss': int(data.get('total_ss') or 1)
        })
        
        return redirect(url_for('hq', view_id=target_id, message='Changes saved successfully!'))
    
    all_events = database.get_all_events()
    return render_template('hq.html', message=message, all_events=all_events, **state)

@app.route('/tc')
def tc():
    state = get_current_state()
    return render_template('tc.html', **state)

@app.route('/start')
def start():
    state = get_current_state()
    return render_template('start.html', **state)

@app.route('/flying_finish')
def flying_finish():
    state = get_current_state()
    current_ss = state['settings'].get('current_ss', '1')
    timings = database.get_timings(state['active_race_id'], limit=100, ss=current_ss)
    return render_template('events.html', events=timings, **state)

@app.route('/stop')
def stop():
    state = get_current_state()
    return render_template('stop.html', **state)

@app.route('/park')
def park():
    state = get_current_state()
    return render_template('park.html', **state)

@app.route('/results')
def results():
    state = get_current_state()
    return render_template('result.html', **state)

@app.route('/api/events')
def api_events():
    state = get_current_state()
    ss = request.args.get('ss')
    timings = database.get_timings(state['active_race_id'], limit=500, ss=ss)
    return jsonify(timings)

@app.route('/api/events/delete', methods=['POST'])
def api_delete_event():
    data = request.json
    race_id = data.get('event_id')
    state = get_current_state()
    if race_id == state['active_race_id']:
        return jsonify({'error': 'Cannot delete the ACTIVE event. Deactivate it first.'}), 400
    
    if database.delete_event(race_id):
        return jsonify({'status': 'success'})
    return jsonify({'error': 'Delete failed'}), 500

@app.route('/api/starting_list/<race_id>')
def api_get_starting_list(race_id):
    entries = database.get_starting_list(race_id)
    return jsonify(entries)

@app.route('/api/starting_list/upsert', methods=['POST'])
def api_upsert_starting_entry():
    data = request.json
    race_id = data.get('race_id')
    if not race_id:
        return jsonify({'error': 'No race_id provided'}), 400
    entry_id = database.upsert_starting_entry(race_id, data)
    return jsonify({'status': 'success', 'id': entry_id})

@app.route('/api/starting_list/bulk_import', methods=['POST'])
def api_bulk_import_starting_entries():
    data = request.json
    race_id = data.get('race_id')
    entries = data.get('entries')
    if not race_id or not entries:
        return jsonify({'error': 'No race_id or entries provided'}), 400
    
    database.bulk_upsert_starting_entries(race_id, entries)
    return jsonify({'status': 'success'})

@app.route('/api/starting_list/delete', methods=['POST'])
def api_delete_starting_entry():
    data = request.json
    entry_id = data.get('id')
    if database.delete_starting_entry(entry_id):
        return jsonify({'status': 'success'})
    return jsonify({'error': 'Delete failed'}), 500

@app.route('/api/events/clear', methods=['POST'])
def api_events_clear():
    state = get_current_state()
    database.clear_current_timings(state['active_race_id'])
    return jsonify({'status': 'cleared'})

@app.route('/api/events/new_event', methods=['POST'])
def api_new_event():
    data = request.json or {}
    new_id = database.create_new_event(data)
    return jsonify({'status': 'success', 'new_race_id': new_id})

@app.route('/api/events/switch', methods=['POST'])
def api_switch_event():
    data = request.json
    event_id = data.get('event_id')
    if event_id:
        database.update_settings({'active_race_id': str(event_id)})
        return jsonify({'status': 'success'})
    return jsonify({'status': 'error'}), 400

def _send_timing_to_serial(timing):
    """Helper to send a timing record to the controller via serial"""
    if serial_mgr.is_connected and serial_mgr.serial_port:
        try:
            timing_id = timing['id']
            ns_number = timing.get('No_start', '')
            raw_time = timing.get('Time_Stamp', '')
            compressed_time = raw_time.replace(':', '').replace('.', '')
            data_segment = f"{ns_number},{compressed_time}"
            
            checksum = 0
            for char in data_segment:
                checksum ^= ord(char)
            hex_checksum = f"{checksum:02X}"
            
            final_command = f"${data_segment}*{hex_checksum};\n"
            serial_mgr.serial_port.write(final_command.encode())
            
            database.mark_timing_sent(timing_id)
            print(f"Sync-Sent to Controller: {final_command.strip()}")
            return True
        except Exception as e:
            print(f"Error sending timing data: {e}")
            return False
    return False

@app.route('/api/events/update_ns', methods=['POST'])
def update_ns_api():
    data = request.json
    timing_id = data.get('id')
    ns_number = data.get('ns_number', '')
    if not timing_id:
        return jsonify({'error': 'No ID provided'}), 400
    
    timing = database.get_timing_by_id(timing_id)
    if not timing:
        return jsonify({'error': 'Record not found'}), 404

    database.update_timing_ns(timing_id, ns_number)

    if not ns_number:
        return jsonify({'status': 'updated'})
    
    if (timing.get('send') == 1) and (timing.get('No_start') == ns_number):
        return jsonify({'status': 'updated', 'message': 'Already sent'})

    # Updated timing info after DB update
    timing = database.get_timing_by_id(timing_id)
    _send_timing_to_serial(timing)

    return jsonify({'status': 'updated'})

@app.route('/api/events/sync_ss', methods=['POST'])
def sync_ss_api():
    data = request.json
    ss = data.get('ss')
    state = get_current_state()
    
    # Get all timings for this SS that have NS but not sent
    timings = database.get_timings(state['active_race_id'], limit=500, ss=ss)
    sent_count = 0
    
    for t in timings:
        if t.get('No_start') and t.get('send') == 0:
            if _send_timing_to_serial(t):
                sent_count += 1
                
    return jsonify({'status': 'success', 'sent_count': sent_count})

@app.route('/api/get_location', methods=['POST'])
def get_location():
    if not serial_mgr.is_connected:
        return jsonify({'error': 'Device is disconnected'}), 400
    
    serial_mgr.latest_location = None
    state = get_current_state()
    now = datetime.now().strftime("%H:%M:%S")
    database.add_timing(state['active_race_id'], 'SYS', "Requesting GPS Koordinat...", ns_number="-")
    
    # Kirim perintah #LOC sesuai permintaan controller
    if serial_mgr.serial_port and serial_mgr.serial_port.is_open:
        try:
            serial_mgr.serial_port.write(b"#LOC;")
            print("Requesting coordinates with: #LOC;")
        except Exception as e:
            return jsonify({'error': f'Serial Write Error: {e}'}), 500
            
    for _ in range(30):
        if serial_mgr.latest_location:
            database.update_event_details(state['active_race_id'], {'koordinat': serial_mgr.latest_location})
            database.add_timing(state['active_race_id'], 'SYS', f"GPS Received: {serial_mgr.latest_location}", ns_number="-")
            socketio.emit('new_data', {'status': 'gps'})
            return jsonify({'location': serial_mgr.latest_location})
        time.sleep(0.1)
    
    database.add_timing(state['active_race_id'], 'SYS', "GPS Request Timeout", ns_number="-")
    return jsonify({'error': 'Hardware timeout (No response from controller)'}), 408

@app.route('/api/save_race_setup', methods=['POST'])
def api_save_race_setup():
    data = request.json
    if save_race_setup(data):
        return jsonify({'status': 'success'})
    return jsonify({'status': 'error'}), 500

@app.route('/settings', methods=['GET', 'POST'])
def settings():
    message = None
    state = get_current_state()
    
    if request.method == 'POST':
        data = request.form
        # Update ONLY current event details in DB, with 'none' fallback for blanks
        database.update_event_details(state['active_race_id'], {
            'event_name': data.get('event_name', '').strip() or 'none',
            'start_date': data.get('start_date', '').strip() or 'none',
            'end_date': data.get('end_date', '').strip() or 'none',
            'operator': data.get('operator', '').strip() or 'none',
            'koordinat': data.get('koordinat', '').strip() or 'none'
        })
        message = 'Setup Event saved!'
        state = get_current_state()
    
    ports = [port.device for port in serial.tools.list_ports.comports()]
    current_port = serial_mgr.serial_port.port if serial_mgr.is_connected and serial_mgr.serial_port else None
    
    all_events = database.get_all_events()
    
    return render_template('settings.html', 
                         settings=state['settings'], 
                         event=state['event'],
                         message=message,
                         ports=ports,
                         connected=serial_mgr.is_connected,
                         current_port=current_port,
                         all_events=all_events)

@app.route('/static/<path:path>')
def send_static(path):
    return send_from_directory('static', path)

def run_flask():
    # Gunakan socketio.run agar pengiriman real-time bekerja
    socketio.run(app, host='127.0.0.1', port=5000, debug=True, use_reloader=False, allow_unsafe_werkzeug=True)

@app.route('/api/pull_cloud_events')
def api_pull_cloud_events():
    success, message = database.pull_events_from_cloud()
    return jsonify({'success': success, 'message': message})

if __name__ == '__main__':
    database.init_db()
    
    # Jalankan Flask di Thread terpisah (Background)
    t = threading.Thread(target=run_flask)
    t.daemon = True
    t.start()
    
    # Buka Jendela Aplikasi Utama (Desktop view)
    print("Aplikasi sedang berjalan...")
    webview.create_window(
        'Kralrei Flying Finish 2026 - v1.0', 
        'http://127.0.0.1:5000', 
        width=1366, 
        height=768, 
        resizable=True,
        min_size=(1024, 720)
    )
    webview.start()