import os
import requests
from flask import Flask, request, jsonify, render_template

app = Flask(__name__)

SUPABASE_URL = os.environ.get('SUPABASE_URL', '')
SUPABASE_KEY = os.environ.get('SUPABASE_KEY', '')
MAX_KEYS_PER_DEVICE = 2
KEYS_FILE = os.path.join(os.path.dirname(__file__), 'keys.txt')


# ============================================
# ĐỌC FILE keys.txt
# ============================================
def load_keys_from_file():
    """Đọc toàn bộ key từ keys.txt"""
    if not os.path.exists(KEYS_FILE):
        print(f'⚠️ Không tìm thấy file {KEYS_FILE}')
        return []

    keys = []
    with open(KEYS_FILE, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            # Bỏ dòng trống và comment
            if not line or line.startswith('#'):
                continue
            keys.append(line)

    print(f'✅ Đã load {len(keys)} key từ keys.txt')
    return keys


# Load 1 lần khi khởi động
ALL_KEYS = load_keys_from_file()


# ============================================
# HÀM GỌI SUPABASE
# ============================================
def supabase_request(method, endpoint, body=None):
    url = f"{SUPABASE_URL}/rest/v1/{endpoint}"
    headers = {
        'apikey': SUPABASE_KEY,
        'Authorization': f'Bearer {SUPABASE_KEY}',
        'Content-Type': 'application/json',
        'Prefer': 'return=representation'
    }

    try:
        if method == 'GET':
            res = requests.get(url, headers=headers, timeout=10)
        elif method == 'POST':
            res = requests.post(url, headers=headers, json=body, timeout=10)
        else:
            raise ValueError(f'Method không hỗ trợ: {method}')

        if res.status_code >= 400:
            raise Exception(f'Supabase {res.status_code}: {res.text}')

        if res.text:
            return res.json()
        return {}

    except requests.exceptions.RequestException as e:
        raise Exception(f'Lỗi kết nối Supabase: {str(e)}')


# ============================================
# ROUTES
# ============================================
@app.route('/')
def index():
    return render_template('index.html')


@app.route('/api/check-device')
def check_device():
    """Đếm số key đã lấy của device"""
    try:
        device_id = request.args.get('device_id', '').strip()
        if not device_id or len(device_id) < 5:
            return jsonify({'error': 'Thiếu device_id'}), 400

        res = supabase_request(
            'GET',
            f'used_keys?device_id=eq.{device_id}&select=key_value'
        )

        issued = len(res)
        remaining = max(0, MAX_KEYS_PER_DEVICE - issued)

        return jsonify({
            'success': True,
            'issued': issued,
            'remaining': remaining,
            'can_get': remaining > 0
        })

    except Exception as e:
        print(f'check-device error: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/get-key')
def get_key():
    """Lấy key từ file keys.txt chưa bị dùng"""
    try:
        device_id = request.args.get('device_id', '').strip()
        if not device_id or len(device_id) < 5:
            return jsonify({'error': 'Thiếu device_id'}), 400

        # Bước 1: Kiểm tra device đã lấy bao nhiêu key
        device_used = supabase_request(
            'GET',
            f'used_keys?device_id=eq.{device_id}&select=key_value'
        )
        issued_count = len(device_used)
        remaining = MAX_KEYS_PER_DEVICE - issued_count

        if remaining <= 0:
            return jsonify({
                'error': 'Đã hết lượt',
                'remaining': 0
            })

        # Bước 2: Lấy TẤT CẢ key đã dùng (toàn hệ thống)
        all_used = supabase_request('GET', 'used_keys?select=key_value')
        used_set = {item['key_value'] for item in all_used}

        # Bước 3: Tìm key trong file chưa bị dùng
        new_key = None
        for k in ALL_KEYS:
            if k not in used_set:
                new_key = k
                break

        if not new_key:
            return jsonify({'error': 'Kho đã hết key'})

        # Bước 4: Ghi key vào used_keys
        # Nếu key đã tồn tại (race condition) → Supabase trả lỗi unique
        try:
            supabase_request('POST', 'used_keys', {
                'key_value': new_key,
                'device_id': device_id
            })
        except Exception as e:
            # Key bị người khác lấy trước → retry
            if 'duplicate' in str(e).lower() or '23505' in str(e):
                return get_key()
            raise

        return jsonify({
            'success': True,
            'key': new_key,
            'remaining': remaining - 1
        })

    except Exception as e:
        print(f'get-key error: {e}')
        return jsonify({'error': f'Lỗi server: {str(e)}'}), 500


@app.route('/health')
def health():
    return 'OK'


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
