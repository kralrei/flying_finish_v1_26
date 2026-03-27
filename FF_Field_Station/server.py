from flask import Flask, request, jsonify
from flask_cors import CORS
import psycopg2
from psycopg2.extras import RealDictCursor
import os
from datetime import datetime
import uuid

app = Flask(__name__)
CORS(app) # Allow connections from the mobile app

# Aiven PostgreSQL Connection (Using Env Var)
DATABASE_URL = os.getenv('DATABASE_URL', 'postgres://avnadmin:AVNS_kBuJkPaOCdYMOCjCU0x@kralreirally2026-ipenk79-a621.j.aivencloud.com:17394/defaultdb?sslmode=require')

def get_db_connection():
    return psycopg2.connect(DATABASE_URL)

@app.route('/api/status', methods=['GET'])
def status():
    return jsonify({'status': 'online', 'database': 'connected'})

@app.route('/api/save_timing', methods=['POST'])
def save_timing():
    data = request.json
    station_type = data.get('station_type') # 'TC' or 'START'
    ss = data.get('ss', '1')
    ns = data.get('ns', '')
    time_hhmm = data.get('jam', '')
    
    # Format current date with provided time
    # This logic assumes the timing happens today
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        # Get active_race_id from settings
        cur.execute("SELECT value FROM settings WHERE key = 'active_race_id'")
        result = cur.fetchone()
        race_id = result[0] if result else '1'
        
        # Insert into Aiven Timing Table (UUID ID)
        timing_id = str(uuid.uuid4())
        
        cur.execute("""
            INSERT INTO timing (id, race_id, no_start, line_status, time_stamp, ss) 
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (timing_id, race_id, ns, station_type, time_hhmm, ss))
        
        conn.commit()
        cur.close()
        conn.close()
        return jsonify({'status': 'success', 'id': timing_id})
    except Exception as e:
        print(f"Error: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

if __name__ == '__main__':
    # Run on all interfaces for mobile access (Access via http://your-pc-ip:5050)
    app.run(host='0.0.0.0', port=5050, debug=True)
