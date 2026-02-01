import sys
import socket
import threading
import subprocess
import qrcode
import json
import os
from io import BytesIO

from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                               QLabel, QPushButton, QStackedWidget, QStackedLayout)
from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QPixmap, QImage, QCursor
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile, QWebEngineSettings

from flask import Flask, request

# --- Configuration ---
PORT = 8080
CONFIG_FILE = "deskthing_config.json"

# Default Settings
DEFAULT_CONFIG = {
    "url": "",
    "zoom": 1.0,
    "show_cursor": False
}

shared_state = {
    "config": DEFAULT_CONFIG.copy(),
    "config_updated": False
}

# --- Helper Functions ---
def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r") as f:
                data = json.load(f)
                for key, value in DEFAULT_CONFIG.items():
                    if key not in data:
                        data[key] = value
                return data
        except Exception as e:
            print(f"Error loading config: {e}")
    return DEFAULT_CONFIG.copy()

def save_config(config):
    try:
        with open(CONFIG_FILE, "w") as f:
            json.dump(config, f, indent=4)
    except Exception as e:
        print(f"Error saving config: {e}")

def get_ip_address():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return None

def check_internet():
    # If using local sites, you might not have internet but still want to proceed.
    # For now, we still check Google DNS, but if your local site is the ONLY target, 
    # we might need to relax this check later.
    try:
        socket.create_connection(("8.8.8.8", 53), timeout=1)
        return True
    except OSError:
        return False

# --- Web Server (Flask) ---
app_server = Flask(__name__)

html_template = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>DeskThing Settings</title>
    <style>
        body { background-color: #121212; color: #e0e0e0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; padding: 20px; display: flex; justify-content: center; }
        .container { max-width: 500px; width: 100%; }
        h2 { color: #ffffff; text-align: center; margin-bottom: 30px; }
        .card { background-color: #1e1e1e; padding: 25px; border-radius: 12px; box-shadow: 0 4px 6px rgba(0,0,0,0.3); }
        label { display: block; margin-bottom: 8px; font-weight: 500; color: #b0b0b0; }
        input[type="url"], input[type="number"] { width: 100%; padding: 12px; background-color: #2c2c2c; border: 1px solid #444; color: white; border-radius: 6px; margin-bottom: 20px; box-sizing: border-box; }
        input[type="checkbox"] { transform: scale(1.5); margin-right: 10px; margin-bottom: 20px; }
        button { width: 100%; padding: 15px; background-color: #6200ea; color: white; border: none; border-radius: 8px; font-size: 16px; font-weight: bold; cursor: pointer; transition: background 0.2s; }
        button:hover { background-color: #3700b3; }
        .status { text-align: center; margin-top: 15px; color: #03dac6; font-size: 0.9em; }
    </style>
</head>
<body>
    <div class="container">
        <h2>DeskThing Control</h2>
        <div class="card">
            <form method="POST">
                <label for="url">Dashboard URL</label>
                <input type="url" id="url" name="url" placeholder="http://" value="{{ url }}" required>

                <label for="zoom">Zoom Level (0.5 - 3.0)</label>
                <input type="number" id="zoom" name="zoom" step="0.1" min="0.5" max="3.0" value="{{ zoom }}">

                <div style="display: flex; align-items: center; margin-bottom: 15px;">
                    <input type="checkbox" id="show_cursor" name="show_cursor" {{ 'checked' if show_cursor else '' }}>
                    <label for="show_cursor" style="margin: 0;">Show Mouse Cursor</label>
                </div>

                <button type="submit">Save & Apply</button>
            </form>
            {% if message %}
            <div class="status">{{ message }}</div>
            {% endif %}
        </div>
    </div>
</body>
</html>
"""

@app_server.route("/", methods=["GET", "POST"])
def index():
    message = ""
    if request.method == "POST":
        new_url = request.form.get("url")
        new_zoom = float(request.form.get("zoom", 1.0))
        new_cursor = request.form.get("show_cursor") == "on"

        shared_state["config"]["url"] = new_url
        shared_state["config"]["zoom"] = new_zoom
        shared_state["config"]["show_cursor"] = new_cursor
        
        save_config(shared_state["config"])
        shared_state["config_updated"] = True
        message = "Settings updated successfully!"

    cfg = shared_state["config"]
    rendered_html = html_template.replace("{{ url }}", cfg["url"]) \
                                 .replace("{{ zoom }}", str(cfg["zoom"])) \
                                 .replace("{{ message }}", message) \
                                 .replace("{{ 'checked' if show_cursor else '' }}", "checked" if cfg["show_cursor"] else "")
    return rendered_html

def run_flask():
    app_server.run(host="0.0.0.0", port=PORT, use_reloader=False)

# --- GUI Application ---
class DeskThingApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("DeskThing")
        self.setWindowFlags(Qt.FramelessWindowHint)
        self.resize(800, 480)
        self.setStyleSheet("background-color: #1a1a1a; color: white; font-family: Arial;")

        self.stack = QStackedWidget()
        self.setCentralWidget(self.stack)

        self.view_no_internet = QWidget()
        self.view_setup = QWidget()
        self.view_web_container = QWidget()
        
        self.setup_ui_no_internet()
        self.setup_ui_setup()
        self.setup_ui_web_container()

        self.stack.addWidget(self.view_no_internet)
        self.stack.addWidget(self.view_setup)
        self.stack.addWidget(self.view_web_container)

        self.current_stack_index = -1 
        self.last_applied_url = None
        self.last_applied_zoom = -1.0
        self.last_applied_cursor = None

        shared_state["config"] = load_config()

        self.flask_thread = threading.Thread(target=run_flask, daemon=True)
        self.flask_thread.start()

        self.timer = QTimer()
        self.timer.timeout.connect(self.update_state)
        self.timer.start(1000)
        self.update_state()

    def setup_ui_no_internet(self):
        layout = QVBoxLayout()
        layout.setAlignment(Qt.AlignCenter)
        lbl = QLabel("Not connected to\ninternet")
        lbl.setAlignment(Qt.AlignCenter)
        lbl.setStyleSheet("font-size: 28px; font-weight: bold;")
        btn = QPushButton("Open xterm")
        btn.setFixedSize(200, 50)
        btn.setStyleSheet("background-color: #383838; border-radius: 8px; font-size: 16px;")
        btn.clicked.connect(self.launch_xterm)
        layout.addWidget(lbl)
        layout.addSpacing(30)
        layout.addWidget(btn, 0, Qt.AlignCenter)
        self.view_no_internet.setLayout(layout)

    def setup_ui_setup(self):
        layout = QVBoxLayout()
        layout.setAlignment(Qt.AlignCenter)
        lbl_title = QLabel("Setup your device")
        lbl_title.setStyleSheet("font-size: 32px; font-weight: bold; margin-bottom: 20px;")
        lbl_title.setAlignment(Qt.AlignCenter)
        self.qr_label = QLabel()
        self.qr_label.setAlignment(Qt.AlignCenter)
        lbl_desc = QLabel("Scan the QR code to configure")
        lbl_desc.setStyleSheet("font-size: 16px; color: #aaaaaa; margin-top: 20px;")
        lbl_desc.setAlignment(Qt.AlignCenter)
        self.ip_label = QLabel("Waiting for IP...")
        self.ip_label.setStyleSheet("font-size: 14px; color: #666; margin-top: 5px;")
        self.ip_label.setAlignment(Qt.AlignCenter)

        layout.addWidget(lbl_title)
        layout.addWidget(self.qr_label)
        layout.addWidget(lbl_desc)
        layout.addWidget(self.ip_label)
        self.view_setup.setLayout(layout)

    def setup_ui_web_container(self):
        self.web_stack_layout = QStackedLayout()
        self.web_stack_layout.setStackingMode(QStackedLayout.StackAll)

        self.lbl_fail = QLabel("WebView failed to load")
        self.lbl_fail.setAlignment(Qt.AlignCenter)
        self.lbl_fail.setStyleSheet("font-size: 24px; color: red; font-weight: bold;")
        
        self.view_web = QWebEngineView()
        self.view_web.page().setBackgroundColor(Qt.transparent)
        self.view_web.setStyleSheet("background: transparent;")
        
        # --- Allow Local Content ---
        # 1. Ignore SSL Errors (for self-signed local certs)
        self.view_web.page().certificateError.connect(self.on_cert_error)
        
        # 2. Enable Local Content Access
        settings = self.view_web.settings()
        settings.setAttribute(QWebEngineSettings.LocalContentCanAccessRemoteUrls, True)
        settings.setAttribute(QWebEngineSettings.LocalContentCanAccessFileUrls, True)
        settings.setAttribute(QWebEngineSettings.AllowRunningInsecureContent, True) # Allow HTTP
        
        self.view_web.loadFinished.connect(self.on_load_finished)

        self.web_stack_layout.addWidget(self.lbl_fail)
        self.web_stack_layout.addWidget(self.view_web)
        self.view_web_container.setLayout(self.web_stack_layout)

    def on_load_finished(self, success):
        if success:
            print(f"DEBUG: Successfully loaded {self.view_web.url().toString()}")
            self.lbl_fail.hide()
            self.view_web.show()
        else:
            print(f"DEBUG: Failed to load {self.view_web.url().toString()}")
            # DO NOT HIDE webview here immediately, or we can't inspect it.
            # But we make sure fail label is visible below it.

    def on_cert_error(self, error):
        print(f"DEBUG: Ignored Certificate Error: {error.description()}")
        return True # Return True to ignore the error and proceed loading

    def generate_qr(self, data):
        qr = qrcode.QRCode(box_size=10, border=2)
        qr.add_data(data)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        im_data = img.convert("RGBA").tobytes("raw", "RGBA")
        qim = QImage(im_data, img.size[0], img.size[1], QImage.Format_RGBA8888)
        self.qr_label.setPixmap(QPixmap.fromImage(qim))

    def update_state(self):
        # We might be strictly local, so check_internet might be false but we still want to load.
        # Modified logic: If we have a Config URL, TRY to load it regardless of internet check.
        
        has_internet = check_internet()
        cfg = shared_state["config"]
        target_url = cfg["url"]
        
        # Force Setup mode only if NO URL is set.
        if not target_url:
            target_index = 1
        elif not has_internet and "192.168" not in target_url and "10.0" not in target_url and "localhost" not in target_url:
             # If no internet AND not a local IP, show no internet screen
            target_index = 0
        else:
            # Internet exists OR it's a local IP -> Show Web
            target_index = 2

        if target_index == 1:
            ip = get_ip_address()
            if ip:
                url_display = f"http://{ip}:{PORT}"
                self.ip_label.setText(url_display)
                if self.current_stack_index != 1:
                    self.generate_qr(url_display)

        if target_index == 2:
            if self.view_web.isHidden():
                self.view_web.show()

            if self.last_applied_url != target_url:
                print(f"Loading URL: {target_url}")
                self.view_web.setUrl(QUrl(target_url))
                self.last_applied_url = target_url

            if self.last_applied_zoom != cfg["zoom"]:
                self.view_web.setZoomFactor(cfg["zoom"])
                self.last_applied_zoom = cfg["zoom"]

            if self.last_applied_cursor != cfg["show_cursor"]:
                if cfg["show_cursor"]:
                    self.setCursor(Qt.ArrowCursor)
                else:
                    self.setCursor(Qt.BlankCursor)
                self.last_applied_cursor = cfg["show_cursor"]
            
            if shared_state["config_updated"]:
                self.view_web.reload()
                shared_state["config_updated"] = False

        if self.current_stack_index != target_index:
            self.stack.setCurrentIndex(target_index)
            self.current_stack_index = target_index

    def launch_xterm(self):
        subprocess.Popen(["xterm", "-geometry", "100x30", "-fa", "Monospace", "-fs", "14"])

if __name__ == "__main__":
    # --- IMPORTANT ARGS FOR LOCAL CONTENT ---
    args = sys.argv + [
        "--ignore-certificate-errors",
        "--allow-running-insecure-content",
        "--no-sandbox"
    ]
    
    app = QApplication(args)
    window = DeskThingApp()
    if not shared_state["config"]["show_cursor"]:
        window.setCursor(Qt.BlankCursor)
    window.showFullScreen()
    sys.exit(app.exec())