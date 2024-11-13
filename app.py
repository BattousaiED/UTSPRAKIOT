from flask import Flask, render_template, jsonify, request
from flask_socketio import SocketIO, emit
import paho.mqtt.client as mqtt
from datetime import datetime
from flask_cors import CORS
import json
from pymongo import MongoClient
from bson import json_util

app = Flask(__name__)
CORS(app)
socketio = SocketIO(app, cors_allowed_origins="*")

# Koneksi ke MongoDB
client = MongoClient("mongodb://localhost:27017/")
db = client['uts']
collection = db['suhuuts']

# Konfigurasi MQTT
MQTT_BROKER = "192.168.45.116"  # Ganti dengan IP broker Mosquitto jika di jaringan berbeda
MQTT_PORT = 1885
MQTT_TOPIC = "sensor/data"

# Callback untuk menerima data dari MQTT
def on_message(client, userdata, msg):
    try:
        print("Payload received:", msg.payload.decode())

        # Coba parse payload sebagai JSON
        try:
            data = json.loads(msg.payload.decode())
        except json.JSONDecodeError:
            # Jika payload bukan JSON, anggap sebagai nilai numerik
            data = {
                "temperature": float(msg.payload.decode()), 
                "humidity": None, 
                "ldr": None
            }

        # Pastikan data memiliki struktur yang benar
        if isinstance(data, dict):
            # Jika timestamp berupa UNIX timestamp, konversi menjadi format datetime
            if isinstance(data.get('timestamp'), int):
                timestamp = datetime.utcfromtimestamp(data['timestamp']).strftime('%Y-%m-%d %H:%M:%S')
            else:
                timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

            # Menyimpan data suhu, kelembapan, dan kecerahan dalam format float
            new_data = {
                'suhu': float(data['temperature']) if data.get('temperature') is not None else None,
                'kelembapan': float(data['humidity']) if data.get('humidity') is not None else None,
                'kecerahan': int(data['ldr']) if data.get('ldr') is not None else None,
                'timestamp': timestamp
            }

            # Menyimpan data ke MongoDB
            collection.insert_one(new_data)
            print("Data diterima dan ditambahkan ke MongoDB.")

            # Menghitung suhumax, suhumin, dan suhurata
            all_data = list(collection.find({}))
            suhumax = max([item['suhu'] for item in all_data], default=None)
            suhumin = min([item['suhu'] for item in all_data], default=None)
            suhurata = sum([item['suhu'] for item in all_data]) / len(all_data) if all_data else None

            # Menyusun nilai_suhu_max_humid_max
            nilai_suhu_max_humid_max = [
                {
                    "idx": i + 1,
                    "suhu": item['suhu'],
                    "humid": item.get('kelembapan', None),
                    "kecerahan": item.get('kecerahan', None),
                    "timestamp": item['timestamp']
                }
                for i, item in enumerate(all_data)
            ]

            # Menyusun month_year_max
            month_year_max = [
                {"month_year": datetime.strptime(item['timestamp'], '%Y-%m-%d %H:%M:%S').strftime('%m-%Y')}
                for item in all_data
            ]

            # Membuat data entry untuk disimpan ke MongoDB
            new_entry = {
                "suhumax": suhumax,
                "suhumin": suhumin,
                "suhurata": suhurata,
                "nilai_suhu_max_humid_max": nilai_suhu_max_humid_max,
                "month_year_max": month_year_max
            }

            # Menyimpan data lengkap ke MongoDB
            collection.insert_one(new_entry)

            # Kirim data terbaru ke semua klien yang terhubung
            socketio.emit('data_update', {
                'suhu': new_data['suhu'],
                'kelembapan': new_data['kelembapan'],
                'kecerahan': new_data['kecerahan'],
                'timestamp': new_data['timestamp']
            })

        else:
            print("Data tidak lengkap atau tidak valid.")
    except Exception as e:
        print("Error parsing MQTT message:", e)


# Setup MQTT Client
mqtt_client = mqtt.Client()
mqtt_client.on_message = on_message
mqtt_client.connect(MQTT_BROKER, MQTT_PORT, 60)

# Subscribe ke topic
mqtt_client.subscribe(MQTT_TOPIC)

@app.get('/')
def index():
    return render_template("index.html")

@app.get('/json')
def get_data_json():
    # Mengambil semua data dari MongoDB
    all_data = list(collection.find({}, {'_id': 0}))  # Menghilangkan '_id' dari output

    # Convert ObjectId dan timestamp menjadi format yang serializable
    all_data_serialized = json.loads(json_util.dumps(all_data))

    # Pastikan data suhu ada, dan jika tidak, beri nilai default
    data_suhu = [data.get('suhu', None) for data in all_data_serialized]

    # Hitung nilai max, min, dan rata-rata suhu, pastikan tidak ada nilai None
    suhumax = max([suhu for suhu in data_suhu if suhu is not None], default=None)
    suhumin = min([suhu for suhu in data_suhu if suhu is not None], default=None)
    suhurata = sum([suhu for suhu in data_suhu if suhu is not None]) / len([suhu for suhu in data_suhu if suhu is not None]) if data_suhu else None

    # Mengambil bulan-tahun untuk setiap entri
    month_year_max = [
        {'month_year': datetime.strptime(data.get('timestamp', ''), '%Y-%m-%d %H:%M:%S').strftime('%m-%Y')}
        for data in all_data_serialized if data.get('timestamp')
    ]

    # Menyusun data response
    data = {
        'suhumax': suhumax,
        'suhumin': suhumin,
        'suhurata': suhurata,
        'nilai_suhu_max_humid_max': all_data_serialized,
        'month_year_max': month_year_max
    }

    return jsonify(data), 200


# Jalankan MQTT Client dalam thread terpisah
def mqtt_loop():
    mqtt_client.loop_start()

if __name__ == '__main__':
    mqtt_loop()
    socketio.run(app, host='0.0.0.0', port=43222, debug=True)
