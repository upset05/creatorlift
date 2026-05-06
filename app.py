from flask import Flask, request, jsonify, send_from_directory, session
from flask_cors import CORS
import json
import os
import googleapiclient.discovery
import re

app = Flask(__name__, static_folder='.')
CORS(app)
app.secret_key = 'creatorlift_secret_key'

# --- CONFIG ---
API_KEY = "AIzaSyAkegt5QFnP_7pWolYrwPe0OyjFnysNps8"
ADMIN_PASSWORD = "admin123" 
DB_FILE = 'db.json'

def load_db():
    if not os.path.exists(DB_FILE):
        return {"orders": [], "active_target": "@MrBeast", "stats": {"revenue": 0, "hours": 0}}
    with open(DB_FILE, 'r') as f:
        return json.load(f)

def save_db(data):
    with open(DB_FILE, 'w') as f:
        json.dump(data, f, indent=4)

def get_video_id(url):
    """Extract video ID from YouTube URL"""
    pattern = r'(?:v=|\/)([0-9A-Za-z_-]{11}).*'
    match = re.search(pattern, url)
    return match.group(1) if match else None

def update_network_content(handle_or_url):
    """Fetch real YouTube data and update videos.json"""
    try:
        youtube = googleapiclient.discovery.build("youtube", "v3", developerKey=API_KEY)
        
        # Case A: It's a direct video URL
        video_id = get_video_id(handle_or_url)
        if video_id:
            res = youtube.videos().list(part="snippet", id=video_id).execute()
            if res.get("items"):
                item = res["items"][0]
                videos = [{
                    "title": item["snippet"]["title"],
                    "id": video_id,
                    "thumbnail": item["snippet"]["thumbnails"].get("maxres", item["snippet"]["thumbnails"].get("high", {}))["url"],
                    "creator": item["snippet"]["channelTitle"]
                }]
                with open("videos.json", "w") as f:
                    json.dump(videos, f, indent=4)
                return True

        # Case B: It's a channel handle
        query = handle_or_url.replace("@", "")
        search_res = youtube.search().list(q=query, type="channel", part="id", maxResults=1).execute()
        if search_res.get("items"):
            channel_id = search_res["items"][0]["id"]["channelId"]
            chan_res = youtube.channels().list(part="contentDetails", id=channel_id).execute()
            playlist_id = chan_res["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]
            play_res = youtube.playlistItems().list(part="snippet", playlistId=playlist_id, maxResults=10).execute()
            
            videos = []
            for item in play_res["items"]:
                snippet = item["snippet"]
                videos.append({
                    "title": snippet["title"],
                    "id": snippet["resourceId"]["videoId"],
                    "thumbnail": snippet["thumbnails"].get("maxres", snippet["thumbnails"].get("high", {}))["url"],
                    "creator": snippet["channelTitle"]
                })
            with open("videos.json", "w") as f:
                json.dump(videos, f, indent=4)
            return True
            
        return False
    except Exception as e:
        print(f"YouTube Update Error: {e}")
        return False

@app.route('/')
def index_page():
    return send_from_directory('.', 'index.html')

@app.route('/watch')
@app.route('/watch.html')
def watch_page():
    return send_from_directory('.', 'watch.html')

@app.route('/admin')
@app.route('/admin.html')
def admin_page():
    return send_from_directory('.', 'admin.html')

@app.route('/terms')
def terms_page():
    return send_from_directory('.', 'terms.html')

@app.route('/<path:path>')
def send_static(path):
    return send_from_directory('.', path)

@app.route('/api/order', methods=['POST'])
def place_order():
    data = request.json
    db = load_db()
    new_order = {
        "id": len(db["orders"]) + 1,
        "email": data['email'],
        "video_url": data['video_url'],
        "plan": data['plan'],
        "status": "unpaid"
    }
    db["orders"].append(new_order)
    save_db(db)
    return jsonify({"success": True})

@app.route('/api/admin/login', methods=['POST'])
def login():
    if request.json.get('password') == ADMIN_PASSWORD:
        session['logged_in'] = True
        return jsonify({"success": True})
    return jsonify({"success": False}), 401

@app.route('/api/admin/data')
def get_admin_data():
    if not session.get('logged_in'): return jsonify({"error": "Unauthorized"}), 401
    return jsonify(load_db())

@app.route('/api/admin/update-target', methods=['POST'])
def update_target():
    if not session.get('logged_in'): return jsonify({"error": "Unauthorized"}), 401
    handle = request.json.get('handle')
    if update_network_content(handle):
        db = load_db()
        db["active_target"] = handle
        save_db(db)
        return jsonify({"success": True})
    return jsonify({"success": False})

@app.route('/api/admin/activate', methods=['POST'])
def activate_order():
    if not session.get('logged_in'): return jsonify({"error": "Unauthorized"}), 401
    order_id = request.json.get('id')
    db = load_db()
    for order in db["orders"]:
        if order["id"] == order_id:
            if update_network_content(order["video_url"]):
                order["status"] = "active"
                db["active_target"] = order["video_url"]
                save_db(db)
                return jsonify({"success": True})
    return jsonify({"success": False})

@app.route('/api/admin/reset-network', methods=['POST'])
def reset_network():
    if not session.get('logged_in'): return jsonify({"error": "Unauthorized"}), 401
    # Reset to default MrBeast content or empty
    if update_network_content("@MrBeast"):
        db = load_db()
        db["active_target"] = "@MrBeast"
        save_db(db)
        return jsonify({"success": True})
    return jsonify({"success": False})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
