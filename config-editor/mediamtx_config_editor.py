#!/usr/bin/env python3
"""
MediaMTX Configuration Web Editor
Drone Video Streaming Infrastructure for Emergency Services
https://github.com/takwerx/mediamtx-installer
"""

from flask import Flask, render_template_string, request, jsonify, redirect, url_for, session, send_file, Response
from functools import wraps
from ruamel.yaml import YAML
import os
import subprocess
import time
from datetime import datetime, timedelta
import secrets
import json
import psutil  # For system metrics

app = Flask(__name__)
app.secret_key = secrets.token_hex(32)  # Generate secure secret key

# Version - used by auto-update checker
CURRENT_VERSION = "v1.0.6"
GITHUB_REPO = "takwerx/mediamtx-installer"
GITHUB_RAW_URL = f"https://raw.githubusercontent.com/{GITHUB_REPO}/main/config-editor/mediamtx_config_editor.py"
GITHUB_API_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"

# Initialize YAML handler that preserves comments
yaml = YAML()
yaml.preserve_quotes = True
yaml.default_flow_style = False

# Configuration
CONFIG_FILE = '/usr/local/etc/mediamtx.yml'
BACKUP_DIR = '/usr/local/etc/mediamtx_backups'
SERVICE_NAME = 'mediamtx'
AUTH_FILE = '/opt/mediamtx-webeditor/.auth/credentials'
GROUP_METADATA_FILE = '/opt/mediamtx-webeditor/group_names.json'
SRT_PASSPHRASE_BACKUP_FILE = '/opt/mediamtx-webeditor/srt_passphrase_backup.json'
THEME_CONFIG_FILE = '/opt/mediamtx-webeditor/theme_config.json'
LOGO_FILE = '/opt/mediamtx-webeditor/agency_logo'

# Default theme colors
DEFAULT_THEME = {
    'headerColor': '#1e3a8a',
    'headerColorEnd': '#1e293b',
    'accentColor': '#3b82f6',
    'headerTitle': 'MediaMTX Configuration Editor',
    'subtitle': 'Brought to you by TAKWERX'
}

def load_theme():
    """Load theme settings from JSON file"""
    if os.path.exists(THEME_CONFIG_FILE):
        try:
            with open(THEME_CONFIG_FILE, 'r') as f:
                theme = json.load(f)
                # Merge with defaults for any missing keys
                merged = dict(DEFAULT_THEME)
                merged.update(theme)
                return merged
        except:
            pass
    return dict(DEFAULT_THEME)

def save_theme(theme):
    """Save theme settings to JSON file"""
    os.makedirs(os.path.dirname(THEME_CONFIG_FILE), exist_ok=True)
    with open(THEME_CONFIG_FILE, 'w') as f:
        json.dump(theme, f, indent=2)

# Ensure backup directory exists
os.makedirs(BACKUP_DIR, exist_ok=True)

def load_group_metadata():
    """Load group names for MediaMTX users - maps username to group name"""
    if os.path.exists(GROUP_METADATA_FILE):
        try:
            with open(GROUP_METADATA_FILE, 'r') as f:
                return json.load(f)
        except:
            pass
    return {}

def save_group_metadata(metadata):
    """Save group names for MediaMTX users"""
    os.makedirs(os.path.dirname(GROUP_METADATA_FILE), exist_ok=True)
    with open(GROUP_METADATA_FILE, 'w') as f:
        json.dump(metadata, f, indent=2)
    os.chmod(GROUP_METADATA_FILE, 0o600)

def load_srt_passphrase_backup():
    """Load backed up SRT passphrases"""
    if os.path.exists(SRT_PASSPHRASE_BACKUP_FILE):
        try:
            with open(SRT_PASSPHRASE_BACKUP_FILE, 'r') as f:
                return json.load(f)
        except:
            pass
    return None

def save_srt_passphrase_backup(publish_pass, read_pass):
    """Save SRT passphrases to backup file"""
    os.makedirs(os.path.dirname(SRT_PASSPHRASE_BACKUP_FILE), exist_ok=True)
    with open(SRT_PASSPHRASE_BACKUP_FILE, 'w') as f:
        json.dump({'publishPassphrase': publish_pass, 'readPassphrase': read_pass}, f, indent=2)
    os.chmod(SRT_PASSPHRASE_BACKUP_FILE, 0o600)

def clear_srt_passphrase_backup():
    """Delete the backup file"""
    if os.path.exists(SRT_PASSPHRASE_BACKUP_FILE):
        os.remove(SRT_PASSPHRASE_BACKUP_FILE)

def get_hlsviewer_credential():
    """Get hlsviewer credential by reading directly from config file"""
    try:
        with open(CONFIG_FILE, 'r') as f:
            lines = f.readlines()
        
        # Find hlsviewer user and password
        for i, line in enumerate(lines):
            if 'user: hlsviewer' in line:
                # Look for password in next few lines
                for j in range(i+1, min(i+10, len(lines))):
                    if 'pass:' in lines[j]:
                        pass_line = lines[j].strip()
                        if ':' in pass_line:
                            password = pass_line.split(':', 1)[1].strip()
                            if password:
                                # Ensure it's in group metadata
                                ensure_hlsviewer_in_metadata()
                                return {'username': 'hlsviewer', 'password': password}
                break
        return None
    except Exception as e:
        print(f"Error reading hlsviewer credential: {e}")
        return None

def ensure_hlsviewer_in_metadata():
    """Ensure hlsviewer is in group_names.json"""
    try:
        metadata = load_group_metadata()
        if 'hlsviewer' not in metadata:
            metadata['hlsviewer'] = 'HLS PLAYER'
            save_group_metadata(metadata)
            print("Added hlsviewer to group metadata")
    except Exception as e:
        print(f"Error ensuring hlsviewer in metadata: {e}")

def get_streaming_domain():
    """Get HLS streaming domain and protocol (works with or without certs)"""
    try:
        with open(CONFIG_FILE, 'r') as f:
            lines = f.readlines()
        
        # First check if HLS encryption is actually enabled
        hls_encryption_on = False
        domain_from_cert = None
        
        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith('hlsEncryption:'):
                value = stripped.split(':', 1)[1].strip()
                if value.lower() in ['yes', 'true']:
                    hls_encryption_on = True
            
            if 'hlsServerCert:' in line:
                cert_path = line.split(':', 1)[1].strip() if ':' in line else ''
                
                if not cert_path and i + 1 < len(lines):
                    next_line = lines[i + 1].strip()
                    if next_line and not next_line.startswith('#'):
                        cert_path = next_line
                
                if cert_path and cert_path != '':
                    import re
                    match = re.search(r'/([a-z0-9.-]+\.[a-z]{2,})/\1\.crt', cert_path)
                    if match:
                        domain_from_cert = match.group(1)
        
        if domain_from_cert:
            return {
                'domain': domain_from_cert,
                'protocol': 'https' if hls_encryption_on else 'http'
            }
                
    except Exception as e:
        print(f"Error reading streaming domain: {e}")
    
    # No cert found - use HTTP (will use IP from request.host)
    return {
        'domain': None,
        'protocol': 'http'
    }

# Authentication decorator
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('logged_in'):
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    """Decorator for admin-only routes"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('logged_in'):
            return redirect(url_for('login'))
        if session.get('role') != 'admin':
            return redirect('/?message=Access denied: Admin privileges required&message_type=danger')
        return f(*args, **kwargs)
    return decorated_function

def load_users():
    """Load all users from JSON file"""
    users_file = '/opt/mediamtx-webeditor/users.json'
    if os.path.exists(users_file):
        try:
            with open(users_file, 'r') as f:
                return json.load(f)
        except:
            pass
    # Default admin user
    default_users = [
        {'username': 'admin', 'password': 'admin', 'role': 'admin'}
    ]
    save_users(default_users)
    return default_users

def save_users(users):
    """Save users to JSON file"""
    users_file = '/opt/mediamtx-webeditor/users.json'
    os.makedirs(os.path.dirname(users_file), exist_ok=True)
    with open(users_file, 'w') as f:
        json.dump(users, f, indent=2)
    os.chmod(users_file, 0o600)

def authenticate_user(username, password):
    """Authenticate user and return role"""
    users = load_users()
    for user in users:
        if user['username'] == username and user['password'] == password:
            return user['role']
    return None

# Login Page Template
LOGIN_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head>
    <title>{{ theme.headerTitle }}</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta name="description" content="{{ theme.subtitle }}">
    <meta property="og:title" content="{{ theme.headerTitle }}">
    <meta property="og:description" content="{{ theme.subtitle }}">
    <meta property="og:type" content="website">
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        
        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: #1a1a1a;
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 20px;
        }
        
        .login-container {
            background: #2d2d2d;
            border-radius: 12px;
            box-shadow: 0 20px 60px rgba(0,0,0,0.5);
            padding: 40px;
            width: 100%;
            max-width: 400px;
            border: 1px solid #404040;
        }
        
        .login-header {
            text-align: center;
            margin-bottom: 30px;
        }
        
        .login-header h1 {
            font-size: 1.8rem;
            color: #e5e5e5;
            margin-bottom: 10px;
        }
        
        .login-header p {
            color: #999;
        }
        
        .form-group {
            margin-bottom: 20px;
        }
        
        .form-group label {
            display: block;
            margin-bottom: 8px;
            color: #e5e5e5;
            font-weight: 500;
        }
        
        .form-group input {
            width: 100%;
            padding: 12px;
            border: 2px solid #404040;
            border-radius: 6px;
            font-size: 16px;
            transition: border-color 0.3s;
            background: #1a1a1a;
            color: #e5e5e5;
        }
        
        .form-group input:focus {
            outline: none;
            border-color: #3b82f6;
        }
        
        .btn-login {
            width: 100%;
            padding: 12px;
            background: linear-gradient(135deg, #1e3a8a 0%, #1e293b 100%);
            color: white;
            border: none;
            border-radius: 6px;
            font-size: 16px;
            font-weight: 600;
            cursor: pointer;
            transition: transform 0.2s;
        }
        
        .btn-login:hover {
            transform: translateY(-2px);
        }
        
        .alert {
            padding: 12px;
            border-radius: 6px;
            margin-bottom: 20px;
            text-align: center;
        }
        
        .alert-danger {
            background: #4a1c1c;
            color: #ff7d7d;
            border: 1px solid #6b2929;
        }
        
        .first-time-notice {
            background: #1c3a4a;
            color: #7dc7ff;
            border: 1px solid #29556b;
            padding: 15px;
            border-radius: 6px;
            margin-bottom: 20px;
            font-size: 14px;
        }
        
        .first-time-notice strong {
            display: block;
            margin-bottom: 5px;
        }
        
        /* Toggle Switch */
        .switch {
            position: relative;
            display: inline-block;
            width: 60px;
            height: 34px;
        }
        
        .switch input {
            opacity: 0;
            width: 0;
            height: 0;
        }
        
        .slider {
            position: absolute;
            cursor: pointer;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            background-color: #555;
            transition: .4s;
            border-radius: 34px;
        }
        
        .slider:before {
            position: absolute;
            content: "";
            height: 26px;
            width: 26px;
            left: 4px;
            bottom: 4px;
            background-color: white;
            transition: .4s;
            border-radius: 50%;
        }
        
        input:checked + .slider {
            background-color: #4CAF50;
        }
        
        input:checked + .slider:before {
            transform: translateX(26px);
        }
    </style>
</head>
<body>
    <div class="login-container">
        <div class="login-header">
            {% if logo_exists %}
            <img src="/api/theme/logo" alt="Logo" style="max-height: 80px; max-width: 200px; margin-bottom: 15px; border-radius: 8px;" onerror="this.style.display='none';">
            {% endif %}
            <h1>🔐 {{ theme.headerTitle }}</h1>
            <p>Please log in to continue</p>
        </div>
        
        {% if error %}
        <div class="alert alert-danger">
            {{ error }}
        </div>
        {% endif %}
        
        {% if first_time %}
        <div class="first-time-notice">
            <strong>⚠️ First Time Login</strong>
            Default credentials: admin / admin<br>
            Change your password immediately after logging in!
        </div>
        {% endif %}
        
        <form method="POST" action="/login">
            <div class="form-group">
                <label>Username</label>
                <input type="text" name="username" placeholder="Enter username" required autofocus>
            </div>
            
            <div class="form-group">
                <label>Password</label>
                <input type="password" name="password" placeholder="Enter password" required>
            </div>
            
            <button type="submit" class="btn-login">Login</button>
        </form>
    </div>
</body>
</html>
'''

# HTML Template
HTML_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head>
    <title>{{ theme.headerTitle }}</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta name="description" content="{{ theme.subtitle }}">
    <meta property="og:title" content="{{ theme.headerTitle }}">
    <meta property="og:description" content="{{ theme.subtitle }}">
    <meta property="og:type" content="website">
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        
        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: #1a1a1a;
            min-height: 100vh;
            padding: 20px;
        }
        
        .container {
            max-width: 1600px;
            margin: 0 auto;
            background: #2d2d2d;
            border-radius: 12px;
            box-shadow: 0 20px 60px rgba(0,0,0,0.5);
            overflow: hidden;
        }
        
        .header {
            background: linear-gradient(135deg, {{ theme.headerColor }} 0%, {{ theme.headerColorEnd }} 100%);
            color: white;
            padding: 30px;
            text-align: center;
            position: relative;
        }
        
        .header h1 {
            font-size: 2rem;
            margin-bottom: 10px;
        }
        
        .header p {
            opacity: 0.9;
        }
        
        .tabs {
            display: flex;
            background: #1a1a1a;
            border-bottom: 2px solid #404040;
            overflow-x: auto;
            overflow-y: hidden;
            -webkit-overflow-scrolling: touch; /* Smooth scrolling on iOS */
        }
        
        .tab {
            flex: 0 0 auto; /* Don't shrink tabs, allow scrolling instead */
            min-width: 120px; /* Minimum tab width */
            padding: 15px 20px;
            text-align: center;
            background: #1a1a1a;
            color: #999;
            border: none;
            cursor: pointer;
            font-size: 16px;
            font-weight: 500;
            transition: all 0.3s;
        }
        
        .tab:hover {
            background: #2d2d2d;
            color: #fff;
        }
        
        .tab.active {
            background: #2d2d2d;
            color: {{ theme.accentColor }};
            border-bottom: 3px solid {{ theme.accentColor }};
        }
        
        .content {
            padding: 30px;
            background: #2d2d2d;
            color: #e5e5e5;
        }
        
        .tab-content {
            display: none;
        }
        
        .tab-content.active {
            display: block;
        }
        
        .form-group {
            margin-bottom: 25px;
        }
        
        .form-group label {
            display: block;
            margin-bottom: 8px;
            font-weight: 600;
            color: #e5e5e5;
        }
        
        .form-group input,
        .form-group select,
        .form-group textarea {
            width: 100%;
            padding: 12px;
            border: 2px solid #404040;
            border-radius: 6px;
            font-size: 15px;
            transition: border-color 0.3s;
            background: #1a1a1a;
            color: #e5e5e5;
        }
        
        .form-group input:focus,
        .form-group select:focus,
        .form-group textarea:focus {
            outline: none;
            border-color: {{ theme.accentColor }};
        }
        
        .form-row {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 20px;
        }
        
        .btn {
            padding: 12px 30px;
            border: none;
            border-radius: 6px;
            font-size: 16px;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.3s;
        }
        
        .btn-primary {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
        }
        
        .btn-primary:hover {
            transform: translateY(-2px);
            box-shadow: 0 5px 15px rgba(102, 126, 234, 0.4);
        }
        
        .btn-danger {
            background: #dc3545;
            color: white;
        }
        
        .btn-danger:hover {
            background: #c82333;
            transform: translateY(-2px);
        }
        
        .btn-success {
            background: #28a745;
            color: white;
        }
        
        .btn-success:hover {
            background: #218838;
        }
        
        .btn-secondary {
            background: #6c757d;
            color: white;
        }
        
        .btn-secondary:hover {
            background: #5a6268;
        }
        
        .btn-group {
            display: flex;
            gap: 15px;
            margin-top: 20px;
        }
        
        .alert {
            padding: 15px 20px;
            border-radius: 6px;
            margin-bottom: 20px;
            font-weight: 500;
        }
        
        .alert-success {
            background: #1e4620;
            color: #7dff7d;
            border: 1px solid #2d6930;
        }
        
        .alert-danger {
            background: #4a1c1c;
            color: #ff7d7d;
            border: 1px solid #6b2929;
        }
        
        .alert-info {
            background: #1c3a4a;
            color: #7dc7ff;
            border: 1px solid #29556b;
        }
        
        .service-status {
            display: inline-block;
            padding: 5px 15px;
            border-radius: 20px;
            font-size: 14px;
            font-weight: 600;
        }
        
        .status-running {
            background: #d4edda;
            color: #155724;
        }
        
        .status-stopped {
            background: #f8d7da;
            color: #721c24;
        }
        
        .user-list {
            background: #1a1a1a;
            padding: 15px;
            border-radius: 6px;
            margin-top: 10px;
        }
        
        .user-item {
            background: #2d2d2d;
            padding: 15px;
            margin-bottom: 10px;
            border-radius: 6px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            border: 1px solid #404040;
        }
        
        textarea {
            width: 100%;
            min-height: 400px;
            font-family: 'Courier New', monospace;
            font-size: 13px;
            padding: 15px;
            border: 2px solid #404040;
            border-radius: 6px;
            background: #1a1a1a;
            color: #e5e5e5;
        }
        
        .help-text {
            font-size: 14px;
            color: #999;
            margin-top: 5px;
        }
        
        .section-title {
            font-size: 1.3rem;
            color: {{ theme.accentColor }};
            margin-bottom: 20px;
            padding-bottom: 10px;
            border-bottom: 2px solid #404040;
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <!-- Agency Logo (Left Side) -->
            <div id="header-logo" style="position: absolute; top: 50%; left: 25px; transform: translateY(-50%);">
                <img id="agency-logo-img" src="/api/theme/logo" alt="" 
                    style="max-height: 60px; max-width: 120px; {% if not logo_exists %}display: none;{% endif %} border-radius: 6px;"
                    onerror="this.style.display='none';">
                <div id="agency-logo-placeholder" style="width: 50px; height: 50px; border-radius: 8px; background: rgba(255,255,255,0.15); display: flex; align-items: center; justify-content: center; font-size: 22px; display: none;">🏢</div>
            </div>
            <h1>🎥 {{ theme.headerTitle }}</h1>
            <p>{{ theme.subtitle }}</p>
            <div style="position: absolute; top: 15px; right: 30px; color: white; display: flex; align-items: center; gap: 10px;">
                <span id="status-badge" style="padding: 6px 12px; border-radius: 5px; font-size: 14px; background: rgba(255,255,255,0.2);">
                    <span id="status-text">Loading...</span>
                </span>
                <span id="stream-badge" style="padding: 6px 12px; border-radius: 5px; font-size: 14px; background: rgba(255,255,255,0.2); display: none;">
                    🎥 <span id="stream-count">0</span> Stream<span id="stream-plural">s</span>
                </span>
            </div>
            <div style="position: absolute; bottom: 15px; right: 30px; color: white; display: flex; align-items: center; gap: 15px;">
                <span>👤 {{ username }}</span>
                <a href="/logout" style="color: white; text-decoration: none; padding: 8px 15px; background: rgba(255,255,255,0.2); border-radius: 5px;">Logout</a>
            </div>
        </div>
        
        <div class="tabs">
            {% if role == 'admin' %}
            <button class="tab {% if tab == 'dashboard' %}active{% endif %}" onclick="showTab('dashboard', event)">📊 Dashboard</button>
            <button class="tab {% if tab == 'basic' %}active{% endif %}" onclick="showTab('basic', event)">Basic Settings</button>
            <button class="tab {% if tab == 'users' %}active{% endif %}" onclick="showTab('users', event)">Users & Auth</button>
            <button class="tab {% if tab == 'protocols' %}active{% endif %}" onclick="showTab('protocols', event)">Protocols</button>
            <button class="tab {% if tab == 'sources' %}active{% endif %}" onclick="showTab('sources', event)">External Sources</button>
            <button class="tab {% if tab == 'advanced' %}active{% endif %}" onclick="showTab('advanced', event)">Advanced YAML</button>
            <button class="tab {% if tab == 'service' %}active{% endif %}" onclick="showTab('service', event)">Service Control</button>
            <button class="tab {% if tab == 'logs' %}active{% endif %}" onclick="showTab('logs', event)">Live Logs</button>
            {% endif %}
            <button class="tab {% if role == 'viewer' %}active{% endif %}" onclick="showTab('streams', event)">Active Streams</button>
            {% if role == 'admin' %}
            <button class="tab {% if tab == 'test' %}active{% endif %}" onclick="showTab('test', event)">Test Streams</button>
            <button class="tab {% if tab == 'recordings' %}active{% endif %}" onclick="showTab('recordings', event)">Recordings</button>
            <button class="tab {% if tab == 'webusers' %}active{% endif %}" onclick="showTab('webusers', event)">Web Users</button>
            <button class="tab {% if tab == 'account' %}active{% endif %}" onclick="showTab('account', event)">Account</button>
            <button class="tab {% if tab == 'styling' %}active{% endif %}" onclick="showTab('styling', event)">🎨 Styling</button>
            {% endif %}
        </div>
        
        <div class="content">
            {% if message %}
            <div class="alert alert-{{ message_type }}" id="flash-message">
                {{ message }}
            </div>
            <script>
                // Auto-dismiss flash messages after 3 seconds
                setTimeout(function() {
                    const msg = document.getElementById('flash-message');
                    if (msg) {
                        msg.style.transition = 'opacity 0.5s';
                        msg.style.opacity = '0';
                        setTimeout(function() {
                            msg.remove();
                            // Clean URL (remove message params)
                            const url = new URL(window.location);
                            url.searchParams.delete('message');
                            url.searchParams.delete('message_type');
                            window.history.replaceState({}, '', url);
                        }, 500);
                    }
                }, 3000);
            </script>
            {% endif %}
            
            {% if role == 'admin' %}
            <!-- Dashboard Tab -->
            <div id="dashboard" class="tab-content {% if tab == 'dashboard' %}active{% endif %}">
                <h2 class="section-title">📊 Server Health Dashboard</h2>
                
                <!-- Update Banner (hidden by default, shown when update available) -->
                <div id="update-banner" style="display: none; margin-bottom: 20px; padding: 20px; border-radius: 10px; background: linear-gradient(135deg, #1a3a1a 0%, #1a2e1a 100%); border: 1px solid #2d5a2d;">
                    <div style="display: flex; justify-content: space-between; align-items: flex-start; flex-wrap: wrap; gap: 15px;">
                        <div style="flex: 1; min-width: 250px;">
                            <div style="font-size: 16px; font-weight: bold; color: #4ade80; margin-bottom: 6px;">
                                🆕 Update Available: <span id="update-remote-version"></span>
                            </div>
                            <div style="font-size: 13px; color: #999; margin-bottom: 10px;">
                                You are running <span id="update-current-version" style="color: #e5e5e5;"></span> · 
                                Published <span id="update-published"></span>
                            </div>
                            <div id="update-release-notes" style="font-size: 14px; color: #ccc; white-space: pre-wrap; max-height: 150px; overflow-y: auto; padding: 10px; background: rgba(0,0,0,0.2); border-radius: 6px;"></div>
                        </div>
                        <div style="display: flex; flex-direction: column; gap: 8px; min-width: 160px;">
                            <button class="btn btn-success" onclick="applyUpdate()" id="update-apply-btn" style="padding: 10px 20px;">
                                ⬆️ Update Now
                            </button>
                            <a id="update-github-link" href="#" target="_blank" style="text-align: center; color: #999; font-size: 13px; text-decoration: none;">
                                View on GitHub →
                            </a>
                            <button onclick="dismissUpdate()" style="background: none; border: none; color: #666; cursor: pointer; font-size: 12px; padding: 4px;">
                                Dismiss
                            </button>
                        </div>
                    </div>
                    <div id="update-progress" style="display: none; margin-top: 15px;">
                        <div style="padding: 12px; background: rgba(0,0,0,0.3); border-radius: 6px; color: #e5e5e5; font-size: 14px;">
                            <span id="update-progress-text">⏳ Downloading update...</span>
                        </div>
                    </div>
                </div>
                
                <!-- Version Info (shown when up to date) -->
                <div id="version-badge" style="display: none; margin-bottom: 10px; padding: 10px 15px; border-radius: 6px; background: rgba(255,255,255,0.05); border: 1px solid #333; font-size: 13px; color: #888;">
                    ✅ Web Editor <span id="version-current"></span> — up to date
                </div>
                
                <!-- MediaMTX Version Info (shown when up to date) -->
                <div id="mediamtx-version-badge" style="display: none; margin-bottom: 20px; padding: 10px 15px; border-radius: 6px; background: rgba(255,255,255,0.05); border: 1px solid #333; font-size: 13px; color: #888;">
                    ✅ MediaMTX <span id="mediamtx-version-current"></span> — up to date
                </div>
                
                <!-- MediaMTX Update Banner (hidden by default) -->
                <div id="mediamtx-update-banner" style="display: none; margin-bottom: 20px; padding: 20px; border-radius: 10px; background: linear-gradient(135deg, #1a2a3a 0%, #1a1e3a 100%); border: 1px solid #2d4a6d;">
                    <div style="display: flex; justify-content: space-between; align-items: flex-start; flex-wrap: wrap; gap: 15px;">
                        <div style="flex: 1; min-width: 250px;">
                            <div style="font-size: 16px; font-weight: bold; color: #60a5fa; margin-bottom: 6px;">
                                🆕 MediaMTX Update Available: <span id="mediamtx-update-remote-version"></span>
                            </div>
                            <div style="font-size: 13px; color: #999; margin-bottom: 10px;">
                                You are running MediaMTX <span id="mediamtx-update-current-version" style="color: #e5e5e5;"></span> · 
                                Published <span id="mediamtx-update-published"></span>
                            </div>
                            <div id="mediamtx-update-release-notes" style="font-size: 14px; color: #ccc; white-space: pre-wrap; max-height: 150px; overflow-y: auto; padding: 10px; background: rgba(0,0,0,0.2); border-radius: 6px;"></div>
                        </div>
                        <div style="display: flex; flex-direction: column; gap: 8px; min-width: 160px;">
                            <button class="btn" onclick="applyMediaMTXUpdate()" id="mediamtx-update-apply-btn" style="padding: 10px 20px; background: #2563eb; color: white; border: none; border-radius: 6px; cursor: pointer;">
                                ⬆️ Upgrade MediaMTX
                            </button>
                            <button onclick="skipMediaMTXUpdate()" id="mediamtx-skip-btn" style="background: none; border: 1px solid #555; color: #aaa; cursor: pointer; font-size: 12px; padding: 6px 12px; border-radius: 4px;">
                                Skip this version
                            </button>
                            <a id="mediamtx-update-github-link" href="#" target="_blank" style="text-align: center; color: #999; font-size: 13px; text-decoration: none;">
                                View on GitHub →
                            </a>
                            <button onclick="dismissMediaMTXUpdate()" style="background: none; border: none; color: #666; cursor: pointer; font-size: 12px; padding: 4px;">
                                Dismiss
                            </button>
                        </div>
                    </div>
                    <div id="mediamtx-update-progress" style="display: none; margin-top: 15px;">
                        <div style="padding: 12px; background: rgba(0,0,0,0.3); border-radius: 6px; color: #e5e5e5; font-size: 14px;">
                            <span id="mediamtx-update-progress-text">⏳ Upgrading MediaMTX...</span>
                        </div>
                    </div>
                </div>
                
                <!-- MediaMTX Rollback Banner (hidden by default) -->
                <div id="mediamtx-rollback-banner" style="display: none; margin-bottom: 20px; padding: 10px 15px; border-radius: 6px; background: rgba(255,255,255,0.05); border: 1px solid #6d4a2d; font-size: 13px; color: #999;">
                    ⏪ Previous version <span id="rollback-version" style="color: #e5e5e5;"></span> backed up — <span id="rollback-reason" style="color: #ccc;"></span>
                    <button class="btn" onclick="rollbackMediaMTX()" id="mediamtx-rollback-btn" style="margin-left: 10px; padding: 4px 12px; background: #d97706; color: white; border: none; border-radius: 4px; cursor: pointer; font-size: 12px;">
                        ⏪ Rollback
                    </button>
                </div>
                
                <!-- Top Stats Row -->
                <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 20px; margin-bottom: 30px;">
                    <!-- Active Streams -->
                    <div style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); padding: 25px; border-radius: 12px; color: white; box-shadow: 0 4px 15px rgba(0,0,0,0.2);">
                        <div style="font-size: 14px; opacity: 0.9; margin-bottom: 8px;">Active Streams</div>
                        <div id="active-streams-count" style="font-size: 48px; font-weight: bold;">-</div>
                    </div>
                    
                    <!-- Total Viewers -->
                    <div style="background: linear-gradient(135deg, #f093fb 0%, #f5576c 100%); padding: 25px; border-radius: 12px; color: white; box-shadow: 0 4px 15px rgba(0,0,0,0.2);">
                        <div style="font-size: 14px; opacity: 0.9; margin-bottom: 8px;">Total Viewers</div>
                        <div id="total-viewers-count" style="font-size: 48px; font-weight: bold;">-</div>
                    </div>
                    
                    <!-- Recordings Size -->
                    <div style="background: linear-gradient(135deg, #4facfe 0%, #00f2fe 100%); padding: 25px; border-radius: 12px; color: white; box-shadow: 0 4px 15px rgba(0,0,0,0.2);">
                        <div style="font-size: 14px; opacity: 0.9; margin-bottom: 8px;">Recordings</div>
                        <div id="recordings-size" style="font-size: 48px; font-weight: bold;">-</div>
                    </div>
                    
                    <!-- Server Uptime -->
                    <div style="background: linear-gradient(135deg, #43e97b 0%, #38f9d7 100%); padding: 25px; border-radius: 12px; color: white; box-shadow: 0 4px 15px rgba(0,0,0,0.2);">
                        <div style="font-size: 14px; opacity: 0.9; margin-bottom: 8px;">Uptime</div>
                        <div id="server-uptime" style="font-size: 32px; font-weight: bold;">-</div>
                    </div>
                </div>
                
                <!-- System Resources Row -->
                <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 20px; margin-bottom: 30px;">
                    <!-- CPU Gauge -->
                    <div class="card">
                        <h3 style="margin: 0 0 20px 0; color: #4CAF50;">💻 CPU Usage</h3>
                        <div style="position: relative; width: 200px; height: 200px; margin: 0 auto;">
                            <canvas id="cpu-gauge" width="200" height="200"></canvas>
                            <div id="cpu-percent" style="position: absolute; top: 50%; left: 50%; transform: translate(-50%, -50%); font-size: 36px; font-weight: bold;">-</div>
                        </div>
                    </div>
                    
                    <!-- RAM Gauge -->
                    <div class="card">
                        <h3 style="margin: 0 0 20px 0; color: #4CAF50;">🧠 RAM Usage</h3>
                        <div style="position: relative; width: 200px; height: 200px; margin: 0 auto;">
                            <canvas id="ram-gauge" width="200" height="200"></canvas>
                            <div id="ram-percent" style="position: absolute; top: 50%; left: 50%; transform: translate(-50%, -50%); font-size: 36px; font-weight: bold;">-</div>
                        </div>
                    </div>
                    
                    <!-- Disk Usage -->
                    <div class="card">
                        <h3 style="margin: 0 0 20px 0; color: #4CAF50;">💾 Disk Usage</h3>
                        <div id="disk-usage-info" style="text-align: center; padding: 20px;">
                            <div style="font-size: 48px; font-weight: bold; margin-bottom: 10px;" id="disk-percent">-</div>
                            <div style="color: #999; font-size: 14px;" id="disk-details">-</div>
                        </div>
                    </div>
                </div>
                
                <!-- Network Stats -->
                <div class="card" style="margin-bottom: 30px;">
                    <h3 style="margin: 0 0 20px 0; color: #4CAF50;">🌐 Network Activity</h3>
                    <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 30px;">
                        <div>
                            <div style="color: #999; font-size: 14px; margin-bottom: 5px;">↓ Received</div>
                            <div id="network-rx" style="font-size: 32px; font-weight: bold; color: #4CAF50;">-</div>
                        </div>
                        <div>
                            <div style="color: #999; font-size: 14px; margin-bottom: 5px;">↑ Sent</div>
                            <div id="network-tx" style="font-size: 32px; font-weight: bold; color: #FF9800;">-</div>
                        </div>
                    </div>
                </div>
            </div>
            
            <!-- Basic Settings Tab -->
            <div id="basic" class="tab-content {% if tab == 'basic' %}active{% endif %}">
                <h2 class="section-title">Basic Configuration</h2>
                <form method="POST" action="/save_basic">
                    <input type="hidden" name="current_tab" class="tab-tracker" value="basic">
                    <div class="form-group">
                        <label>Log Level</label>
                        <select name="logLevel">
                            <option value="error" {% if config.logLevel == 'error' %}selected{% endif %}>Error</option>
                            <option value="warn" {% if config.logLevel == 'warn' %}selected{% endif %}>Warning</option>
                            <option value="info" {% if config.logLevel == 'info' %}selected{% endif %}>Info</option>
                            <option value="debug" {% if config.logLevel == 'debug' %}selected{% endif %}>Debug</option>
                        </select>
                        <p class="help-text">Level of logging detail</p>
                    </div>
                    
                    <div class="form-row">
                        <div class="form-group">
                            <label>Read Timeout</label>
                            <input type="text" name="readTimeout" value="{{ config.readTimeout }}" placeholder="10s">
                            <p class="help-text">Connection read timeout</p>
                        </div>
                        
                        <div class="form-group">
                            <label>Write Timeout</label>
                            <input type="text" name="writeTimeout" value="{{ config.writeTimeout }}" placeholder="10s">
                            <p class="help-text">Connection write timeout</p>
                        </div>
                    </div>
                    
                    <button type="submit" class="btn btn-primary">Save Basic Settings</button>
                </form>
            </div>
            
            <!-- Users Tab -->
            <div id="users" class="tab-content {% if tab == 'users' %}active{% endif %}">
                <h2 class="section-title">MediaMTX Stream Authentication</h2>
                <p class="help-text">Manage who can publish and view streams on this MediaMTX server</p>
                
                <!-- Public Access Toggle -->
                <div style="margin-top: 20px; padding: 15px; background: #2d2d2d; border-radius: 8px; border: 2px solid #444;">
                    <div style="display: flex; align-items: center; justify-content: space-between;">
                        <div>
                            <strong style="font-size: 16px;">⚠️ Public Access (All Streams)</strong>
                            <p class="help-text" style="margin: 5px 0 0 0;">When enabled, ALL streams viewable without authentication</p>
                        </div>
                        <label class="switch">
                            <input type="checkbox" id="public-access-toggle" onchange="togglePublicAccess()">
                            <span class="slider"></span>
                        </label>
                    </div>
                </div>
                
                <div class="alert alert-info" style="margin-top: 20px;">
                    <strong>💡 How it works:</strong><br>
                    Create user accounts for different agencies/groups. Each user needs credentials to publish (stream) or read (view) from MediaMTX.<br>
                    Perfect for giving different agencies their own login credentials!
                </div>
                
                <button class="btn btn-primary" onclick="showAddMediaMTXUserForm()" style="margin-top: 20px;">+ Add Authorized User</button>
                
                <div id="add-mediamtx-user-form" style="display: none; margin-top: 20px; padding: 20px; background: #2d2d2d; border-radius: 8px;">
                    <h3>Add New MediaMTX User</h3>
                    <form id="mediamtx-user-form">
                        <div class="form-group">
                            <label>Group/Agency Name</label>
                            <input type="text" id="mtx-group-name" list="existing-groups" placeholder="e.g., Highway Patrol, Fire Department" required>
                            <datalist id="existing-groups">
                                <!-- Populated dynamically with existing groups -->
                            </datalist>
                            <p class="help-text">This appears as a comment in the config for organization. Select existing or type new.</p>
                        </div>
                        <div class="form-group">
                            <label>Username</label>
                            <input type="text" id="mtx-username" placeholder="Enter username" required>
                            <p class="help-text" style="color: #ff9800;">⚠️ Allowed: A-Z, 0-9, special chars • NO spaces, commas, apostrophes, slashes</p>
                        </div>
                        <div class="form-group">
                            <label>Password</label>
                            <input type="text" id="mtx-password" placeholder="Enter password (blank for 'any' user)">
                            <p class="help-text">Password will be visible in config (for easier sharing with agencies)</p>
                            <p class="help-text" style="color: #ff9800; margin-top: 5px;">⚠️ Allowed: A-Z, 0-9, special chars (!$*.@#&) • NOT allowed: spaces, commas, apostrophes, slashes</p>
                        </div>
                        <div class="form-group">
                            <label>Permissions</label>
                            <div style="margin-top: 10px;">
                                <label style="display: block; margin-bottom: 8px;">
                                    <input type="checkbox" id="mtx-perm-read" checked> 
                                    <strong>Read</strong> - View/pull streams from server
                                </label>
                                <label style="display: block; margin-bottom: 8px;">
                                    <input type="checkbox" id="mtx-perm-publish" checked> 
                                    <strong>Publish</strong> - Push/stream to server
                                </label>
                                <label style="display: block; margin-bottom: 8px;">
                                    <input type="checkbox" id="mtx-perm-playback" checked> 
                                    <strong>Playback</strong> - Access recorded streams
                                </label>
                            </div>
                        </div>
                        <button type="submit" class="btn btn-primary">Create User</button>
                        <button type="button" class="btn btn-secondary" onclick="hideAddMediaMTXUserForm()">Cancel</button>
                    </form>
                </div>
                
                <h3 style="margin-top: 30px;">Current Authorized Users</h3>
                <div id="mediamtx-users-list">
                    <p style="color: #999;">Loading...</p>
                </div>
            </div>
            
            <!-- Protocols Tab -->
            <div id="protocols" class="tab-content {% if tab == 'protocols' %}active{% endif %}">
                <h2 class="section-title">Protocol Settings</h2>
                
                <!-- Protocol Enable/Disable Toggles -->
                <div style="margin-bottom: 30px; padding: 20px; background: #2d2d2d; border-radius: 8px; border: 2px solid #444;">
                    <h3 style="margin: 0 0 15px 0;">Enable/Disable Protocols</h3>
                    <p class="help-text" style="margin-bottom: 20px;">Turn protocols on or off globally. Disabled protocols will not accept any connections.</p>
                    
                    <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 15px;">
                        <div style="padding: 15px; background: #1a1a1a; border-radius: 6px;">
                            <div style="display: flex; align-items: center; justify-content: space-between;">
                                <strong>RTSP</strong>
                                <label class="switch">
                                    <input type="checkbox" id="protocol-rtsp-toggle" onchange="toggleProtocol('rtsp')">
                                    <span class="slider"></span>
                                </label>
                            </div>
                        </div>
                        
                        <div style="padding: 15px; background: #1a1a1a; border-radius: 6px;">
                            <div style="display: flex; align-items: center; justify-content: space-between;">
                                <strong>HLS</strong>
                                <label class="switch">
                                    <input type="checkbox" id="protocol-hls-toggle" onchange="toggleProtocol('hls')">
                                    <span class="slider"></span>
                                </label>
                            </div>
                        </div>
                        
                        <div style="padding: 15px; background: #1a1a1a; border-radius: 6px;">
                            <div style="display: flex; align-items: center; justify-content: space-between;">
                                <strong>SRT</strong>
                                <label class="switch">
                                    <input type="checkbox" id="protocol-srt-toggle" onchange="toggleProtocol('srt')">
                                    <span class="slider"></span>
                                </label>
                            </div>
                        </div>
                    </div>
                </div>
                
                <form method="POST" action="/save_protocols">
                    <input type="hidden" name="current_tab" class="tab-tracker" value="protocols">
                    <h3>RTSP Settings</h3>
                    <div class="form-row">
                        <div class="form-group">
                            <label>RTSP Port</label>
                            <input type="number" name="rtspAddress" value="{{ config.rtspAddress.split(':')[1] if ':' in config.rtspAddress else '8554' }}" placeholder="8554">
                        </div>
                        
                        <div class="form-group">
                            <label>Transport Protocol</label>
                            <select name="rtspTransports" onchange="this.form.submit()">
                                <option value="tcp" {% if rtsp_transport_mode == 'tcp' %}selected{% endif %}>TCP only (recommended)</option>
                                <option value="udp,tcp" {% if rtsp_transport_mode == 'udp_tcp' %}selected{% endif %}>UDP + TCP</option>
                                <option value="udp,multicast,tcp" {% if rtsp_transport_mode == 'all' %}selected{% endif %}>All (UDP + Multicast + TCP)</option>
                            </select>
                            <p class="help-text" style="margin-top: 8px;">
                                <strong>TCP only:</strong> Works through NAT/firewalls, best for internet streams<br>
                                <strong>UDP + TCP:</strong> Allows both, client chooses (UDP may fail behind NAT)<br>
                                <strong>All:</strong> Includes multicast for LAN environments
                            </p>
                        </div>
                        
                        <div class="form-group">
                            <label>Encryption</label>
                            <select name="rtspEncryption" onchange="this.form.submit()">
                                <option value="no" {% if config.rtspEncryption == 'no' %}selected{% endif %}>No</option>
                                <option value="optional" {% if config.rtspEncryption == 'optional' %}selected{% endif %}>Optional</option>
                                <option value="strict" {% if config.rtspEncryption == 'strict' %}selected{% endif %}>Strict</option>
                            </select>
                            <p class="help-text" style="margin-top: 8px;">
                                <strong>No:</strong> Only port 8554 (unencrypted)<br>
                                <strong>Optional:</strong> Port 8554 (unencrypted) + Port 8322 (SSL)<br>
                                <strong>Strict:</strong> Only port 8322 (SSL)
                            </p>
                            {% if not config.rtspServerCert or not config.rtspServerCert.strip() %}
                            <div class="alert alert-warning" style="margin-top: 12px;">
                                <strong>⚠️ Certificates Not Configured!</strong><br>
                                Setting encryption to "Optional" or "Strict" without certificates will cause MediaMTX to crash.<br>
                                <strong>Do not change from "No"</strong> until you run the Caddy installer to obtain Let's Encrypt certificates.
                            </div>
                            {% endif %}
                        </div>
                    </div>
                    
                    <h3 style="margin-top: 30px;">RTSPS Settings (RTSP over SSL)</h3>
                    <div class="alert alert-info" style="margin-bottom: 20px;">
                        <strong>🔐 Encrypted RTSP:</strong> RTSPS encrypts RTSP streams using SSL/TLS. Requires certificates (automatically configured by Caddy installer).
                    </div>
                    <div class="form-row">
                        <div class="form-group">
                            <label>RTSPS Port</label>
                            <input type="number" name="rtspsAddress" value="{{ config.rtspsAddress.split(':')[1] if ':' in config.rtspsAddress else '8322' }}" placeholder="8322">
                            <p class="help-text">SSL/TLS encrypted RTSP port</p>
                        </div>
                        
                        <div class="form-group">
                            <label>Encryption Mode</label>
                            <div style="background: #383838; padding: 12px; border-radius: 6px; border: 1px solid #4a4a4a;">
                                {% if config.rtspEncryption == 'no' %}
                                <strong style="color: #ff9800;">⚠️ Disabled (RTSPS not available)</strong>
                                <p class="help-text" style="margin-top: 8px; margin-bottom: 0;">
                                    Port 8322 is closed. Set RTSP Encryption to "Optional" or "Strict" above to enable RTSPS.
                                </p>
                                {% elif config.rtspEncryption == 'optional' %}
                                <strong style="color: #4CAF50;">✓ Optional (Both RTSP & RTSPS work)</strong>
                                <p class="help-text" style="margin-top: 8px; margin-bottom: 0;">
                                    Port 8554: Unencrypted (rtsp://)<br>
                                    Port 8322: SSL Encrypted (rtsps://)
                                </p>
                                {% elif config.rtspEncryption == 'strict' %}
                                <strong style="color: #2196F3;">🔒 Strict (RTSPS only)</strong>
                                <p class="help-text" style="margin-top: 8px; margin-bottom: 0;">
                                    Port 8554: Disabled<br>
                                    Port 8322: SSL Encrypted (rtsps://)
                                </p>
                                {% endif %}
                            </div>
                            <p class="help-text" style="margin-top: 8px;">
                                <em>Status reflects RTSP Encryption setting above. Change it there to modify this.</em>
                            </p>
                        </div>
                    </div>
                    
                    {% if config.rtspServerCert and config.rtspServerCert.strip() %}
                    <div class="alert alert-success" style="padding-left: 15px; white-space: nowrap; overflow-x: auto;">
                        <strong>✓ Certificates Configured:</strong><br>
                        <small>Cert: {{ config.rtspServerCert }}</small>
                    </div>
                    {% else %}
                    <div class="alert alert-warning">
                        <strong>⚠ Certificates Not Configured:</strong> Run the Caddy installer to automatically configure Let's Encrypt certificates for RTSPS encryption.
                    </div>
                    {% endif %}
                    
                    
                    <h3 style="margin-top: 30px;">HLS Settings</h3>
                    <div class="form-row">
                        <div class="form-group">
                            <label>HLS Port</label>
                            <input type="number" name="hlsAddress" value="{{ config.hlsAddress.split(':')[1] if ':' in config.hlsAddress else '8888' }}" placeholder="8888">
                        </div>
                    </div>
                    
                    {% if config.hlsServerCert and config.hlsServerCert.strip() %}
                    <!-- Certificates configured - show cert box, force encryption on -->
                    <input type="hidden" name="hlsEncryption" value="yes">
                    <div class="alert alert-success" style="padding-left: 15px; white-space: nowrap; overflow-x: auto;">
                        <strong>✓ Certificates Configured:</strong><br>
                        <small>Cert: {{ config.hlsServerCert }}</small>
                    </div>
                    {% else %}
                    <!-- No certificates - show warning, disable encryption -->
                    <input type="hidden" name="hlsEncryption" value="no">
                    <div class="alert alert-warning">
                        <strong>⚠ Certificates Not Configured:</strong> Run the Caddy installer to automatically configure Let's Encrypt certificates for HTTPS encryption for HLS streams.
                    </div>
                    {% endif %}
                    
                    <h3 style="margin-top: 30px;">SRT Settings</h3>
                    <div class="form-group">
                        <label>SRT Port</label>
                        <input type="number" name="srtAddress" value="{{ config.srtAddress.split(':')[1] if ':' in config.srtAddress else '8890' }}" placeholder="8890">
                        <p class="help-text">UDP port for SRT streaming</p>
                    </div>
                    
                    <div class="alert alert-info" style="margin-top: 20px;">
                        <strong>🔐 SRT Passphrases</strong> - Secure your SRT streams with encryption. These passphrases are stored in the <code>pathDefaults</code> section and apply to all streams.
                    </div>
                    
                    <div class="form-group">
                        <label>SRT Publish Passphrase (for streaming TO server)</label>
                        <input type="text" name="srtPublishPassphrase" value="{% if 'pathDefaults' in config and config.pathDefaults.get('srtPublishPassphrase') is not none %}{{ config.pathDefaults.get('srtPublishPassphrase') }}{% endif %}" placeholder="Leave empty for no passphrase">
                        <p class="help-text">Required when publishing/pushing streams via SRT (e.g., from OBS). Must be 10-79 characters or left blank.</p>
                    </div>
                    
                    <div class="form-group">
                        <label>SRT Read Passphrase (for viewing FROM server)</label>
                        <input type="text" name="srtReadPassphrase" value="{% if 'pathDefaults' in config and config.pathDefaults.get('srtReadPassphrase') is not none %}{{ config.pathDefaults.get('srtReadPassphrase') }}{% endif %}" placeholder="Leave empty for no passphrase">
                        <p class="help-text">Required when viewing/pulling streams via SRT (e.g., from VLC). Must be 10-79 characters or left blank.</p>
                    </div>
                    
                    <div class="alert alert-info">
                        <strong>💡 Tip:</strong> Use the same passphrase for both, or different ones for publish vs. read. Passphrase must be 10-79 characters. After saving, MediaMTX will automatically restart.
                    </div>
                    
                    <button type="submit" class="btn btn-primary">Save Protocol Settings & Restart MediaMTX</button>
                </form>
            </div>
            
            <!-- External Sources Tab -->
            <div id="sources" class="tab-content {% if tab == 'sources' %}active{% endif %}">
                <h2 class="section-title">📡 External Sources</h2>
                <p class="help-text">Pull streams from other agencies' servers. MediaMTX connects to their server and rebroadcasts the stream through yours.</p>
                
                <div class="alert alert-info" style="margin-top: 20px;">
                    <strong>💡 How it works:</strong><br>
                    Add external stream sources here. MediaMTX will connect to them and rebroadcast through your server, just like local drone streams.<br><br>
                    <strong>Supported protocols:</strong> SRT, RTSP, UDP MPEG-TS, RTMP, HLS<br><br>
                    <strong>Two ways agencies share:</strong><br>
                    1. <strong>They push to us</strong> — Create a user for them in Users & Auth. No external source needed.<br>
                    2. <strong>We pull from them</strong> — Add their URL here. This tab handles that.
                </div>
                
                <button class="btn btn-primary" onclick="showAddSourceForm()" style="margin-top: 20px;">+ Add External Source</button>
                
                <div id="add-source-form" style="display: none; margin-top: 20px; padding: 20px; background: #2d2d2d; border-radius: 8px; border: 1px solid #404040;">
                    <h3>Add External Source</h3>
                    <form id="external-source-form">
                        <div class="form-group">
                            <label>Stream Name</label>
                            <input type="text" id="source-name" placeholder="e.g., chp_air1, fd_drone2">
                            <p class="help-text">This becomes the path name viewers use: rtsp://yourserver:8554/<strong>chp_air1</strong></p>
                            <p class="help-text" style="color: #ff9800;">⚠️ Allowed: lowercase letters, numbers, underscores. No spaces or special characters.</p>
                        </div>
                        <div class="form-group">
                            <label>Protocol</label>
                            <select id="source-protocol" onchange="updateSourceFormFields()">
                                <option value="srt">SRT (recommended for agency-to-agency)</option>
                                <option value="rtsp">RTSP (IP cameras, RTSP servers)</option>
                                <option value="udp">UDP MPEG-TS (multicast, encoders)</option>
                                <option value="rtmp">RTMP (RTMP servers)</option>
                                <option value="hls">HLS (HTTP streams)</option>
                            </select>
                        </div>
                        <div id="srt-source-fields">
                            <div class="form-row">
                                <div class="form-group">
                                    <label>SRT Server Address</label>
                                    <input type="text" id="source-srt-host" placeholder="e.g., their.server.com">
                                    <p class="help-text">Hostname or IP of their SRT server</p>
                                </div>
                                <div class="form-group">
                                    <label>Port</label>
                                    <input type="number" id="source-srt-port" placeholder="8890" value="8890">
                                    <p class="help-text">SRT port (default: 8890)</p>
                                </div>
                            </div>
                            <div class="form-group">
                                <label>Connection Mode</label>
                                <select id="source-srt-mode">
                                    <option value="caller">Caller — We connect to their server</option>
                                    <option value="listener">Listener — We listen, they connect to us</option>
                                </select>
                                <p class="help-text">Caller: Your server reaches out to theirs. Listener: Your server waits for them to connect in.</p>
                            </div>
                            <div class="form-group">
                                <label>Stream ID (optional)</label>
                                <input type="text" id="source-srt-streamid" placeholder="e.g., air1, drone2 (leave blank if not needed)">
                                <p class="help-text">Optional. The stream name on their server. Leave blank if they only use port-based routing.</p>
                            </div>
                            <div class="form-group">
                                <label>Passphrase (optional)</label>
                                <div style="position: relative;">
                                    <input type="password" id="source-srt-passphrase" placeholder="Leave empty if not required" style="padding-right: 60px;">
                                    <button type="button" onclick="const f=document.getElementById('source-srt-passphrase'); const b=this; if(f.type==='password'){f.type='text';b.textContent='Hide';}else{f.type='password';b.textContent='Show';}" style="position: absolute; right: 8px; top: 50%; transform: translateY(-50%); background: #555; color: #fff; border: none; border-radius: 3px; padding: 4px 10px; cursor: pointer; font-size: 12px;">Show</button>
                                </div>
                                <p class="help-text">SRT encryption passphrase if their server requires one</p>
                            </div>
                        </div>
                        <div id="rtsp-source-fields" style="display: none;">
                            <div class="form-group">
                                <label>Encryption</label>
                                <select id="source-rtsp-secure">
                                    <option value="rtsp">rtsp:// (standard)</option>
                                    <option value="rtsps">rtsps:// (encrypted)</option>
                                </select>
                            </div>
                            <div class="form-row">
                                <div class="form-group">
                                    <label>Host</label>
                                    <input type="text" id="source-rtsp-host" placeholder="e.g., their.server.com">
                                    <p class="help-text">Hostname or IP of their RTSP server</p>
                                </div>
                                <div class="form-group">
                                    <label>Port</label>
                                    <input type="number" id="source-rtsp-port" placeholder="554" value="554">
                                    <p class="help-text">Default: 554</p>
                                </div>
                            </div>
                            <div class="form-group">
                                <label>Path</label>
                                <input type="text" id="source-rtsp-path" placeholder="e.g., live/stream1 or cam1">
                                <p class="help-text">Stream path on their server (no leading slash)</p>
                            </div>
                            <div class="form-row">
                                <div class="form-group">
                                    <label>Username (optional)</label>
                                    <input type="text" id="source-rtsp-user" placeholder="Leave empty if not required">
                                </div>
                                <div class="form-group">
                                    <label>Password (optional)</label>
                                    <div style="position: relative;">
                                        <input type="password" id="source-rtsp-pass" placeholder="Leave empty if not required" style="padding-right: 60px;">
                                        <button type="button" onclick="const f=document.getElementById('source-rtsp-pass'); const b=this; if(f.type==='password'){f.type='text';b.textContent='Hide';}else{f.type='password';b.textContent='Show';}" style="position: absolute; right: 8px; top: 50%; transform: translateY(-50%); background: #555; color: #fff; border: none; border-radius: 3px; padding: 4px 10px; cursor: pointer; font-size: 12px;">Show</button>
                                    </div>
                                </div>
                            </div>
                        </div>
                        <div id="udp-source-fields" style="display: none;">
                            <div class="form-group">
                                <label>Listen Port</label>
                                <input type="number" id="source-udp-port" placeholder="5004" value="5004">
                                <p class="help-text">UDP port your server will listen on. Give the sender your server IP and this port. A firewall rule will be created automatically.</p>
                            </div>
                            <div class="form-group">
                                <label>Source IP Filter (optional)</label>
                                <input type="text" id="source-udp-filter" placeholder="e.g., 192.168.1.100">
                                <p class="help-text">Only accept packets from this IP address. Recommended for security. Leave empty to accept from any source.</p>
                            </div>
                        </div>
                        <div id="rtmp-source-fields" style="display: none;">
                            <div class="form-group">
                                <label>Encryption</label>
                                <select id="source-rtmp-secure">
                                    <option value="rtmp">rtmp:// (standard)</option>
                                    <option value="rtmps">rtmps:// (encrypted)</option>
                                </select>
                            </div>
                            <div class="form-row">
                                <div class="form-group">
                                    <label>Host</label>
                                    <input type="text" id="source-rtmp-host" placeholder="e.g., their.server.com">
                                    <p class="help-text">Hostname or IP of their RTMP server</p>
                                </div>
                                <div class="form-group">
                                    <label>Port</label>
                                    <input type="number" id="source-rtmp-port" placeholder="1935" value="1935">
                                    <p class="help-text">Default: 1935</p>
                                </div>
                            </div>
                            <div class="form-group">
                                <label>Path / Stream Key</label>
                                <input type="text" id="source-rtmp-path" placeholder="e.g., live/stream1">
                                <p class="help-text">Stream path or key on their server (no leading slash)</p>
                            </div>
                        </div>
                        <div id="hls-source-fields" style="display: none;">
                            <div class="form-group">
                                <label>HLS Playlist URL</label>
                                <input type="text" id="source-hls-url" placeholder="e.g., https://their.server.com/stream/index.m3u8">
                                <p class="help-text">Full URL to the .m3u8 playlist. Supports http:// and https://</p>
                            </div>
                        </div>
                        <button type="submit" class="btn btn-primary">Add Source</button>
                        <button type="button" class="btn btn-secondary" onclick="hideAddSourceForm()">Cancel</button>
                    </form>
                </div>
                
                <h3 style="margin-top: 30px;">Configured External Sources</h3>
                <div id="external-sources-list" style="margin-top: 10px;">
                    <p style="color: #999;">Loading...</p>
                </div>
            </div>
            
            <!-- Advanced YAML Tab -->
            <div id="advanced" class="tab-content {% if tab == 'advanced' %}active{% endif %}">
                <h2 class="section-title">Advanced YAML Editor</h2>
                
                <!-- User Management Warning -->
                <div class="alert alert-warning" style="margin-bottom: 15px;">
                    <strong>⚠️ User Management:</strong> Do NOT edit users (authInternalUsers section) here! 
                    Use the <strong>Users & Auth</strong> tab to manage users safely. Direct editing can break authentication.
                </div>
                
                <!-- Search Tips Banner -->
                <div class="alert alert-info" style="margin-bottom: 15px;">
                    <strong>🔍 Quick Search Tip:</strong> Use your browser's search to quickly find settings:<br>
                    <kbd style="background: #333; padding: 3px 6px; border-radius: 3px; margin: 5px 5px 0 0;">Cmd+F</kbd> (Mac) or 
                    <kbd style="background: #333; padding: 3px 6px; border-radius: 3px;">Ctrl+F</kbd> (Windows/Linux)<br>
                    <small style="opacity: 0.8;">Try searching for: hlsTrustedProxies, authInternalUsers, rtspEncryption, paths</small>
                </div>
                
                <!-- Restart Reminder -->
                <div class="alert alert-warning">
                    <strong>⚠️ Important:</strong> After making changes, you MUST restart MediaMTX for changes to take effect. 
                    Go to the <strong>Service Control</strong> tab and click "Restart Service" after saving.
                </div>
                
                <div class="alert alert-info">
                    ⚠️ <strong>Warning:</strong> Direct YAML editing can break the configuration if syntax is invalid. Always create a backup first!
                </div>
                
                <!-- Refresh Button -->
                <button onclick="refreshYAML()" class="btn btn-success" style="margin-bottom: 15px;">🔄 Refresh YAML</button>
                
                <form method="POST" action="/save_yaml" id="yaml-form">
                    <input type="hidden" name="current_tab" class="tab-tracker" value="advanced">
                    <div class="form-group">
                        <textarea name="yaml_content" id="yaml-textarea">{{ yaml_content }}</textarea>
                    </div>
                    
                    <div class="btn-group">
                        <button type="submit" class="btn btn-primary">Save YAML</button>
                        <button type="submit" formaction="/validate_yaml" class="btn btn-success">Validate Only</button>
                    </div>
                </form>
            </div>
            
            <!-- Service Control Tab -->
            <div id="service" class="tab-content {% if tab == 'service' %}active{% endif %}">
                <h2 class="section-title">Service Management</h2>
                
                <div class="form-group">
                    <label>Service Status</label>
                    <div>
                        <span class="service-status status-{{ 'running' if service_status.active else 'stopped' }}">
                            {% if service_status.active %}
                                ● Running
                            {% else %}
                                ○ Stopped
                            {% endif %}
                        </span>
                    </div>
                </div>
                
                <div class="btn-group">
                    <form method="POST" action="/service/restart" style="margin: 0;">
                        <input type="hidden" name="current_tab" class="tab-tracker" value="service">
                        <button type="submit" class="btn btn-primary">Restart Service</button>
                    </form>
                    
                    <form method="POST" action="/service/stop" style="margin: 0;">
                        <input type="hidden" name="current_tab" class="tab-tracker" value="service">
                        <button type="submit" class="btn btn-danger">Stop Service</button>
                    </form>
                    
                    <form method="POST" action="/service/start" style="margin: 0;">
                        <input type="hidden" name="current_tab" class="tab-tracker" value="service">
                        <button type="submit" class="btn btn-success">Start Service</button>
                    </form>
                </div>
                
                <h3 style="margin-top: 40px; margin-bottom: 15px;">Backup Management</h3>
                <form method="POST" action="/backup">
                    <button type="submit" class="btn btn-success">Create Backup Now</button>
                </form>
                
                <div class="form-group" style="margin-top: 20px;">
                    <label>Recent Backups</label>
                    <div class="user-list">
                        {% for backup in backups %}
                        <div class="user-item">
                            <span>{{ backup }}</span>
                            <form method="POST" action="/restore/{{ backup }}" style="margin: 0;">
                                <button type="submit" class="btn btn-primary" onclick="return confirm('Restore this backup? This will restart the service.')">Restore</button>
                            </form>
                        </div>
                        {% endfor %}
                        {% if not backups %}
                        <p class="help-text">No backups found</p>
                        {% endif %}
                    </div>
                </div>
            </div>
            
            <!-- Live Logs Tab -->
            <div id="logs" class="tab-content {% if tab == 'logs' %}active{% endif %}">
                <h2 class="section-title">📊 Live MediaMTX Logs</h2>
                <p class="help-text">Real-time service logs (like journalctl -fu mediamtx)</p>
                
                <div style="margin-bottom: 15px;">
                    <button onclick="clearLogs()" class="btn btn-danger" style="margin-right: 10px;">Clear Logs</button>
                    <button onclick="restartLogs()" class="btn btn-success" style="margin-right: 10px;">Restart Logs</button>
                    <button onclick="toggleAutoScroll()" class="btn btn-primary" id="autoScrollBtn">Auto-Scroll: ON</button>
                </div>
                
                <div id="logContainer" style="background: #1e1e1e; color: #d4d4d4; padding: 20px; border-radius: 8px; height: 600px; overflow-y: auto; font-family: 'Courier New', monospace; font-size: 13px; line-height: 1.5;">
                    <div id="logContent">Connecting to log stream...</div>
                </div>
            </div>
            
            <!-- Account Tab -->
            <div id="account" class="tab-content {% if tab == 'account' %}active{% endif %}">
                <h2 class="section-title">Account Settings</h2>
                <p class="help-text">Manage your configuration editor login credentials</p>
                
                <form method="POST" action="/change_password">
                    <input type="hidden" name="current_tab" class="tab-tracker" value="account">
                    <h3 style="margin-top: 20px; margin-bottom: 15px;">Change Password</h3>
                    
                    <div class="form-group">
                        <label>Current Password</label>
                        <input type="text" name="current_password" placeholder="Enter current password" required>
                    </div>
                    
                    <div class="form-group">
                        <label>New Password</label>
                        <input type="text" name="new_password" placeholder="Enter new password (min 4 characters)" required>
                        <p class="help-text">Minimum 4 characters</p>
                    </div>
                    
                    <div class="form-group">
                        <label>Confirm New Password</label>
                        <input type="text" name="confirm_password" placeholder="Confirm new password" required>
                    </div>
                    
                    <button type="submit" class="btn btn-primary">Change Password</button>
                </form>
                
                <div class="alert alert-info" style="margin-top: 30px;">
                    <strong>ℹ️ Security Note:</strong> This password protects access to the configuration editor (port 5000). It is separate from MediaMTX authentication credentials.
                </div>
            </div>
            
            <!-- Styling Tab -->
            <div id="styling" class="tab-content {% if tab == 'styling' %}active{% endif %}">
                <h2 class="section-title">🎨 Styling & Theme</h2>
                <p class="help-text">Customize the look and feel of your MediaMTX Configuration Editor</p>
                
                <!-- Live Preview -->
                <div style="margin-top: 20px; margin-bottom: 25px;">
                    <h3 style="margin-bottom: 10px;">Live Preview</h3>
                    <div id="theme-preview" style="border-radius: 8px; overflow: hidden; border: 2px solid #404040;">
                        <div id="preview-header" style="background: linear-gradient(135deg, {{ theme.headerColor }} 0%, {{ theme.headerColorEnd }} 100%); color: white; padding: 20px; text-align: center;">
                            <div id="preview-title" style="font-size: 1.3rem; font-weight: bold;">🎥 {{ theme.headerTitle }}</div>
                            <div id="preview-subtitle" style="opacity: 0.9; font-size: 0.9rem; margin-top: 4px;">{{ theme.subtitle }}</div>
                        </div>
                        <div style="background: #1a1a1a; display: flex; gap: 0; border-bottom: 2px solid #404040;">
                            <div style="padding: 10px 18px; color: #999; font-size: 14px;">Dashboard</div>
                            <div id="preview-active-tab" style="padding: 10px 18px; color: {{ theme.accentColor }}; font-size: 14px; border-bottom: 3px solid {{ theme.accentColor }};">Active Tab</div>
                            <div style="padding: 10px 18px; color: #999; font-size: 14px;">Settings</div>
                        </div>
                        <div style="background: #2d2d2d; padding: 15px;">
                            <div id="preview-section-title" style="font-size: 1.1rem; color: {{ theme.accentColor }}; margin-bottom: 8px; padding-bottom: 8px; border-bottom: 2px solid #404040;">📊 Section Title</div>
                            <div style="color: #999; font-size: 0.9rem;">This is how your themed interface will look.</div>
                        </div>
                    </div>
                </div>
                
                <!-- Preset Themes -->
                <div style="margin-bottom: 25px;">
                    <h3 style="margin-bottom: 10px;">Quick Presets</h3>
                    <div style="display: flex; flex-wrap: wrap; gap: 10px;">
                        <button class="btn btn-secondary" style="padding: 8px 16px; font-size: 14px;" onclick="applyPreset('#1e3a8a', '#1e293b', '#3b82f6')">
                            <span style="display:inline-block; width:12px; height:12px; border-radius:50%; background:#1e3a8a; margin-right:6px; vertical-align:middle;"></span>Default Blue
                        </button>
                        <button class="btn btn-secondary" style="padding: 8px 16px; font-size: 14px;" onclick="applyPreset('#7f1d1d', '#451a1a', '#ef4444')">
                            <span style="display:inline-block; width:12px; height:12px; border-radius:50%; background:#7f1d1d; margin-right:6px; vertical-align:middle;"></span>Fire Red
                        </button>
                        <button class="btn btn-secondary" style="padding: 8px 16px; font-size: 14px;" onclick="applyPreset('#14532d', '#1a2e1a', '#22c55e')">
                            <span style="display:inline-block; width:12px; height:12px; border-radius:50%; background:#14532d; margin-right:6px; vertical-align:middle;"></span>Tactical Green
                        </button>
                        <button class="btn btn-secondary" style="padding: 8px 16px; font-size: 14px;" onclick="applyPreset('#78350f', '#451a03', '#f59e0b')">
                            <span style="display:inline-block; width:12px; height:12px; border-radius:50%; background:#78350f; margin-right:6px; vertical-align:middle;"></span>Alert Orange
                        </button>
                        <button class="btn btn-secondary" style="padding: 8px 16px; font-size: 14px;" onclick="applyPreset('#581c87', '#2e1065', '#a855f7')">
                            <span style="display:inline-block; width:12px; height:12px; border-radius:50%; background:#581c87; margin-right:6px; vertical-align:middle;"></span>Purple
                        </button>
                        <button class="btn btn-secondary" style="padding: 8px 16px; font-size: 14px;" onclick="applyPreset('#1e293b', '#0f172a', '#64748b')">
                            <span style="display:inline-block; width:12px; height:12px; border-radius:50%; background:#1e293b; margin-right:6px; vertical-align:middle;"></span>Stealth Gray
                        </button>
                        <button class="btn btn-secondary" style="padding: 8px 16px; font-size: 14px;" onclick="applyPreset('#5c4a32', '#3b2f1e', '#c2a66b')">
                            <span style="display:inline-block; width:12px; height:12px; border-radius:50%; background:#5c4a32; margin-right:6px; vertical-align:middle;"></span>Desert Tan
                        </button>
                    </div>
                </div>
                
                <!-- Agency Logo -->
                <div style="margin-bottom: 25px;">
                    <h3 style="margin-bottom: 10px;">Agency / Business Logo</h3>
                    <p class="help-text" style="margin-bottom: 15px;">Upload a logo to display on the left side of the header bar. Recommended size: 120×60px or smaller. PNG or JPG.</p>
                    <div style="display: flex; align-items: center; gap: 20px; flex-wrap: wrap;">
                        <!-- Current Logo Preview -->
                        <div id="logo-preview-box" style="width: 120px; height: 70px; background: rgba(255,255,255,0.1); border-radius: 8px; border: 2px dashed #555; display: flex; align-items: center; justify-content: center; overflow: hidden;">
                            <img id="logo-preview-img" src="" style="max-width: 110px; max-height: 60px; display: none; border-radius: 4px;">
                            <span id="logo-preview-placeholder" style="color: #666; font-size: 13px;">No logo</span>
                        </div>
                        <!-- Upload Controls -->
                        <div style="display: flex; flex-direction: column; gap: 10px;">
                            <div>
                                <input type="file" id="logo-upload-input" accept="image/png,image/jpeg,image/gif,image/svg+xml,image/webp" 
                                    onchange="previewLogoUpload(this)" style="display: none;">
                                <button class="btn btn-secondary" style="padding: 8px 16px; font-size: 14px;" onclick="document.getElementById('logo-upload-input').click();">📁 Choose File</button>
                                <button class="btn btn-secondary" style="padding: 8px 16px; font-size: 14px;" onclick="uploadLogo();" id="logo-upload-btn" disabled>⬆️ Upload</button>
                                <button class="btn btn-secondary" style="padding: 8px 16px; font-size: 14px;" onclick="removeLogo();">🗑️ Remove</button>
                            </div>
                            <span id="logo-filename" style="color: #999; font-size: 13px;">No file selected</span>
                        </div>
                    </div>
                </div>
                
                <!-- Header Text -->
                <div style="margin-bottom: 25px;">
                    <h3 style="margin-bottom: 15px;">Header Text</h3>
                    <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 20px;">
                        <div style="background: #1a1a1a; padding: 15px; border-radius: 8px; border: 1px solid #404040;">
                            <label style="display: block; margin-bottom: 8px; font-weight: 600; color: #e5e5e5;">Title</label>
                            <p class="help-text" style="margin-bottom: 10px;">Main heading shown in the top bar and login page</p>
                            <input type="text" id="theme-headerTitle" value="{{ theme.headerTitle }}" maxlength="100"
                                oninput="updateTextPreview()"
                                style="width: 100%; padding: 10px; background: #2d2d2d; border: 1px solid #404040; color: #e5e5e5; border-radius: 4px; font-size: 15px; box-sizing: border-box;">
                        </div>
                        <div style="background: #1a1a1a; padding: 15px; border-radius: 8px; border: 1px solid #404040;">
                            <label style="display: block; margin-bottom: 8px; font-weight: 600; color: #e5e5e5;">Subtitle</label>
                            <p class="help-text" style="margin-bottom: 10px;">Smaller text below the title (e.g. agency name, tagline)</p>
                            <input type="text" id="theme-subtitle" value="{{ theme.subtitle }}" maxlength="100"
                                oninput="updateTextPreview()"
                                style="width: 100%; padding: 10px; background: #2d2d2d; border: 1px solid #404040; color: #e5e5e5; border-radius: 4px; font-size: 15px; box-sizing: border-box;">
                        </div>
                    </div>
                </div>
                
                <!-- Custom Colors -->
                <div style="margin-bottom: 25px;">
                    <h3 style="margin-bottom: 15px;">Custom Colors</h3>
                    <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(250px, 1fr)); gap: 20px;">
                        
                        <!-- Header Start Color -->
                        <div style="background: #1a1a1a; padding: 15px; border-radius: 8px; border: 1px solid #404040;">
                            <label style="display: block; margin-bottom: 8px; font-weight: 600; color: #e5e5e5;">Header Color (Left)</label>
                            <p class="help-text" style="margin-bottom: 10px;">Primary gradient color for the top bar</p>
                            <div style="display: flex; align-items: center; gap: 10px;">
                                <input type="color" id="theme-headerColor" value="{{ theme.headerColor }}" 
                                    onchange="updatePreview()" 
                                    style="width: 50px; height: 40px; border: none; cursor: pointer; background: none; padding: 0;">
                                <input type="text" id="theme-headerColor-text" value="{{ theme.headerColor }}" 
                                    onchange="document.getElementById('theme-headerColor').value = this.value; updatePreview();"
                                    style="flex: 1; padding: 8px; background: #2d2d2d; border: 1px solid #404040; color: #e5e5e5; border-radius: 4px; font-family: monospace;">
                            </div>
                        </div>
                        
                        <!-- Header End Color -->
                        <div style="background: #1a1a1a; padding: 15px; border-radius: 8px; border: 1px solid #404040;">
                            <label style="display: block; margin-bottom: 8px; font-weight: 600; color: #e5e5e5;">Header Color (Right)</label>
                            <p class="help-text" style="margin-bottom: 10px;">Secondary gradient color for the top bar</p>
                            <div style="display: flex; align-items: center; gap: 10px;">
                                <input type="color" id="theme-headerColorEnd" value="{{ theme.headerColorEnd }}" 
                                    onchange="updatePreview()" 
                                    style="width: 50px; height: 40px; border: none; cursor: pointer; background: none; padding: 0;">
                                <input type="text" id="theme-headerColorEnd-text" value="{{ theme.headerColorEnd }}" 
                                    onchange="document.getElementById('theme-headerColorEnd').value = this.value; updatePreview();"
                                    style="flex: 1; padding: 8px; background: #2d2d2d; border: 1px solid #404040; color: #e5e5e5; border-radius: 4px; font-family: monospace;">
                            </div>
                        </div>
                        
                        <!-- Accent Color -->
                        <div style="background: #1a1a1a; padding: 15px; border-radius: 8px; border: 1px solid #404040;">
                            <label style="display: block; margin-bottom: 8px; font-weight: 600; color: #e5e5e5;">Accent Color</label>
                            <p class="help-text" style="margin-bottom: 10px;">Active tabs, section titles, and focus highlights</p>
                            <div style="display: flex; align-items: center; gap: 10px;">
                                <input type="color" id="theme-accentColor" value="{{ theme.accentColor }}" 
                                    onchange="updatePreview()" 
                                    style="width: 50px; height: 40px; border: none; cursor: pointer; background: none; padding: 0;">
                                <input type="text" id="theme-accentColor-text" value="{{ theme.accentColor }}" 
                                    onchange="document.getElementById('theme-accentColor').value = this.value; updatePreview();"
                                    style="flex: 1; padding: 8px; background: #2d2d2d; border: 1px solid #404040; color: #e5e5e5; border-radius: 4px; font-family: monospace;">
                            </div>
                        </div>
                    </div>
                </div>
                
                <!-- Save / Reset Buttons -->
                <div style="display: flex; gap: 15px; margin-top: 25px;">
                    <button class="btn btn-primary" onclick="saveTheme()">💾 Save Theme</button>
                    <button class="btn btn-secondary" onclick="applyPreset('#1e3a8a', '#1e293b', '#3b82f6'); document.getElementById('theme-headerTitle').value='MediaMTX Configuration Editor'; document.getElementById('theme-subtitle').value='Brought to you by TAKWERX'; updateTextPreview();">↩️ Reset to Default</button>
                </div>
                
                <div id="theme-status" style="margin-top: 15px; display: none;"></div>
                
                <div class="alert alert-info" style="margin-top: 30px;">
                    <strong>ℹ️ Note:</strong> Theme changes are saved to a config file on the server and apply to all users. The page will reload after saving to fully apply the new theme.
                </div>
            </div>
            {% endif %}
            
            <!-- Active Streams Tab -->
            <div id="streams" class="tab-content {% if role == 'viewer' %}active{% endif %}">
                <h2 class="section-title">Active Streams</h2>
                <p class="help-text">View and monitor all active streams on this MediaMTX server</p>
                
                <div id="streams-container" style="margin-top: 20px;">
                    <p style="color: #999;">Loading streams...</p>
                </div>
            </div>
            
            {% if role == 'admin' %}
            <!-- Test Streams Tab -->
            <div id="test" class="tab-content {% if tab == 'test' %}active{% endif %}">
                <h2 class="section-title">Test Streams</h2>
                <p class="help-text">Upload and stream test video files (.ts format) to verify your MediaMTX setup</p>
                
                <!-- Test Stream Viewer Toggle -->
                <div style="margin-top: 20px; padding: 15px; background: #2d2d2d; border-radius: 8px; border: 2px solid #444;">
                    <div style="display: flex; align-items: center; justify-content: space-between;">
                        <div>
                            <strong style="font-size: 16px;">📡 Test Stream Viewing (teststream path only)</strong>
                            <p class="help-text" style="margin: 5px 0 0 0;">Allow viewing test streams without credentials (does not affect other streams)</p>
                            <p style="margin: 5px 0 0 0; color: #ff9800; font-size: 13px;">⚠️ Stop streaming before toggling, then restart stream for changes to take effect</p>
                        </div>
                        <label class="switch">
                            <input type="checkbox" id="teststream-viewer-toggle" onchange="toggleTestStreamViewer()">
                            <span class="slider"></span>
                        </label>
                    </div>
                </div>
                
                <!-- SRT Passphrase Info -->
                <div style="margin-top: 20px; padding: 15px; background: #2d2d2d; border-radius: 8px; border: 2px solid #444;">
                    <div>
                        <strong style="font-size: 16px;">🔐 SRT Passphrase Status</strong>
                        <p id="srt-passphrase-value" style="margin: 8px 0 0 0; font-size: 14px; font-family: monospace;"></p>
                        <p id="srt-passphrase-help" class="help-text" style="margin: 8px 0 0 0;"></p>
                    </div>
                </div>

                <div class="alert alert-info" style="margin-top: 20px;">
                    <strong>💡 How it works:</strong> Upload a .ts video file, then click "Stream" to publish it via FFmpeg to MediaMTX. Perfect for testing ATAK video feeds, VLC playback, and HLS streaming without needing a live camera.
                </div>
                
                <!-- Stream URLs Info Box -->
                <div id="stream-urls-box" style="margin-top: 20px; padding: 20px; background: #1a1a1a; border-radius: 8px; border: 2px solid #4CAF50;">
                    <h3 style="margin: 0 0 10px 0; color: #4CAF50;">📺 Stream URLs (when streaming is active)</h3>
                    <div id="stream-urls-content" style="font-family: monospace; font-size: 14px;">
                        <p style="color: #999; font-style: italic;">Start streaming to see URLs...</p>
                    </div>
                </div>
                
                <form id="upload-test-file" enctype="multipart/form-data" style="margin-top: 20px;">
                    <div class="form-group">
                        <label>Upload Test Video (.ts file)</label>
                        <input type="file" id="test-file-input" name="test_file" accept=".ts" required>
                        <p class="help-text">Select a .ts transport stream file to upload</p>
                    </div>
                    <button type="submit" class="btn btn-primary">Upload</button>
                    <button type="button" id="cancel-upload-btn" class="btn" style="display: none; background: #f44336; margin-left: 10px;" onclick="cancelUpload()">Cancel Upload</button>
                    <div id="upload-progress" style="display: none; margin-top: 10px;">
                        <div style="background: #444; height: 20px; border-radius: 10px; overflow: hidden;">
                            <div id="upload-progress-bar" style="background: #4CAF50; height: 100%; width: 0%; transition: width 0.3s;"></div>
                        </div>
                        <p id="upload-status" style="margin-top: 5px; color: #999;"></p>
                    </div>
                </form>
                
                <h3 style="margin-top: 30px;">Available Test Files</h3>
                
                <div style="margin: 15px 0; padding: 15px; background: #1a4d6d; border-left: 4px solid #2196F3; border-radius: 4px;">
                    <p style="margin: 0 0 10px 0; color: #fff; font-size: 14px; line-height: 1.6;">
                        💡 <strong>Tip:</strong> Test videos loop continuously. Watch all the way through - if you see freezing, 
                        stuttering, or playback issues, click "Optimize" to create a compatible version. 
                        You can then delete the original if needed.
                    </p>
                    <p style="margin: 0; color: #b3e5fc; font-size: 13px; line-height: 1.5;">
                        ⏱️ <strong>Optimization time:</strong> ~5 minutes per 100MB (varies by server). Only optimize one file at a time.<br>
                        ⚠️ <strong>Note:</strong> Optimization fixes most encoding issues but cannot repair corrupted frames or damaged video files.
                    </p>
                </div>
                
                <div id="test-files-container">
                    <p style="color: #999;">Loading...</p>
                </div>
            </div>
            
            <!-- Recordings Tab -->
            <div id="recordings" class="tab-content {% if tab == 'recordings' %}active{% endif %}">
                <h2 class="section-title">📹 Stream Recordings</h2>
                <p class="help-text">Manage automatic recording of streams (teststream excluded)</p>
                
                <!-- Recording Settings -->
                <div style="background: #2d2d2d; padding: 20px; border-radius: 8px; margin-bottom: 30px;">
                    <h3 style="margin: 0 0 20px 0; color: #4CAF50;">⚙️ Recording Settings</h3>
                    
                    
                    <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 20px; margin-bottom: 20px;">
                        <!-- Enable/Disable Recording -->
                        <div>
                            <label style="display: block; margin-bottom: 10px; color: #fff; font-weight: bold;">
                                📼 Auto-Record Streams
                            </label>
                            <label class="toggle-switch">
                                <input type="checkbox" id="recording-enabled">
                                <span class="toggle-slider"></span>
                            </label>
                            <p style="margin: 10px 0 0 0; color: #999; font-size: 13px;">
                                Automatically record all active streams (teststream excluded)
                            </p>
                        </div>
                        
                        <!-- Retention Period -->
                        <div>
                            <label style="display: block; margin-bottom: 10px; color: #fff; font-weight: bold;">
                                🗑️ Auto-Delete After
                            </label>
                            <select id="recording-retention" style="width: 100%; padding: 10px; background: #1a1a1a; color: #fff; border: 1px solid #444; border-radius: 4px;">
                                <option value="24h">1 Day</option>
                                <option value="72h">3 Days</option>
                                <option value="168h">7 Days</option>
                                <option value="336h">14 Days</option>
                                <option value="720h">30 Days</option>
                                <option value="0">Never (Keep Forever)</option>
                            </select>
                            <p style="margin: 10px 0 0 0; color: #999; font-size: 13px;">
                                Recordings older than this will be automatically deleted
                            </p>
                        </div>
                    </div>
                    
                    <div style="margin-bottom: 20px;">
                        <label style="display: block; margin-bottom: 10px; color: #fff; font-weight: bold;">
                            🌍 Display Timezone
                        </label>
                        <select id="recording-timezone" onchange="saveTimezone()" style="width: 100%; padding: 10px; background: #1a1a1a; color: #fff; border: 1px solid #444; border-radius: 4px;">
                            <option value="UTC">UTC (Server Time)</option>
                            <option value="America/New_York">Eastern Time (ET)</option>
                            <option value="America/Chicago">Central Time (CT)</option>
                            <option value="America/Denver">Mountain Time (MT)</option>
                            <option value="America/Los_Angeles">Pacific Time (PT)</option>
                            <option value="America/Anchorage">Alaska Time (AKT)</option>
                            <option value="Pacific/Honolulu">Hawaii Time (HST)</option>
                            <option value="Europe/London">London (GMT/BST)</option>
                            <option value="Europe/Paris">Paris (CET/CEST)</option>
                            <option value="Asia/Tokyo">Tokyo (JST)</option>
                            <option value="Australia/Sydney">Sydney (AEDT/AEST)</option>
                        </select>
                        <p style="margin: 10px 0 0 0; color: #999; font-size: 13px;">
                            Choose your local timezone for displaying recording times (stored in browser)
                        </p>
                    </div>
                    
                    <button onclick="saveRecordingSettings()" class="btn btn-primary" style="width: 100%;">
                        💾 Save Recording Settings
                    </button>
                </div>
                
                <!-- Disk Usage -->
                <div id="disk-usage-container" style="background: #2d2d2d; padding: 20px; border-radius: 8px; margin-bottom: 30px;">
                    <h3 style="margin: 0 0 15px 0; color: #4CAF50;">💾 Disk Usage</h3>
                    <div id="disk-usage-content">
                        <p style="color: #999;">Loading disk usage...</p>
                    </div>
                </div>
                
                <!-- Recordings List -->
                <div style="background: #2d2d2d; padding: 20px; border-radius: 8px;">
                    <h3 style="margin: 0 0 15px 0; color: #4CAF50;">📁 Recorded Files</h3>
                    <div id="recordings-list">
                        <p style="color: #999;">Loading recordings...</p>
                    </div>
                </div>
            </div>
            
            <!-- Web Users Management Tab -->
            <div id="webusers" class="tab-content {% if tab == 'webusers' %}active{% endif %}">
                <h2 class="section-title">Web Editor Users</h2>
                <p class="help-text">Manage who can access this configuration editor</p>
                
                <div class="alert alert-info" style="margin-top: 20px;">
                    <strong>👥 User Roles:</strong><br>
                    <strong>Admin:</strong> Full access to all settings and configuration<br>
                    <strong>Viewer:</strong> Can only view Active Streams tab (perfect for customers)
                </div>
                
                <button class="btn btn-primary" onclick="showAddUserForm()" style="margin-top: 20px;">+ Add User</button>
                
                <div id="add-user-form" style="display: none; margin-top: 20px; padding: 20px; background: #2d2d2d; border-radius: 8px;">
                    <h3>Add New User</h3>
                    <div class="form-group">
                        <label>Username</label>
                        <input type="text" id="new-username" placeholder="Enter username">
                    </div>
                    <div class="form-group">
                        <label>Password</label>
                        <input type="text" id="new-password" placeholder="Enter password (min 4 characters)">
                    </div>
                    <div class="form-group">
                        <label>Role</label>
                        <select id="new-role">
                            <option value="viewer">Viewer (streams only)</option>
                            <option value="admin">Admin (full access)</option>
                        </select>
                    </div>
                    <button class="btn btn-primary" onclick="addUser()">Create User</button>
                    <button class="btn btn-secondary" onclick="hideAddUserForm()">Cancel</button>
                </div>
                
                <h3 style="margin-top: 30px;">Current Users</h3>
                <div id="users-list-container">
                    <p style="color: #999;">Loading...</p>
                </div>
            </div>
            {% endif %}
        </div>
    </div>
    
    <script>
        let autoScroll = true;
        let logEventSource = null;
        
        function showTab(tabName, event) {
            // Hide all tabs
            const tabs = document.querySelectorAll('.tab');
            const contents = document.querySelectorAll('.tab-content');
            
            tabs.forEach(tab => tab.classList.remove('active'));
            contents.forEach(content => content.classList.remove('active'));
            
            // Show selected tab
            if (event && event.target) {
                event.target.classList.add('active');
            } else {
                // Fallback: find and activate the correct tab button
                document.querySelectorAll('.tab').forEach(tab => {
                    if (tab.getAttribute('onclick') && tab.getAttribute('onclick').includes(tabName)) {
                        tab.classList.add('active');
                    }
                });
            }
            document.getElementById(tabName).classList.add('active');
            
            // Update all hidden tab tracker fields
            document.querySelectorAll('.tab-tracker').forEach(tracker => {
                tracker.value = tabName;
            });
            
            // Start dashboard refresh when Dashboard tab is opened
            if (tabName === 'dashboard') {
                startDashboardRefresh();
            } else {
                stopDashboardRefresh();
            }
            
            // Start log streaming when Logs tab is opened
            if (tabName === 'logs' && !logEventSource) {
                startLogStream();
            }
            
            // Load users when Users & Auth tab is opened
            if (tabName === 'users' && typeof loadMediaMTXUsers === 'function') {
                loadMediaMTXUsers();
            }
            
            // Load external sources when External Sources tab is opened
            if (tabName === 'sources' && typeof loadExternalSources === 'function') {
                loadExternalSources();
                // Start auto-refresh
                if (!sourcesRefreshInterval) {
                    sourcesRefreshInterval = setInterval(() => {
                        const sourcesTab = document.getElementById('sources');
                        if (sourcesTab && sourcesTab.classList.contains('active')) {
                            loadExternalSources();
                        }
                    }, 5000);
                }
            } else {
                // Stop auto-refresh when leaving sources tab
                if (sourcesRefreshInterval) {
                    clearInterval(sourcesRefreshInterval);
                    sourcesRefreshInterval = null;
                }
            }
            
            // Load streams when Active Streams tab is opened and start auto-refresh
            if (tabName === 'streams' && typeof loadStreams === 'function') {
                loadStreams();
                // Start auto-refresh if not already running
                if (!streamsRefreshInterval) {
                    streamsRefreshInterval = setInterval(() => {
                        const streamsTab = document.getElementById('streams');
                        if (streamsTab && streamsTab.classList.contains('active')) {
                            loadStreams();
                        }
                    }, 5000);
                }
            }
            
            // Load recordings when Recordings tab is opened
            if (tabName === 'recordings') {
                loadRecordingSettings();
                loadDiskUsage();
                loadRecordings();
                
                // Auto-refresh recordings every 5 seconds to show recording progress
                if (!window.recordingsRefreshInterval) {
                    window.recordingsRefreshInterval = setInterval(() => {
                        const recordingsTab = document.getElementById('recordings');
                        if (recordingsTab && recordingsTab.classList.contains('active')) {
                            loadRecordings();
                            loadDiskUsage();
                        }
                    }, 5000);
                }
            } else {
                // Stop auto-refresh when leaving recordings tab
                if (window.recordingsRefreshInterval) {
                    clearInterval(window.recordingsRefreshInterval);
                    window.recordingsRefreshInterval = null;
                }
            }
        }
        
        function startLogStream() {
            const logContent = document.getElementById('logContent');
            logContent.innerHTML = '';
            
            logEventSource = new EventSource('/stream_logs');
            
            logEventSource.onmessage = function(event) {
                const logContainer = document.getElementById('logContainer');
                const logContent = document.getElementById('logContent');
                
                // Add new log line
                const logLine = document.createElement('div');
                logLine.textContent = event.data;
                logContent.appendChild(logLine);
                
                // Auto-scroll to bottom if enabled
                if (autoScroll) {
                    logContainer.scrollTop = logContainer.scrollHeight;
                }
                
                // Keep only last 500 lines
                const lines = logContent.children;
                if (lines.length > 500) {
                    logContent.removeChild(lines[0]);
                }
            };
            
            logEventSource.onerror = function(error) {
                console.error('Log stream error:', error);
                logContent.innerHTML += '<div style="color: #f44336;">Connection lost. Reconnecting...</div>';
                logEventSource.close();
                logEventSource = null;
                setTimeout(startLogStream, 3000);
            };
        }
        
        function clearLogs() {
            document.getElementById('logContent').innerHTML = '';
        }
        
        function restartLogs() {
            // Close existing connection
            if (logEventSource) {
                logEventSource.close();
                logEventSource = null;
            }
            // Clear and restart
            document.getElementById('logContent').innerHTML = 'Reconnecting to log stream...';
            startLogStream();
        }
        
        function toggleAutoScroll() {
            autoScroll = !autoScroll;
            const btn = document.getElementById('autoScrollBtn');
            btn.textContent = 'Auto-Scroll: ' + (autoScroll ? 'ON' : 'OFF');
            btn.className = autoScroll ? 'btn btn-primary' : 'btn btn-secondary';
        }
        
        // On page load, check for tab parameter and show that tab
        window.addEventListener('DOMContentLoaded', function() {
            const urlParams = new URLSearchParams(window.location.search);
            const tabParam = urlParams.get('tab');
            console.log("Tab parameter from URL:", tabParam);
            
            if (tabParam) {
                // Find the tab button for this tab
                const tabButtons = document.querySelectorAll('.tab');
                tabButtons.forEach(button => {
                    const onclick = button.getAttribute('onclick');
                    if (!onclick) return;
                    console.log("Checking button:", onclick);
                    const match = onclick.match(/showTab\('(.+?)'(?:,\s*event)?\)/);
                    if (!match) return;
                    const tabName = match[1];
                    console.log("Found matching tab:", tabName);
                    if (tabName === tabParam) {
                        // Hide all tabs first
                        const tabs = document.querySelectorAll('.tab');
                        const contents = document.querySelectorAll('.tab-content');
                        
                        tabs.forEach(tab => tab.classList.remove('active'));
                        contents.forEach(content => content.classList.remove('active'));
                        
                        // Show the requested tab
                        button.classList.add('active');
                        document.getElementById(tabParam).classList.add('active');
                        
                        // Update all tab trackers
                        console.log("ACTIVATED TAB:", tabParam);
                        document.querySelectorAll('.tab-tracker').forEach(tracker => {
                            tracker.value = tabParam;
                        });
            console.log("All active tab IDs:", Array.from(document.querySelectorAll('.tab-content.active')).map(t => t.id));
            console.log("Active tabs count:", document.querySelectorAll('.tab-content.active').length);
            console.log("Final active tab:", document.querySelector('.tab-content.active')?.id);
                        
                        // Start logs if needed
                        if (tabParam === 'logs' && !logEventSource) {
                            startLogStream();
                        }
                    }
                });
            }
        });
        
        // Status Badge Auto-Refresh
        function updateStatus() {
            fetch('/api/status')
                .then(response => response.json())
                .then(data => {
                    const badge = document.getElementById('status-badge');
                    const text = document.getElementById('status-text');
                    
                    if (data.status === 'running') {
                        text.textContent = '🟢 MediaMTX Running';
                        badge.style.background = 'rgba(76, 175, 80, 0.3)';
                    } else if (data.status === 'starting') {
                        text.textContent = '🟠 MediaMTX Starting';
                        badge.style.background = 'rgba(255, 152, 0, 0.3)';
                    } else {
                        text.textContent = '🔴 MediaMTX Stopped';
                        badge.style.background = 'rgba(244, 67, 54, 0.3)';
                    }
                })
                .catch(() => {
                    document.getElementById('status-text').textContent = '⚪ Status Unknown';
                });
        }
        
        function updateStreamCount() {
            fetch('/api/streams')
                .then(response => response.json())
                .then(data => {
                    const streamBadge = document.getElementById('stream-badge');
                    const streamCount = document.getElementById('stream-count');
                    const streamPlural = document.getElementById('stream-plural');
                    
                    if (data.streams && data.streams.length > 0) {
                        streamCount.textContent = data.streams.length;
                        streamPlural.textContent = data.streams.length === 1 ? '' : 's';
                        streamBadge.style.display = 'inline-block';
                        streamBadge.style.background = 'rgba(76, 175, 80, 0.3)';
                    } else {
                        streamBadge.style.display = 'none';
                    }
                })
                .catch(() => {
                    document.getElementById('stream-badge').style.display = 'none';
                });
        }
        
        // Load status and stream count on page load and refresh every 5 seconds
        updateStatus();
        updateStreamCount();
        setInterval(updateStatus, 5000);
        setInterval(updateStreamCount, 5000);
        
        // Active Streams Loading
        function loadStreams() {
            fetch('/api/streams')
                .then(response => response.json())
                .then(data => {
                    const container = document.getElementById('streams-container');
                    
                    if (data.streams && data.streams.length > 0) {
                        let html = '<table style="width: 100%; border-collapse: collapse; margin-top: 20px;">';
                        html += '<thead><tr style="background: #383838; border-bottom: 2px solid #4a4a4a;">';
                        html += '<th style="padding: 12px; text-align: left;">Group</th>';
                        html += '<th style="padding: 12px; text-align: left;">User</th>';
                        html += '<th style="padding: 12px; text-align: left;">Stream Name</th>';
                        html += '<th style="padding: 12px; text-align: center;">Viewers</th>';
                        html += '<th style="padding: 12px; text-align: center;">Actions</th>';
                        html += '</tr></thead><tbody>';
                        
                        data.streams.forEach(stream => {
                            html += '<tr style="border-bottom: 1px solid #4a4a4a;">';
                            
                            // Group column
                            let groupDisplay = stream.publisher_group || '<span style="color: #666;">-</span>';
                            html += `<td style="padding: 12px;"><span style="color: #4a9eff; font-weight: bold;">${groupDisplay}</span></td>`;
                            
                            // User column
                            let userDisplay = stream.publisher_username ? `@${stream.publisher_username}` : '<span style="color: #666;">-</span>';
                            html += `<td style="padding: 12px;"><span style="color: #999;">${userDisplay}</span></td>`;
                            
                            // Stream name column
                            html += `<td style="padding: 12px;"><strong>${stream.name}</strong></td>`;
                            
                            // Show viewer count with breakdown
                            let viewerDisplay = `<strong style="color: #4caf50;">${stream.readers}</strong>`;
                            if (stream.reader_breakdown && Object.keys(stream.reader_breakdown).length > 0) {
                                viewerDisplay += `<div style="font-size: 11px; color: #999; margin-top: 4px;">`;
                                const breakdown = Object.entries(stream.reader_breakdown)
                                    .map(([type, count]) => `${type}: ${count}`)
                                    .join(' | ');
                                viewerDisplay += breakdown;
                                viewerDisplay += `</div>`;
                            }
                            html += `<td style="padding: 12px; text-align: center;">${viewerDisplay}</td>`;
                            html += `<td style="padding: 12px; text-align: center;">`;
                            html += `<button class="watch-stream-btn" data-url="${stream.hls_url}" data-name="${escapeHtml(stream.name)}" style="padding: 8px 16px; font-size: 14px; display: inline-flex; align-items: center; gap: 6px; background: #4CAF50; color: white; border: none; border-radius: 4px; cursor: pointer;">`;
                            html += `<span style="font-size: 16px;">▶️</span> Watch</button>`;
                            html += `</td>`;
                            html += '</tr>';
                        });
                        
                        html += '</tbody></table>';
                        container.innerHTML = html;
                        
                        // Add click handlers for all Watch buttons
                        document.querySelectorAll('.watch-stream-btn').forEach(btn => {
                            btn.addEventListener('click', function() {
                                watchStream(this.getAttribute('data-url'));
                            });
                        });
                    } else {
                        container.innerHTML = '<p style="color: #999; margin-top: 20px;">No active streams. Publish a stream via RTSP, SRT, or RTMP to see it here.</p>';
                    }
                })
                .catch(err => {
                    document.getElementById('streams-container').innerHTML = '<p style="color: #f44336;">Error loading streams: ' + err.message + '</p>';
                });
        }
        
        // View stream in popup
        function viewStream(url, name) {
            const popup = window.open('', 'Stream: ' + name, 'width=800,height=600');
            popup.document.write(`
                <!DOCTYPE html>
                <html>
                <head>
                    <title>Stream: ${name}</title>
                    <script src="https://cdn.jsdelivr.net/npm/hls.js@latest"><\/script>
                </head>
                <body style="margin: 0; background: #000;">
                    <video id="video" controls style="width: 100%; height: 100%;"></video>
                    <script>
                        const video = document.getElementById('video');
                        const url = '${url}';
                        
                        if (Hls.isSupported()) {
                            const hls = new Hls();
                            hls.loadSource(url);
                            hls.attachMedia(video);
                        } else if (video.canPlayType('application/vnd.apple.mpegurl')) {
                            video.src = url;
                        }
                    <\/script>
                </body>
                </html>
            `);
        }
        
        // Active Streams auto-refresh
        let streamsRefreshInterval = null;
        
        // Load streams when streams tab is shown
        document.addEventListener('DOMContentLoaded', () => {
            const streamsTab = document.getElementById('streams');
            if (streamsTab && streamsTab.classList.contains('active')) {
                loadStreams();
                // Start auto-refresh
                if (!streamsRefreshInterval) {
                    streamsRefreshInterval = setInterval(() => {
                        const streamsTab = document.getElementById('streams');
                        if (streamsTab && streamsTab.classList.contains('active')) {
                            loadStreams();
                        }
                    }, 5000); // Refresh every 5 seconds
                }
            }
        });
        
        // Web Users Management
        function showAddUserForm() {
            document.getElementById('add-user-form').style.display = 'block';
        }
        
        function hideAddUserForm() {
            document.getElementById('add-user-form').style.display = 'none';
            document.getElementById('new-username').value = '';
            document.getElementById('new-password').value = '';
        }
        
        function addUser() {
            const username = document.getElementById('new-username').value.trim();
            const password = document.getElementById('new-password').value;
            const role = document.getElementById('new-role').value;
            
            if (!username || !password) {
                alert('Username and password required');
                return;
            }
            
            if (password.length < 4) {
                alert('Password must be at least 4 characters');
                return;
            }
            
            fetch('/api/webeditor/users/add', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({username, password, role})
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    hideAddUserForm();
                    loadWebUsers();
                    alert('User added successfully');
                } else {
                    alert('Error: ' + data.error);
                }
            });
        }
        
        function deleteUser(username) {
            if (!confirm('Delete user: ' + username + '?')) return;
            
            fetch('/api/webeditor/users/delete', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({username})
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    loadWebUsers();
                    alert('User deleted');
                } else {
                    alert('Error: ' + data.error);
                }
            });
        }
        
        function loadWebUsers() {
            fetch('/api/webeditor/users')
                .then(response => response.json())
                .then(data => {
                    const container = document.getElementById('users-list-container');
                    let html = '<table style="width: 100%; border-collapse: collapse; margin-top: 20px;">';
                    html += '<thead><tr style="background: #383838; border-bottom: 2px solid #4a4a4a;">';
                    html += '<th style="padding: 12px; text-align: left;">Username</th>';
                    html += '<th style="padding: 12px; text-align: left;">Role</th>';
                    html += '<th style="padding: 12px; text-align: left;">Actions</th>';
                    html += '</tr></thead><tbody>';
                    
                    data.users.forEach(user => {
                        html += '<tr style="border-bottom: 1px solid #4a4a4a;">';
                        html += `<td style="padding: 12px;">${user.username}</td>`;
                        html += `<td style="padding: 12px;">${user.role}</td>`;
                        html += `<td style="padding: 12px;">`;
                        if (user.username !== '{{ username }}') {
                            html += `<button class="btn btn-danger" style="padding: 6px 12px; font-size: 14px;" onclick="deleteUser('${user.username}')">Delete</button>`;
                        } else {
                            html += '<span style="color: #999;">(current user)</span>';
                        }
                        html += '</td></tr>';
                    });
                    
                    html += '</tbody></table>';
                    container.innerHTML = html;
                });
        }
        
        // Load users if on webusers tab
        if (document.getElementById('webusers')) {
            loadWebUsers();
        }
        
        // MediaMTX Users Management
        function showAddMediaMTXUserForm() {
            document.getElementById('add-mediamtx-user-form').style.display = 'block';
            
            // Reset form fields to editable state (in case we were just editing hlsviewer)
            const usernameField = document.getElementById('mtx-username');
            const groupNameField = document.getElementById('mtx-group-name');
            const readCheckbox = document.getElementById('mtx-perm-read');
            const publishCheckbox = document.getElementById('mtx-perm-publish');
            const playbackCheckbox = document.getElementById('mtx-perm-playback');
            
            usernameField.readOnly = false;
            usernameField.style.opacity = '1';
            usernameField.style.cursor = 'text';
            
            groupNameField.readOnly = false;
            groupNameField.style.opacity = '1';
            groupNameField.style.cursor = 'text';
            
            readCheckbox.disabled = false;
            publishCheckbox.disabled = false;
            playbackCheckbox.disabled = false;
            
            // Set default checked states
            readCheckbox.checked = true;
            publishCheckbox.checked = true;
            playbackCheckbox.checked = true;
        }
        
        function hideAddMediaMTXUserForm() {
            document.getElementById('add-mediamtx-user-form').style.display = 'none';
            document.getElementById('mtx-group-name').value = '';
            document.getElementById('mtx-username').value = '';
            document.getElementById('mtx-password').value = '';
            
            // Reset readonly/disabled states (in case we were editing hlsviewer)
            const usernameField = document.getElementById('mtx-username');
            const groupNameField = document.getElementById('mtx-group-name');
            const readCheckbox = document.getElementById('mtx-perm-read');
            const publishCheckbox = document.getElementById('mtx-perm-publish');
            const playbackCheckbox = document.getElementById('mtx-perm-playback');
            
            usernameField.readOnly = false;
            usernameField.style.opacity = '1';
            usernameField.style.cursor = 'text';
            
            groupNameField.readOnly = false;
            groupNameField.style.opacity = '1';
            groupNameField.style.cursor = 'text';
            
            readCheckbox.disabled = false;
            publishCheckbox.disabled = false;
            playbackCheckbox.disabled = false;
            
            // Clear editing flags
            const form = document.getElementById('mediamtx-user-form');
            if (form) {
                if (form.dataset.editing) delete form.dataset.editing;
                if (form.dataset.editingIps) delete form.dataset.editingIps;
                
                // Reset button text back to "Create User"
                const submitButton = form.querySelector('button[type="submit"]');
                if (submitButton) {
                    submitButton.textContent = 'Create User';
                }
            }
        }
        
        document.getElementById('mediamtx-user-form')?.addEventListener('submit', function(e) {
            e.preventDefault();
            
            const groupName = document.getElementById('mtx-group-name').value.trim();
            const username = document.getElementById('mtx-username').value.trim();
            const password = document.getElementById('mtx-password').value.trim();
            const form = e.target;
            const editingUsername = form.dataset.editing;
            const editingIps = form.dataset.editingIps ? JSON.parse(form.dataset.editingIps) : [];
            
            const permissions = [];
            if (document.getElementById('mtx-perm-read').checked) permissions.push('read');
            if (document.getElementById('mtx-perm-publish').checked) permissions.push('publish');
            if (document.getElementById('mtx-perm-playback').checked) permissions.push('playback');
            
            if (!groupName || !username) {
                alert('Please fill in group name and username');
                return;
            }
            
            // TEMPORARILY DISABLED - Allow blank passwords for testing
            // Password can be blank only for "any" user
            // if (!password && username !== 'any') {
            //     alert('Password is required (except for username "any")');
            //     return;
            // }
                        
            if (permissions.length === 0) {
                alert('Please select at least one permission');
                return;
            }
            
            // Validate MediaMTX allowed characters (no spaces, commas, apostrophes, slashes)
            const allowedChars = /^[A-Za-z0-9!$()*.+;<=>\[\]^_\-"@#&]+$/;
            
            if (!allowedChars.test(username)) {
                alert('Username contains invalid characters!\\n\\nAllowed: A-Z, 0-9, !$()*.@#& etc.\\nNOT allowed: spaces, commas, apostrophes, slashes');
                return;
            }
            
            if (password && !allowedChars.test(password)) {
                alert('Password contains invalid characters!\\n\\nAllowed: A-Z, 0-9, !$()*.@#& etc.\\nNOT allowed: spaces, commas, apostrophes, slashes');
                return;
            }
            
            // If editing, use UPDATE endpoint
            if (editingUsername) {
                fetch('/api/mediamtx/users/update', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({
                        oldUsername: editingUsername,
                        oldIps: editingIps,
                        groupName,
                        username,
                        password,
                        permissions
                    })
                })
                .then(response => response.json())
                .then(data => {
                    if (data.success) {
                        delete form.dataset.editing;
                        delete form.dataset.editingIps;
                        hideAddMediaMTXUserForm();
                        loadMediaMTXUsers();
                        reloadYAMLContent();
                        alert('User updated successfully! MediaMTX will restart.');
                    } else {
                        alert('Error updating user: ' + data.error);
                    }
                });
            } else {
                // Adding new user
                fetch('/api/mediamtx/users/add', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({groupName, username, password, permissions})
                })
                .then(response => response.json())
                .then(data => {
                    if (data.success) {
                        hideAddMediaMTXUserForm();
                        loadMediaMTXUsers();
                        reloadYAMLContent();
                        alert('User added successfully! MediaMTX will restart.');
                    } else {
                        alert('Error adding user: ' + data.error);
                    }
                });
            }
        });
        

        function reloadYAMLContent() {
            // Fetch fresh YAML content
            fetch('/api/yaml/content')
                .then(response => response.text())
                .then(yamlText => {
                    const textarea = document.querySelector('textarea[name="yaml_content"]');
                    if (textarea) {
                        textarea.value = yamlText;
                    }
                })
                .catch(err => console.error('Failed to reload YAML:', err));
        }
        
        // === EXTERNAL SOURCES ===
        let sourcesRefreshInterval = null;
        
        function showAddSourceForm() {
            document.getElementById('add-source-form').style.display = 'block';
            editingSourceName = null;
            const nameField = document.getElementById('source-name');
            nameField.value = '';
            nameField.readOnly = false;
            nameField.style.opacity = '1';
            // SRT fields
            document.getElementById('source-srt-host').value = '';
            document.getElementById('source-srt-port').value = '8890';
            document.getElementById('source-srt-mode').value = 'caller';
            document.getElementById('source-srt-streamid').value = '';
            document.getElementById('source-srt-passphrase').value = '';
            // RTSP fields
            document.getElementById('source-rtsp-secure').value = 'rtsp';
            document.getElementById('source-rtsp-host').value = '';
            document.getElementById('source-rtsp-port').value = '554';
            document.getElementById('source-rtsp-path').value = '';
            document.getElementById('source-rtsp-user').value = '';
            document.getElementById('source-rtsp-pass').value = '';
            // UDP fields
            document.getElementById('source-udp-port').value = '5004';
            document.getElementById('source-udp-filter').value = '';
            // RTMP fields
            document.getElementById('source-rtmp-secure').value = 'rtmp';
            document.getElementById('source-rtmp-host').value = '';
            document.getElementById('source-rtmp-port').value = '1935';
            document.getElementById('source-rtmp-path').value = '';
            // HLS fields
            document.getElementById('source-hls-url').value = '';
            
            document.getElementById('source-protocol').value = 'srt';
            const submitBtn = document.querySelector('#external-source-form button[type="submit"]');
            if (submitBtn) submitBtn.textContent = 'Add Source';
            updateSourceFormFields();
        }
        
        function hideAddSourceForm() {
            document.getElementById('add-source-form').style.display = 'none';
        }
        
        function updateSourceFormFields() {
            const protocol = document.getElementById('source-protocol').value;
            document.getElementById('srt-source-fields').style.display = protocol === 'srt' ? 'block' : 'none';
            document.getElementById('rtsp-source-fields').style.display = protocol === 'rtsp' ? 'block' : 'none';
            document.getElementById('udp-source-fields').style.display = protocol === 'udp' ? 'block' : 'none';
            document.getElementById('rtmp-source-fields').style.display = protocol === 'rtmp' ? 'block' : 'none';
            document.getElementById('hls-source-fields').style.display = protocol === 'hls' ? 'block' : 'none';
        }
        
        document.getElementById('external-source-form')?.addEventListener('submit', function(e) {
            e.preventDefault();
            
            const name = document.getElementById('source-name').value.trim();
            const protocol = document.getElementById('source-protocol').value;
            const alwaysOn = true;  // Always connected by default
            
            if (!name) {
                alert('Stream name is required');
                return;
            }
            
            // Validate name: lowercase, numbers, underscores only
            if (!/^[a-z0-9_]+$/.test(name)) {
                alert('Stream name must be lowercase letters, numbers, and underscores only');
                return;
            }
            
            let sourceUrl = '';
            
            if (protocol === 'srt') {
                const host = document.getElementById('source-srt-host').value.trim();
                const port = document.getElementById('source-srt-port').value.trim() || '8890';
                const srtMode = document.getElementById('source-srt-mode').value;
                const streamId = document.getElementById('source-srt-streamid').value.trim();
                const passphrase = document.getElementById('source-srt-passphrase').value.trim();
                
                if (!host) {
                    alert('SRT server address is required');
                    return;
                }
                
                sourceUrl = 'srt://' + host + ':' + port;
                let params = [];
                if (streamId) {
                    params.push('streamid=read:' + streamId);
                }
                if (passphrase) {
                    if (passphrase.length < 10 || passphrase.length > 79) {
                        alert('SRT passphrase must be 10-79 characters');
                        return;
                    }
                    params.push('passphrase=' + passphrase);
                }
                params.push('mode=' + srtMode);
                sourceUrl += '?' + params.join('&');
            } else if (protocol === 'rtsp') {
                const scheme = document.getElementById('source-rtsp-secure').value;
                const host = document.getElementById('source-rtsp-host').value.trim();
                const port = document.getElementById('source-rtsp-port').value.trim() || '554';
                const path = document.getElementById('source-rtsp-path').value.trim();
                const user = document.getElementById('source-rtsp-user').value.trim();
                const pass = document.getElementById('source-rtsp-pass').value.trim();
                
                if (!host) {
                    alert('RTSP host is required');
                    return;
                }
                if (!path) {
                    alert('RTSP path is required');
                    return;
                }
                
                if (user && pass) {
                    sourceUrl = scheme + '://' + user + ':' + pass + '@' + host + ':' + port + '/' + path;
                } else {
                    sourceUrl = scheme + '://' + host + ':' + port + '/' + path;
                }
            } else if (protocol === 'udp') {
                const port = document.getElementById('source-udp-port').value.trim() || '5004';
                const sourceFilter = document.getElementById('source-udp-filter').value.trim();
                
                sourceUrl = 'udp+mpegts://0.0.0.0:' + port;
                if (sourceFilter) {
                    sourceUrl += '?source=' + sourceFilter;
                }
            } else if (protocol === 'rtmp') {
                const scheme = document.getElementById('source-rtmp-secure').value;
                const host = document.getElementById('source-rtmp-host').value.trim();
                const port = document.getElementById('source-rtmp-port').value.trim() || '1935';
                const path = document.getElementById('source-rtmp-path').value.trim();
                
                if (!host) {
                    alert('RTMP host is required');
                    return;
                }
                if (!path) {
                    alert('RTMP path / stream key is required');
                    return;
                }
                
                sourceUrl = scheme + '://' + host + ':' + port + '/' + path;
            } else if (protocol === 'hls') {
                sourceUrl = document.getElementById('source-hls-url').value.trim();
                if (!sourceUrl) {
                    alert('HLS URL is required');
                    return;
                }
                if (!sourceUrl.startsWith('http://') && !sourceUrl.startsWith('https://')) {
                    alert('URL must start with http:// or https://');
                    return;
                }
            }
            
            const endpoint = editingSourceName ? '/api/external-sources/edit' : '/api/external-sources/add';
            const successMsg = editingSourceName ? 'External source updated! MediaMTX will restart.' : 'External source added! MediaMTX will restart.';
            
            fetch(endpoint, {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    name: name,
                    sourceUrl: sourceUrl,
                    onDemand: !alwaysOn
                })
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    hideAddSourceForm();
                    loadExternalSources();
                    reloadYAMLContent();
                    alert(successMsg);
                } else {
                    alert('Error: ' + data.error);
                }
            })
            .catch(err => alert('Error: ' + err.message));
        });
        
        function loadExternalSources() {
            fetch('/api/external-sources')
                .then(response => response.json())
                .then(data => {
                    const container = document.getElementById('external-sources-list');
                    
                    if (!data.sources || data.sources.length === 0) {
                        container.innerHTML = '<p style="color: #999; margin-top: 10px;">No external sources configured. Click "+ Add External Source" to pull a stream from another agency\\'s server.</p>';
                        return;
                    }
                    
                    let html = '<table style="width: 100%; border-collapse: collapse; margin-top: 10px;">';
                    html += '<thead><tr style="background: #383838; border-bottom: 2px solid #4a4a4a;">';
                    html += '<th style="padding: 12px; text-align: left;">Name</th>';
                    html += '<th style="padding: 12px; text-align: left;">Source URL</th>';
                    html += '<th style="padding: 12px; text-align: center;">Mode</th>';
                    html += '<th style="padding: 12px; text-align: center;">Status</th>';
                    html += '<th style="padding: 12px; text-align: center;">Actions</th>';
                    html += '</tr></thead><tbody>';
                    
                    data.sources.forEach(source => {
                        html += '<tr style="border-bottom: 1px solid #4a4a4a;">';
                        html += '<td style="padding: 12px;"><strong>' + escapeHtml(source.name) + '</strong></td>';
                        
                        // Mask passphrase in URL display
                        let displayUrl = source.source_url || '';
                        displayUrl = displayUrl.replace(/passphrase=[^&]+/, 'passphrase=****');
                        html += '<td style="padding: 12px; font-family: monospace; font-size: 13px; word-break: break-all;">' + escapeHtml(displayUrl) + '</td>';
                        
                        // Mode - clickable Caller/Listener for SRT, text for others
                        if (source.source_url && source.source_url.startsWith('srt://')) {
                            if (source.source_url.includes('mode=listener')) {
                                html += '<td style="padding: 12px; text-align: center;"><button data-toggle-btn onclick="switchSrtMode(\\'' + escapeHtml(source.name) + '\\')" style="background: #2196F3; color: white; border: none; border-radius: 4px; padding: 8px 18px; cursor: pointer; font-size: 14px; font-weight: bold;" title="Click to switch to Caller mode">Listener</button></td>';
                            } else {
                                html += '<td style="padding: 12px; text-align: center;"><button data-toggle-btn onclick="switchSrtMode(\\'' + escapeHtml(source.name) + '\\')" style="background: #9c27b0; color: white; border: none; border-radius: 4px; padding: 8px 18px; cursor: pointer; font-size: 14px; font-weight: bold;" title="Click to switch to Listener mode">Caller</button></td>';
                            }
                        } else {
                            let modeText = source.on_demand ? 'On-Demand' : 'Always On';
                            let modeColor = source.on_demand ? '#ff9800' : '#4caf50';
                            html += '<td style="padding: 12px; text-align: center;"><span style="color: ' + modeColor + '; font-weight: bold;">' + modeText + '</span></td>';
                        }
                        
                        // Status
                        let statusText = 'Unknown';
                        let statusColor = '#999';
                        if (source.status === 'disabled') {
                            statusText = '⏸️ Disabled';
                            statusColor = '#999';
                        } else if (source.status === 'ready') {
                            statusText = '🟢 Connected';
                            statusColor = '#4caf50';
                        } else if (source.status === 'not_ready') {
                            statusText = '🔴 Disconnected';
                            statusColor = '#f44336';
                        } else if (source.status === 'waiting') {
                            statusText = '🟡 Waiting';
                            statusColor = '#ff9800';
                        }
                        html += '<td style="padding: 12px; text-align: center;"><span style="color: ' + statusColor + '; font-weight: bold;">' + statusText + '</span></td>';
                        
                        // Actions - Enable/Disable toggle + Edit + Delete
                        html += '<td style="padding: 12px; text-align: center;">';
                        if (source.enabled !== false) {
                            html += '<button class="btn" data-toggle-btn onclick="toggleExternalSource(\\'' + escapeHtml(source.name) + '\\')" style="padding: 6px 14px; font-size: 13px; background: #ff9800; color: white; border: none; border-radius: 4px; cursor: pointer; margin-right: 6px;">Disable</button>';
                        } else {
                            html += '<button class="btn" data-toggle-btn onclick="toggleExternalSource(\\'' + escapeHtml(source.name) + '\\')" style="padding: 6px 14px; font-size: 13px; background: #4caf50; color: white; border: none; border-radius: 4px; cursor: pointer; margin-right: 6px;">Enable</button>';
                        }
                        html += '<button class="btn" onclick="editExternalSource(\\'' + escapeHtml(source.name) + '\\')" style="padding: 6px 14px; font-size: 13px; background: #2196F3; color: white; border: none; border-radius: 4px; cursor: pointer; margin-right: 6px;">Edit</button>';
                        html += '<button class="btn btn-danger" onclick="deleteExternalSource(\\'' + escapeHtml(source.name) + '\\')" style="padding: 6px 14px; font-size: 13px;">Delete</button>';
                        html += '</td>';
                        html += '</tr>';
                    });
                    
                    html += '</tbody></table>';
                    container.innerHTML = html;
                })
                .catch(err => {
                    document.getElementById('external-sources-list').innerHTML = '<p style="color: #f44336;">Error loading sources: ' + err.message + '</p>';
                });
        }
        
        function deleteExternalSource(name) {
            if (!confirm('Delete external source "' + name + '"? This will remove the path from MediaMTX.')) return;
            
            fetch('/api/external-sources/delete', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({name: name})
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    loadExternalSources();
                    reloadYAMLContent();
                    alert('External source deleted! MediaMTX will restart.');
                } else {
                    alert('Error: ' + data.error);
                }
            })
            .catch(err => alert('Error deleting source: ' + err.message));
        }
        
        function toggleExternalSource(name) {
            // Disable all toggle buttons to prevent rapid-fire
            document.querySelectorAll('[data-toggle-btn]').forEach(btn => {
                btn.disabled = true;
                btn.style.opacity = '0.5';
            });
            
            fetch('/api/external-sources/toggle', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({name: name})
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    loadExternalSources();
                    reloadYAMLContent();
                } else {
                    alert('Error: ' + data.error);
                    loadExternalSources();
                }
            })
            .catch(err => {
                alert('Error toggling source: ' + err.message);
                loadExternalSources();
            });
        }
        
        function switchSrtMode(name) {
            // Disable all toggle buttons to prevent rapid-fire
            document.querySelectorAll('[data-toggle-btn]').forEach(btn => {
                btn.disabled = true;
                btn.style.opacity = '0.5';
            });
            
            fetch('/api/external-sources/switch-mode', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({name: name})
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    loadExternalSources();
                    reloadYAMLContent();
                } else {
                    alert('Error: ' + data.error);
                    loadExternalSources();
                }
            })
            .catch(err => {
                alert('Error switching mode: ' + err.message);
                loadExternalSources();
            });
        }
        
        var editingSourceName = null;
        
        function editExternalSource(name) {
            // Fetch current source data
            fetch('/api/external-sources')
                .then(response => response.json())
                .then(data => {
                    const source = data.sources.find(s => s.name === name);
                    if (!source) {
                        alert('Source not found');
                        return;
                    }
                    
                    showAddSourceForm();
                    editingSourceName = name;
                    
                    // Lock the name field
                    const nameField = document.getElementById('source-name');
                    nameField.value = name;
                    nameField.readOnly = true;
                    nameField.style.opacity = '0.6';
                    
                    // Change button text
                    const submitBtn = document.querySelector('#external-source-form button[type="submit"]');
                    if (submitBtn) submitBtn.textContent = 'Save Changes';
                    
                    const url = source.source_url || '';
                    
                    // Detect protocol and fill fields
                    if (url.startsWith('srt://')) {
                        document.getElementById('source-protocol').value = 'srt';
                        updateSourceFormFields();
                        // Parse srt://host:port?params
                        const srtMatch = url.match(/srt:\\/\\/([^:]+):(\\d+)/);
                        if (srtMatch) {
                            document.getElementById('source-srt-host').value = srtMatch[1];
                            document.getElementById('source-srt-port').value = srtMatch[2];
                        }
                        // Parse mode
                        const modeMatch = url.match(/mode=(caller|listener)/);
                        if (modeMatch) {
                            document.getElementById('source-srt-mode').value = modeMatch[1];
                        }
                        // Parse streamid
                        const sidMatch = url.match(/streamid=read:([^&]+)/);
                        if (sidMatch) {
                            document.getElementById('source-srt-streamid').value = sidMatch[1];
                        }
                        // Parse passphrase
                        const ppMatch = url.match(/passphrase=([^&]+)/);
                        if (ppMatch) {
                            document.getElementById('source-srt-passphrase').value = ppMatch[1];
                        }
                    } else if (url.startsWith('rtsp://') || url.startsWith('rtsps://')) {
                        document.getElementById('source-protocol').value = 'rtsp';
                        updateSourceFormFields();
                        const secure = url.startsWith('rtsps://') ? 'rtsps' : 'rtsp';
                        document.getElementById('source-rtsp-secure').value = secure;
                        // Parse rtsp://user:pass@host:port/path or rtsp://host:port/path
                        const rtspMatch = url.match(/rtsps?:\\/\\/(?:([^:]+):([^@]+)@)?([^:\\/]+):?(\\d+)?\\/?(.*)/)
                        if (rtspMatch) {
                            if (rtspMatch[1]) document.getElementById('source-rtsp-user').value = rtspMatch[1];
                            if (rtspMatch[2]) document.getElementById('source-rtsp-pass').value = rtspMatch[2];
                            document.getElementById('source-rtsp-host').value = rtspMatch[3] || '';
                            document.getElementById('source-rtsp-port').value = rtspMatch[4] || '554';
                            document.getElementById('source-rtsp-path').value = rtspMatch[5] || '';
                        }
                    } else if (url.startsWith('udp+mpegts://')) {
                        document.getElementById('source-protocol').value = 'udp';
                        updateSourceFormFields();
                        const udpMatch = url.match(/udp\\+mpegts:\\/\\/([^:]+):(\\d+)/);
                        if (udpMatch) {
                            document.getElementById('source-udp-port').value = udpMatch[2];
                        }
                        const srcMatch = url.match(/source=([^&]+)/);
                        if (srcMatch) {
                            document.getElementById('source-udp-filter').value = srcMatch[1];
                        }
                    } else if (url.startsWith('rtmp://') || url.startsWith('rtmps://')) {
                        document.getElementById('source-protocol').value = 'rtmp';
                        updateSourceFormFields();
                        const rtmpSecure = url.startsWith('rtmps://') ? 'rtmps' : 'rtmp';
                        document.getElementById('source-rtmp-secure').value = rtmpSecure;
                        const rtmpMatch = url.match(/rtmps?:\\/\\/([^:\\/]+):?(\\d+)?\\/?(.*)/)
                        if (rtmpMatch) {
                            document.getElementById('source-rtmp-host').value = rtmpMatch[1] || '';
                            document.getElementById('source-rtmp-port').value = rtmpMatch[2] || '1935';
                            document.getElementById('source-rtmp-path').value = rtmpMatch[3] || '';
                        }
                    } else if (url.startsWith('http://') || url.startsWith('https://')) {
                        document.getElementById('source-protocol').value = 'hls';
                        updateSourceFormFields();
                        document.getElementById('source-hls-url').value = url;
                    }
                })
                .catch(err => alert('Error loading source: ' + err.message));
        }
        // === END EXTERNAL SOURCES ===

        function editMediaMTXUser(username, password, groupName, permissions, ips) {
            // Show the add form
            document.getElementById('add-mediamtx-user-form').style.display = 'block';
            
            // Pre-fill with existing values
            const groupNameField = document.getElementById('mtx-group-name');
            groupNameField.value = groupName || '';
            
            const usernameField = document.getElementById('mtx-username');
            usernameField.value = username;
            
            // Lock username and group name fields for hlsviewer (system user)
            const isHLSViewer = username === 'hlsviewer';
            if (isHLSViewer) {
                usernameField.readOnly = true;
                usernameField.style.opacity = '0.6';
                usernameField.style.cursor = 'not-allowed';
                
                groupNameField.readOnly = true;
                groupNameField.style.opacity = '0.6';
                groupNameField.style.cursor = 'not-allowed';
            } else {
                usernameField.readOnly = false;
                usernameField.style.opacity = '1';
                usernameField.style.cursor = 'text';
                
                groupNameField.readOnly = false;
                groupNameField.style.opacity = '1';
                groupNameField.style.cursor = 'text';
            }
            
            document.getElementById('mtx-password').value = password || '';
            
            // Set permissions
            const readCheckbox = document.getElementById('mtx-perm-read');
            const publishCheckbox = document.getElementById('mtx-perm-publish');
            const playbackCheckbox = document.getElementById('mtx-perm-playback');
            
            readCheckbox.checked = permissions.includes('read');
            publishCheckbox.checked = permissions.includes('publish');
            playbackCheckbox.checked = permissions.includes('playback');
            
            // For hlsviewer, lock permissions (read only, can't change)
            if (isHLSViewer) {
                readCheckbox.disabled = true;
                readCheckbox.checked = true; // Always read
                publishCheckbox.disabled = true;
                publishCheckbox.checked = false; // Never publish
                playbackCheckbox.disabled = true;
                playbackCheckbox.checked = false; // Never playback
            } else {
                readCheckbox.disabled = false;
                publishCheckbox.disabled = false;
                playbackCheckbox.disabled = false;
            }
            
            // Add flags to know we're editing
            const form = document.getElementById('mediamtx-user-form');
            form.dataset.editing = username;
            form.dataset.editingIps = JSON.stringify(ips || []);
            
            // Change button text to "Update User"
            const submitButton = form.querySelector('button[type="submit"]');
            if (submitButton) {
                submitButton.textContent = 'Update User';
            }
            
            // Scroll to form
            document.getElementById('add-mediamtx-user-form').scrollIntoView({behavior: 'smooth'});
        }
        
        function revokeMediaMTXUser(username, ips) {
            if (!confirm('Revoke access for user: ' + username + '?')) return;
            
            fetch('/api/mediamtx/users/revoke', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({username, ips})
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    loadMediaMTXUsers();
                    reloadYAMLContent();
                    alert('User revoked! MediaMTX will restart.');
                } else {
                    alert('Error: ' + data.error);
                }
            });
        }
        
        function loadMediaMTXUsers(retryCount) {
            retryCount = retryCount || 0;
            fetch('/api/mediamtx/users')
                .then(response => response.json())
                .then(data => {
                    const container = document.getElementById('mediamtx-users-list');
                    
                    if ((!data.users || data.users.length === 0) && retryCount < 3) {
                        // Might be loading after restart - retry
                        setTimeout(function() { loadMediaMTXUsers(retryCount + 1); }, 2000);
                        return;
                    }
                    
                    if (!data.users || data.users.length === 0) {
                        container.innerHTML = '<p style="color: #999;">No users configured. Click "Add Authorized User" to create one.</p>';
                        return;
                    }
                    
                    // Sort users: PUBLIC first, HLS PLAYER second, then others
                    data.users.sort((a, b) => {
                        const aIsPublic = a.groupName && a.groupName.toLowerCase() === 'public';
                        const bIsPublic = b.groupName && b.groupName.toLowerCase() === 'public';
                        const aIsHLS = a.user === 'hlsviewer';
                        const bIsHLS = b.user === 'hlsviewer';
                        
                        // PUBLIC always first
                        if (aIsPublic && !bIsPublic) return -1;
                        if (!aIsPublic && bIsPublic) return 1;
                        
                        // HLS PLAYER second (after PUBLIC if it exists)
                        if (aIsHLS && !bIsHLS) return -1;
                        if (!aIsHLS && bIsHLS) return 1;
                        
                        return 0;  // Keep original order for others
                    });
                    
                    let html = '';
                    
                    data.users.forEach(user => {
                        // Check if this is unprotected (any user with no password)
                        const isUnprotected = user.user === 'any' && (!user.pass || user.pass === '');
                        const borderColor = isUnprotected ? '#ff9800' : '#2196F3';
                        
                        html += '<div style="background: #2d2d2d; padding: 20px; border-radius: 8px; margin-bottom: 15px; border-left: 4px solid ' + borderColor + ';">';
                        
                        // Warning for unprotected
                        if (isUnprotected) {
                            html += '<div class="alert alert-warning" style="margin-bottom: 15px;">';
                            html += '<strong>⚠️ Warning: No Authentication Enabled!</strong><br>';
                            html += 'Your server is open to the public and UNPROTECTED. Anyone can publish, read, or playback streams. You can change permissions by clicking "Edit" below or disable public access using the toggle at the top of this page.';
                            html += '</div>';
                        }
                        
                        html += '<div style="display: flex; justify-content: space-between; align-items: center;">';
                        html += '<div>';
                        
                        // Show group name if available
                        if (user.groupName) {
                            html += '<h4 style="margin: 0;">' + user.groupName + '</h4>';
                        } else {
                            html += '<h4 style="margin: 0; color: #999;">Unnamed Group</h4>';
                        }
                        
                        html += '<p style="margin: 5px 0;"><strong>Username:</strong> ' + user.user;
                        if (user.user === 'any') {
                            html += ' <span style="color: #ff9800;">(no auth)</span>';
                        }
                        html += '</p>';
                        
                        if (user.pass) {
                            html += '<p style="margin: 5px 0;"><strong>Password:</strong> ' + user.pass + '</p>';
                        } else {
                            html += '<p style="margin: 5px 0; color: #ff9800;"><strong>Password:</strong> (none)</p>';
                        }
                        
                        html += '<p style="margin: 5px 0;"><strong>Permissions:</strong> ';
                        const perms = user.permissions.map(p => p.action).join(', ');
                        html += perms || 'None';
                        html += '</p>';
                        html += '</div>';
                        
                        html += '<div style="display: flex; gap: 10px;">';
                        const permsJson = JSON.stringify(user.permissions.map(p => p.action)).replace(/"/g, '&quot;');
                        const ipsJson = JSON.stringify(user.ips || []).replace(/"/g, '&quot;');
                        html += '<button class="btn btn-secondary" onclick="editMediaMTXUser(\\'' + user.user + '\\', \\'' + (user.pass || '') + '\\', \\'' + (user.groupName || '') + '\\', ' + permsJson + ', ' + ipsJson + ')">✏️ Edit</button>';
                        
                        // Hide Revoke button for PUBLIC user (controlled by toggle)
                        const isPublicUser = user.user === 'any' && (!user.pass || user.pass === '') && user.groupName === 'PUBLIC';
                        // Hide Revoke button for hlsviewer (system user)
                        const isHLSViewer = user.user === 'hlsviewer';
                        
                        if (!isPublicUser && !isHLSViewer) {
                            html += '<button class="btn btn-danger" onclick="revokeMediaMTXUser(\\'' + user.user + '\\', ' + ipsJson + ')">🗑️ Revoke</button>';
                        } else if (isHLSViewer) {
                            html += '<span style="color: #ff9800; font-size: 13px; margin-left: 10px;">⚠️ System User - Auto-generated for HLS playback (password edit only)</span>';
                        }
                        
                        html += '</div>';
                        
                        html += '</div></div>';
                    });
                    
                    container.innerHTML = html;
                    
                    // Also populate the group dropdown with unique groups
                    populateGroupDropdown(data.users);
                });
        }
        
        function populateGroupDropdown(users) {
            const datalist = document.getElementById('existing-groups');
            if (!datalist) return;
            
            // Get unique group names (excluding empty)
            const groups = new Set();
            users.forEach(user => {
                if (user.groupName && user.groupName.trim()) {
                    groups.add(user.groupName);
                }
            });
            
            // Populate datalist
            datalist.innerHTML = '';
            groups.forEach(groupName => {
                const option = document.createElement('option');
                option.value = groupName;
                datalist.appendChild(option);
            });
        }
        
        // Load MediaMTX users if on users tab
        if (document.getElementById('users')) {
            loadMediaMTXUsers();
            loadPublicAccessStatus();  // Also load public access toggle state
        }
        
        // Test upload handler
        var currentUploadXHR = null;
        
        function cancelUpload() {
            if (currentUploadXHR) {
                currentUploadXHR.abort();
                currentUploadXHR = null;
                document.getElementById('upload-status').textContent = 'Upload cancelled';
                document.getElementById('upload-progress-bar').style.background = '#ff9800';
                document.getElementById('cancel-upload-btn').style.display = 'none';
                setTimeout(function() { 
                    document.getElementById('upload-progress').style.display = 'none'; 
                    document.getElementById('upload-progress-bar').style.background = '#4CAF50';
                }, 2000);
            }
        }
        
        var uploadFormEl = document.getElementById('upload-test-file');
        if (uploadFormEl) {
            uploadFormEl.addEventListener('submit', function(e) {
                e.preventDefault();
                var fileInput = document.getElementById('test-file-input');
                var file = fileInput.files[0];
                if (!file) { alert('Please select a file'); return; }
                var formData = new FormData();
                formData.append('test_file', file);
                var progressDiv = document.getElementById('upload-progress');
                var progressBar = document.getElementById('upload-progress-bar');
                var statusText = document.getElementById('upload-status');
                var cancelBtn = document.getElementById('cancel-upload-btn');
                progressDiv.style.display = 'block';
                cancelBtn.style.display = 'inline-block';
                progressBar.style.width = '0%';
                progressBar.style.background = '#4CAF50';
                statusText.textContent = 'Uploading...';
                currentUploadXHR = new XMLHttpRequest();
                currentUploadXHR.upload.addEventListener('progress', function(e) {
                    if (e.lengthComputable) {
                        var percent = (e.loaded / e.total) * 100;
                        progressBar.style.width = percent + '%';
                        statusText.textContent = 'Uploading: ' + Math.round(percent) + '%';
                    }
                });
                currentUploadXHR.addEventListener('load', function() {
                    cancelBtn.style.display = 'none';
                    currentUploadXHR = null;
                    if (this.status === 200) {
                        var response = JSON.parse(this.responseText);
                        if (response.success) {
                            statusText.textContent = 'Complete!';
                            progressBar.style.width = '100%';
                            fileInput.value = '';
                            setTimeout(function() { progressDiv.style.display = 'none'; loadTestFiles(); }, 2000);
                        } else {
                            statusText.textContent = 'Error: ' + response.error;
                            progressBar.style.background = '#f44336';
                        }
                    } else {
                        statusText.textContent = 'Failed';
                        progressBar.style.background = '#f44336';
                    }
                });
                currentUploadXHR.addEventListener('error', function() {
                    cancelBtn.style.display = 'none';
                    currentUploadXHR = null;
                    statusText.textContent = 'Network error';
                    progressBar.style.background = '#f44336';
                });
                currentUploadXHR.addEventListener('abort', function() {
                    cancelBtn.style.display = 'none';
                });
                currentUploadXHR.open('POST', '/api/test/upload');
                currentUploadXHR.send(formData);
            });
            loadTestFiles();
        }
        
        // HLS Viewer credential for embedded playback
        let hlsViewerCredential = null;
        
        // Fetch HLS viewer credential on page load
        fetch('/api/hlsviewer-credential')
            .then(response => response.json())
            .then(data => {
                if (data.username && data.password) {
                    hlsViewerCredential = data;
                    console.log('[HLS] Viewer credential loaded');
                }
            })
            .catch(err => console.error('[HLS] Failed to load viewer credential:', err));
        
        function watchStream(streamUrl) {
            console.log('[HLS] watchStream called with URL:', streamUrl);
            console.log('[HLS] Current credential:', hlsViewerCredential);
            
            if (!hlsViewerCredential) {
                alert('Viewer credential not loaded. Please refresh the page.');
                return;
            }
            
            // Parse URL and prepare credentials
            const url = new URL(streamUrl);
            const username = hlsViewerCredential.username;
            const password = hlsViewerCredential.password;
            
            console.log('[HLS] Original URL:', streamUrl);
            console.log('[HLS] Will use Authorization header with username:', username);
            
            // Open chromeless popup
            const width = 1280;
            const height = 720;
            const left = (screen.width - width) / 2;
            const top = (screen.height - height) / 2;
            
            const popup = window.open(
                '',
                'streamViewer_teststream',
                `width=${width},height=${height},left=${left},top=${top},` +
                'toolbar=no,location=no,directories=no,status=no,menubar=no,scrollbars=no,resizable=yes'
            );
            
            if (popup) {
                popup.document.write(`
                    <!DOCTYPE html>
                    <html>
                    <head>
                        <title>Stream - Live</title>
                        <style>
                            body { margin: 0; padding: 0; background: #000; overflow: hidden; }
                            #player { width: 100vw; height: 100vh; }
                        </style>
                        <script src="https://cdn.jsdelivr.net/npm/hls.js@latest"><\/script>
                    </head>
                    <body>
                        <video id="player" controls autoplay muted></video>
                        <script>
                            const video = document.getElementById('player');
                            const streamUrl = '${streamUrl}';
                            const username = '${username}';
                            const password = '${password}';
                            
                            if (Hls.isSupported()) {
                                const hls = new Hls({
                                    enableWorker: true,
                                    lowLatencyMode: true,
                                    backBufferLength: 90,
                                    xhrSetup: function(xhr, url) {
                                        // Add Basic Auth header
                                        const credentials = btoa(username + ':' + password);
                                        xhr.setRequestHeader('Authorization', 'Basic ' + credentials);
                                    }
                                });
                                hls.loadSource(streamUrl);
                                hls.attachMedia(video);
                                hls.on(Hls.Events.MANIFEST_PARSED, () => {
                                    video.play().catch(e => console.log('Autoplay blocked:', e));
                                });
                                hls.on(Hls.Events.ERROR, (event, data) => {
                                    console.error('HLS error:', data);
                                });
                            } else if (video.canPlayType('application/vnd.apple.mpegurl')) {
                                video.src = streamUrl;
                                video.addEventListener('loadedmetadata', () => {
                                    video.play().catch(e => console.log('Autoplay blocked:', e));
                                });
                            }
                        <\/script>
                    </body>
                    </html>
                `);
                popup.document.close();
            }
        }
        
        function loadTestFiles() {
            var container = document.getElementById('test-files-container');
            if (!container) return;
            
            fetch('/api/test/stream/status').then(function(r) { return r.json(); }).then(function(statusData) {
                fetch('/api/test/files').then(function(r) { return r.json(); }).then(function(data) {
                    if (data.files && data.files.length > 0) {
                        var html = '';
                        data.files.forEach(function(file) {
                            var isStreaming = statusData.streaming && statusData.filename === file.name;
                            var isTruck = file.name === 'truck_60.ts';
                            
                            if (isTruck) {
                                // Special styled box for truck_60.ts
                                var truckBg = isStreaming ? '#1b5e20' : 'linear-gradient(135deg, #1a2a1a 0%, #1a2a2a 100%)';
                                html += '<div style="background: ' + truckBg + '; padding: 15px; border-radius: 8px; margin-bottom: 10px; border: 1px solid #2d6d2d; display: flex; justify-content: space-between; align-items: center;">';
                                html += '<div>';
                                html += '<strong>🎬 ' + file.name + '</strong>';
                                if (isStreaming) {
                                    html += ' <span style="color: #4CAF50;">● STREAMING</span>';
                                }
                                html += '<p style="margin: 5px 0 0 0; color: #6d9d6d; font-size: 12px;">🔒 System test file — H264 + KLV reference stream for upgrade verification</p>';
                                html += '<p style="margin: 3px 0 0 0; color: #999; font-size: 12px;">Size: ' + file.size_mb + ' MB</p>';
                                html += '</div>';
                                html += '<div style="display: flex; gap: 10px;">';
                                if (isStreaming) {
                                    html += '<button class="btn btn-secondary" onclick="stopTestStream()">⏹ Stop</button>';
                                } else {
                                    html += '<button class="btn btn-success" onclick="playTestStream(\\'' + file.name + '\\')">▶ Play</button>';
                                }
                                html += '</div>';
                                html += '</div>';
                            } else {
                                // Regular file
                                var bgColor = isStreaming ? '#1b5e20' : '#2d2d2d';
                                html += '<div style="background: ' + bgColor + '; padding: 15px; border-radius: 8px; margin-bottom: 10px; display: flex; justify-content: space-between; align-items: center;">';
                                html += '<div>';
                                html += '<strong>' + file.name + '</strong>';
                                if (isStreaming) {
                                    html += ' <span style="color: #4CAF50;">● STREAMING</span>';
                                }
                                html += '<p style="margin: 5px 0 0 0; color: #999;">Size: ' + file.size_mb + ' MB</p>';
                                html += '</div>';
                                html += '<div style="display: flex; gap: 10px;">';
                                if (isStreaming) {
                                    html += '<button class="btn btn-secondary" onclick="stopTestStream()">⏹ Stop</button>';
                                } else {
                                    html += '<button class="btn btn-success" onclick="playTestStream(\\'' + file.name + '\\')">▶ Play</button>';
                                }
                                
                                // Only show Optimize button for non-optimized files
                                if (!file.name.endsWith('_optimized.ts')) {
                                    html += '<button class="btn" style="background: #FF9800;" onclick="optimizeTestFile(\\'' + file.name + '\\')">🔧 Optimize</button>';
                                }
                                
                                html += '<button class="btn btn-danger" onclick="deleteTestFile(\\'' + file.name + '\\')">🗑 Delete</button>';
                                html += '</div>';
                                html += '</div>';
                            }
                        });
                        container.innerHTML = html;
                    } else {
                        container.innerHTML = '<p style="color: #999;">No test files uploaded</p>';
                    }
                });
            });
        }
        
        function deleteTestFile(filename) {
            if (!confirm('Delete ' + filename + '?')) return;
            fetch('/api/test/delete/' + filename, {method: 'POST'}).then(function(r) { return r.json(); }).then(function(data) {
                if (data.success) { loadTestFiles(); } else { alert('Error: ' + data.error); }
            });
        }
        
        function optimizeTestFile(filename) {
            if (!confirm('Optimize ' + filename + '? This will create a new file: ' + filename.replace('.ts', '_optimized.ts'))) return;
            
            // Show progress indicator with timer
            const progressDiv = document.createElement('div');
            progressDiv.id = 'optimize-progress';
            progressDiv.style.cssText = 'position: fixed; top: 50%; left: 50%; transform: translate(-50%, -50%); background: #2d2d2d; padding: 30px; border-radius: 8px; box-shadow: 0 4px 20px rgba(0,0,0,0.5); z-index: 10000; min-width: 400px; text-align: center;';
            progressDiv.innerHTML = `
                <h3 style="margin: 0 0 15px 0; color: #fff;">Optimizing Video...</h3>
                <div style="font-size: 48px; margin: 20px 0; color: #4CAF50;">⏱️</div>
                <p id="optimize-timer" style="margin: 10px 0; color: #fff; font-size: 24px; font-family: monospace;">0m 00s</p>
                <p id="optimize-status" style="margin: 0; color: #999;">Processing ${filename}...</p>
            `;
            document.body.appendChild(progressDiv);
            
            const timerText = document.getElementById('optimize-timer');
            const statusText = document.getElementById('optimize-status');
            
            // Start elapsed time counter
            const startTime = Date.now();
            const timerInterval = setInterval(function() {
                const elapsed = Math.floor((Date.now() - startTime) / 1000);
                const minutes = Math.floor(elapsed / 60);
                const seconds = elapsed % 60;
                timerText.textContent = minutes + 'm ' + (seconds < 10 ? '0' : '') + seconds + 's';
            }, 1000);
            
            // Start optimization
            fetch('/api/test/optimize/' + filename, {method: 'POST'})
                .then(r => r.json())
                .then(data => {
                    clearInterval(timerInterval);
                    if (data.success) {
                        statusText.textContent = 'Complete!';
                        statusText.style.color = '#4CAF50';
                        setTimeout(function() {
                            document.body.removeChild(progressDiv);
                            loadTestFiles();
                        }, 2000);
                    } else {
                        statusText.textContent = 'Error: ' + (data.error || 'Unknown error');
                        statusText.style.color = '#f44336';
                        setTimeout(function() {
                            document.body.removeChild(progressDiv);
                        }, 5000);
                    }
                })
                .catch(err => {
                    clearInterval(timerInterval);
                    statusText.textContent = 'Error: ' + err;
                    statusText.style.color = '#f44336';
                    setTimeout(function() {
                        document.body.removeChild(progressDiv);
                    }, 5000);
                });
        }
        
        function playTestStream(filename) {
            fetch('/api/test/stream/start/' + filename, {method: 'POST'}).then(function(r) { return r.json(); }).then(function(data) {
                if (data.success) {
                    alert('Stream started!');
                    updateStreamURLs();
                    loadTestFiles();
                } else {
                    alert('Error: ' + data.error);
                }
            });
        }
        
        function updateStreamURLs() {
            // Get server info for URLs
            fetch('/api/stream-urls').then(function(r) { return r.json(); }).then(function(data) {
                var html = '<div style="line-height: 2.2;">';
                
                // Add warning at the top
                html += '<p style="margin: 0 0 15px 0; color: #2196F3; font-size: 13px; line-height: 1.5;">';
                html += 'ℹ️ <strong>Stream URLs for reference:</strong><br>';
                html += '• <strong>RTSP:</strong> Enable "Test Stream Viewing" toggle above for unauthenticated access<br>';
                html += '• <strong>SRT:</strong> If a passphrase is active (shown above), clear it in the Protocols tab to test without authentication<br>';
                html += '• <strong>HLS:</strong> Click "Watch" button for automatic authenticated playback';
                html += '</p>';
                
                // RTSP URL
                html += '<div style="margin-bottom: 10px;">';
                html += '<strong style="color: #4CAF50;">RTSP:</strong><br>';
                html += '<div style="display: flex; align-items: center; gap: 10px; margin-top: 5px;">';
                html += '<input type="text" readonly value="' + escapeHtml(data.rtsp) + '" style="flex: 1; background: #2d2d2d; border: 1px solid #444; color: #fff; padding: 8px; border-radius: 4px; font-family: monospace; font-size: 13px; cursor: text;">';
                html += '</div></div>';
                
                // SRT URL
                html += '<div style="margin-bottom: 10px;">';
                html += '<strong style="color: #4CAF50;">SRT:</strong><br>';
                html += '<div style="display: flex; align-items: center; gap: 10px; margin-top: 5px;">';
                html += '<input type="text" readonly value="' + escapeHtml(data.srt) + '" style="flex: 1; background: #2d2d2d; border: 1px solid #444; color: #fff; padding: 8px; border-radius: 4px; font-family: monospace; font-size: 13px; cursor: text;">';
                html += '</div></div>';
                
                // HLS URL (Watch button with embedded credentials)
                html += '<div style="margin-bottom: 10px;">';
                html += '<strong style="color: #4CAF50;">HLS:</strong><br>';
                html += '<div style="display: flex; align-items: center; gap: 10px; margin-top: 5px;">';
                html += '<input type="text" readonly value="' + escapeHtml(data.hls) + '" style="flex: 1; background: #2d2d2d; border: 1px solid #444; color: #fff; padding: 8px; border-radius: 4px; font-family: monospace; font-size: 13px; cursor: text;">';
                html += '<button class="watch-btn" data-url="' + data.hls + '" style="background: #4CAF50; color: white; border: none; padding: 8px 15px; border-radius: 4px; cursor: pointer; white-space: nowrap;">▶️ Watch</button>';
                html += '</div></div>';
                
                html += '</div>';
                document.getElementById('stream-urls-content').innerHTML = html;
                
                // Add click handler for Watch button
                var watchBtn = document.querySelector('.watch-btn');
                if (watchBtn) {
                    watchBtn.addEventListener('click', function() {
                        watchStream(this.getAttribute('data-url'));
                    });
                }
            });
        }
        
        function escapeHtml(text) {
            var map = {
                '&': '&amp;',
                '<': '&lt;',
                '>': '&gt;',
                '"': '&quot;',
                "'": '&#039;'
            };
            return text.replace(/[&<>"']/g, function(m) { return map[m]; });
        }
        
        function copyToClipboard(text) {
            navigator.clipboard.writeText(text).then(function() {
                // Show temporary success message
                var msg = document.createElement('div');
                msg.textContent = '✓ Copied!';
                msg.style.cssText = 'position: fixed; top: 20px; right: 20px; background: #4CAF50; color: white; padding: 10px 20px; border-radius: 6px; z-index: 10000; font-weight: bold;';
                document.body.appendChild(msg);
                setTimeout(function() { document.body.removeChild(msg); }, 2000);
            }).catch(function(err) {
                alert('Failed to copy: ' + err);
            });
        }
        
        function stopTestStream() {
            if (!confirm('Stop streaming?')) return;
            fetch('/api/test/stream/stop', {method: 'POST'}).then(function(r) { return r.json(); }).then(function(data) {
                if (data.success) {
                    document.getElementById('stream-urls-content').innerHTML = '<p style="color: #999; font-style: italic;">Start streaming to see URLs...</p>';
                    loadTestFiles();
                } else {
                    alert('Error: ' + data.error);
                }
            });
        }
        
        // === RECORDING FUNCTIONS ===
        
        function loadRecordingSettings() {
            fetch('/api/recordings/settings')
                .then(r => r.json())
                .then(data => {
                    document.getElementById('recording-enabled').checked = data.enabled || false;
                    
                    // Map 0s (from YAML) back to 0 (dropdown value for "Never")
                    let retention = data.retention || '168h';
                    if (retention === '0s') {
                        retention = '0';
                    }
                    document.getElementById('recording-retention').value = retention;
                    
                    // Load timezone from localStorage
                    const savedTimezone = localStorage.getItem('recording-timezone') || 'UTC';
                    document.getElementById('recording-timezone').value = savedTimezone;
                });
        }
        
        function saveRecordingSettings() {
            const enabled = document.getElementById('recording-enabled').checked;
            const retention = document.getElementById('recording-retention').value;
            const timezone = document.getElementById('recording-timezone').value;
            
            // Save timezone to localStorage
            localStorage.setItem('recording-timezone', timezone);
            
            fetch('/api/recordings/settings', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({enabled, retention})
            })
            .then(r => r.json())
            .then(data => {
                if (data.success) {
                    alert('✅ Recording settings saved! MediaMTX will restart.');
                    loadRecordingSettings();
                    // Wait 3 seconds for MediaMTX to restart before reloading recordings list
                    setTimeout(loadRecordings, 3000);
                } else {
                    alert('❌ Error: ' + data.error);
                }
            });
        }
        
        // Convert UTC timestamp to user's selected timezone
        function convertToTimezone(utcDateStr) {
            const timezone = localStorage.getItem('recording-timezone') || 'UTC';
            const date = new Date(utcDateStr + ' UTC'); // Parse as UTC
            
            // Format with colons in time
            return date.toLocaleString('en-US', {
                timeZone: timezone,
                year: 'numeric',
                month: '2-digit',
                day: '2-digit',
                hour: '2-digit',
                minute: '2-digit',
                second: '2-digit',
                hour12: false
            }).replace(/(\d+)\/(\d+)\/(\d+),/, '$3-$1-$2'); // Format as YYYY-MM-DD HH:MM:SS
        }
        
        function saveTimezone() {
            const timezone = document.getElementById('recording-timezone').value;
            localStorage.setItem('recording-timezone', timezone);
            loadRecordings(); // Reload with new timezone
        }
        
        function loadDiskUsage() {
            fetch('/api/recordings/disk-usage')
                .then(r => r.json())
                .then(data => {
                    const container = document.getElementById('disk-usage-content');
                    const usedPercent = (data.used / data.total * 100).toFixed(1);
                    const usedGB = (data.used / 1024 / 1024 / 1024).toFixed(2);
                    const totalGB = (data.total / 1024 / 1024 / 1024).toFixed(2);
                    const freeGB = (data.free / 1024 / 1024 / 1024).toFixed(2);
                    
                    let barColor = '#4CAF50';
                    if (usedPercent > 80) barColor = '#f44336';
                    else if (usedPercent > 60) barColor = '#FF9800';
                    
                    container.innerHTML = `
                        <div style="margin-bottom: 15px;">
                            <div style="display: flex; justify-content: space-between; margin-bottom: 5px;">
                                <span style="color: #fff; font-weight: bold;">${usedGB} GB / ${totalGB} GB (${usedPercent}% used)</span>
                                <span style="color: #999;">${freeGB} GB free</span>
                            </div>
                            <div style="background: #444; height: 30px; border-radius: 15px; overflow: hidden;">
                                <div style="background: ${barColor}; height: 100%; width: ${usedPercent}%; transition: width 0.3s;"></div>
                            </div>
                        </div>
                    `;
                });
        }
        
        function loadRecordings() {
            fetch('/api/recordings/list')
                .then(r => r.json())
                .then(data => {
                    window.recordingsData = data.recordings || [];
                    renderRecordingsTable();
                });
        }
        
        function renderRecordingsTable(sortBy = 'created', sortDir = 'desc') {
            const container = document.getElementById('recordings-list');
            const recordings = window.recordingsData || [];
            
            if (recordings.length > 0) {
                // Sort recordings
                const sorted = [...recordings].sort((a, b) => {
                    let aVal, bVal;
                    
                    if (sortBy === 'filename') {
                        aVal = a.name.toLowerCase();
                        bVal = b.name.toLowerCase();
                    } else if (sortBy === 'size') {
                        aVal = a.size_mb;
                        bVal = b.size_mb;
                    } else if (sortBy === 'created') {
                        aVal = new Date(a.date).getTime();
                        bVal = new Date(b.date).getTime();
                    } else if (sortBy === 'expires') {
                        const getValue = (text) => {
                            if (text === 'Never') return 999999;
                            if (text === 'Expired') return -1;
                            const num = parseInt(text);
                            return text.includes('h') ? num / 24 : num;
                        };
                        aVal = getValue(a.expires_text);
                        bVal = getValue(b.expires_text);
                    }
                    
                    return sortDir === 'asc' ? (aVal > bVal ? 1 : -1) : (aVal < bVal ? 1 : -1);
                });
                
                let html = '<div style="overflow-x: auto;">';
                html += '<table style="width: 100%; border-collapse: collapse;">';
                html += '<thead><tr style="background: #1a1a1a; text-align: left;">';
                
                const arrow = (col) => {
                    if (col !== sortBy) return ' ⬍';
                    return sortDir === 'asc' ? ' ▲' : ' ▼';
                };
                
                html += `<th onclick="sortRecordings('filename')" style="padding: 12px; color: #4CAF50; cursor: pointer;">Filename${arrow('filename')}</th>`;
                html += `<th onclick="sortRecordings('size')" style="padding: 12px; color: #4CAF50; cursor: pointer;">Size${arrow('size')}</th>`;
                html += `<th onclick="sortRecordings('created')" style="padding: 12px; color: #4CAF50; cursor: pointer;">Created${arrow('created')}</th>`;
                html += `<th onclick="sortRecordings('expires')" style="padding: 12px; color: #4CAF50; cursor: pointer;">Expires${arrow('expires')}</th>`;
                html += '<th style="padding: 12px; color: #4CAF50; text-align: center;">Actions</th>';
                html += '</tr></thead><tbody>';
                
                sorted.forEach(rec => {
                    html += '<tr style="border-bottom: 1px solid #444;">';
                    
                    // Filename with recording badge if active
                    html += '<td style="padding: 12px; color: #fff;">';
                    if (rec.is_recording) {
                        html += '<span style="color: #f44336; font-weight: bold;">🔴 </span>';
                    }
                    html += rec.name;
                    if (rec.is_recording) {
                        html += ' <span style="color: #f44336; font-size: 11px; font-weight: bold;">[RECORDING]</span>';
                    }
                    html += '</td>';
                    
                    html += `<td style="padding: 12px; color: #999;">${rec.size_mb} MB</td>`;
                    
                    // Convert created time to user's timezone
                    const localTime = convertToTimezone(rec.date);
                    html += `<td style="padding: 12px; color: #999;">${localTime}</td>`;
                    
                    html += `<td style="padding: 12px; color: ${rec.expires_color};">${rec.expires_text}</td>`;
                    html += '<td style="padding: 12px; text-align: center; white-space: nowrap;">';
                    html += `<button onclick="playRecording('${rec.name}')" class="btn btn-success" style="margin-right: 5px; padding: 6px 12px; font-size: 13px;">▶️ Watch</button>`;
                    html += `<button onclick="downloadRecording('${rec.name}')" class="btn btn-primary" style="margin-right: 5px; padding: 6px 12px; font-size: 13px;">⬇️ .TS</button>`;
                    html += `<button onclick="downloadMP4('${rec.name}')" class="btn btn-info" style="margin-right: 5px; padding: 6px 12px; font-size: 13px;">⬇️ MP4</button>`;
                    html += `<button onclick="deleteRecording('${rec.name}')" class="btn btn-danger" style="padding: 6px 12px; font-size: 13px;">🗑️ Delete</button>`;
                    html += '</td></tr>';
                });
                
                html += '</tbody></table></div>';
                container.innerHTML = html;
                
                // Store current sort state
                window.currentSort = {by: sortBy, dir: sortDir};
            } else {
                container.innerHTML = '<p style="color: #999; text-align: center; padding: 40px;">No recordings found</p>';
            }
        }
        
        function downloadRecording(filename) {
            window.location.href = '/api/recordings/download/' + filename;
        }
        
        function downloadMP4(filename) {
            // Show converting popup
            const popup = document.createElement('div');
            popup.style.cssText = 'position: fixed; top: 50%; left: 50%; transform: translate(-50%, -50%); background: #2d2d2d; color: white; padding: 30px 50px; border-radius: 12px; z-index: 10000; box-shadow: 0 10px 40px rgba(0,0,0,0.5); text-align: center;';
            popup.innerHTML = `
                <div style="font-size: 24px; margin-bottom: 15px;">🎬 Converting to MP4...</div>
                <div style="font-size: 14px; color: #999;">This may take a minute depending on file size</div>
                <div style="margin-top: 20px;">
                    <div class="spinner" style="border: 3px solid #444; border-top: 3px solid #4CAF50; border-radius: 50%; width: 40px; height: 40px; animation: spin 1s linear infinite; margin: 0 auto;"></div>
                </div>
            `;
            document.body.appendChild(popup);
            
            // Add spinner animation
            const style = document.createElement('style');
            style.textContent = '@keyframes spin { 0% { transform: rotate(0deg); } 100% { transform: rotate(360deg); } }';
            document.head.appendChild(style);
            
            // Start conversion and download
            fetch(`/api/recordings/convert-mp4/${filename}`)
                .then(response => {
                    if (!response.ok) throw new Error('Conversion failed');
                    return response.blob();
                })
                .then(blob => {
                    // Remove popup
                    document.body.removeChild(popup);
                    
                    // Download MP4
                    const url = window.URL.createObjectURL(blob);
                    const a = document.createElement('a');
                    a.href = url;
                    a.download = filename.replace('.ts', '.mp4');
                    document.body.appendChild(a);
                    a.click();
                    window.URL.revokeObjectURL(url);
                    document.body.removeChild(a);
                })
                .catch(err => {
                    document.body.removeChild(popup);
                    alert('Error converting to MP4: ' + err.message);
                });
        }
        
        function playRecording(filename) {
            // Open playback in a chromeless popup window
            const width = 1280;
            const height = 720;
            const left = (screen.width - width) / 2;
            const top = (screen.height - height) / 2;
            
            const playbackUrl = `/api/recordings/play/${filename}`;
            window.open(
                playbackUrl,
                'playback',
                `width=${width},height=${height},left=${left},top=${top},toolbar=no,menubar=no,location=no,status=no`
            );
        }
        
        function deleteRecording(filename) {
            if (!confirm('Delete recording: ' + filename + '?')) return;
            
            fetch('/api/recordings/delete/' + filename, {method: 'POST'})
                .then(r => r.json())
                .then(data => {
                    if (data.success) {
                        loadRecordings();
                        loadDiskUsage();
                    } else {
                        alert('Error: ' + data.error);
                    }
                });
        }
        
        function sortRecordings(column) {
            const current = window.currentSort || {by: 'created', dir: 'desc'};
            let newDir = 'asc';
            
            if (current.by === column) {
                // Toggle direction
                newDir = current.dir === 'asc' ? 'desc' : 'asc';
            } else {
                // Default direction for new column
                newDir = column === 'created' ? 'desc' : 'asc';
            }
            
            renderRecordingsTable(column, newDir);
        }
        
        // === END RECORDING FUNCTIONS ===
        
        // === DASHBOARD FUNCTIONS ===
        
        function drawGauge(canvasId, percent, color) {
            const canvas = document.getElementById(canvasId);
            if (!canvas) return;
            
            const ctx = canvas.getContext('2d');
            const centerX = 100;
            const centerY = 100;
            const radius = 80;
            
            // Clear canvas
            ctx.clearRect(0, 0, 200, 200);
            
            // Background circle
            ctx.beginPath();
            ctx.arc(centerX, centerY, radius, 0, 2 * Math.PI);
            ctx.strokeStyle = '#2a2a2a';
            ctx.lineWidth = 20;
            ctx.stroke();
            
            // Progress arc
            const angle = (percent / 100) * 2 * Math.PI;
            ctx.beginPath();
            ctx.arc(centerX, centerY, radius, -0.5 * Math.PI, -0.5 * Math.PI + angle);
            ctx.strokeStyle = color;
            ctx.lineWidth = 20;
            ctx.lineCap = 'round';
            ctx.stroke();
        }
        
        function formatBytes(bytes) {
            if (bytes === 0) return '0 B';
            const k = 1024;
            const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
            const i = Math.floor(Math.log(bytes) / Math.log(k));
            return Math.round(bytes / Math.pow(k, i) * 100) / 100 + ' ' + sizes[i];
        }
        
        function formatUptime(seconds) {
            const days = Math.floor(seconds / 86400);
            const hours = Math.floor((seconds % 86400) / 3600);
            const mins = Math.floor((seconds % 3600) / 60);
            
            if (days > 0) return `${days}d ${hours}h`;
            if (hours > 0) return `${hours}h ${mins}m`;
            return `${mins}m`;
        }
        
        function loadDashboardMetrics() {
            fetch('/api/dashboard/metrics')
                .then(r => r.json())
                .then(data => {
                    // Update big stat cards
                    document.getElementById('active-streams-count').textContent = data.active_streams || 0;
                    document.getElementById('total-viewers-count').textContent = data.total_viewers || 0;
                    document.getElementById('recordings-size').textContent = formatBytes(data.recordings_size || 0);
                    document.getElementById('server-uptime').textContent = formatUptime(data.uptime || 0);
                    
                    // Update CPU gauge
                    const cpuPercent = Math.round(data.cpu_percent || 0);
                    document.getElementById('cpu-percent').textContent = cpuPercent + '%';
                    const cpuColor = cpuPercent > 80 ? '#f44336' : cpuPercent > 60 ? '#FF9800' : '#4CAF50';
                    drawGauge('cpu-gauge', cpuPercent, cpuColor);
                    
                    // Update RAM gauge
                    const ramPercent = Math.round(data.ram_percent || 0);
                    document.getElementById('ram-percent').textContent = ramPercent + '%';
                    const ramColor = ramPercent > 80 ? '#f44336' : ramPercent > 60 ? '#FF9800' : '#4CAF50';
                    drawGauge('ram-gauge', ramPercent, ramColor);
                    
                    // Update Disk usage
                    const diskPercent = Math.round(data.disk_percent || 0);
                    document.getElementById('disk-percent').textContent = diskPercent + '%';
                    document.getElementById('disk-details').textContent = 
                        `${formatBytes(data.disk_used || 0)} / ${formatBytes(data.disk_total || 0)}`;
                    
                    // Update Network (bandwidth rate)
                    document.getElementById('network-rx').textContent = formatBytes(data.network_rx_rate || 0) + '/s';
                    document.getElementById('network-tx').textContent = formatBytes(data.network_tx_rate || 0) + '/s';
                })
                .catch(err => console.error('Dashboard error:', err));
        }
        
        // Auto-refresh dashboard every 5 seconds
        let dashboardInterval;
        let updateCheckDone = false;
        
        function startDashboardRefresh() {
            loadDashboardMetrics();
            dashboardInterval = setInterval(loadDashboardMetrics, 5000);
            // Check for updates once per session when dashboard opens
            if (!updateCheckDone) {
                updateCheckDone = true;
                setTimeout(checkForUpdate, 1500);  // Slight delay so dashboard loads first
                setTimeout(checkMediaMTXUpdate, 2000);  // Check MediaMTX version too
                setTimeout(checkRollbackAvailable, 2500);  // Check if rollback is available
            }
        }
        
        function stopDashboardRefresh() {
            if (dashboardInterval) {
                clearInterval(dashboardInterval);
                dashboardInterval = null;
            }
        }
        
        // === UPDATE CHECKER FUNCTIONS ===
        
        function checkForUpdate() {
            fetch('/api/update/check')
            .then(res => res.json())
            .then(data => {
                if (data.success && data.update_available) {
                    // Show update banner
                    document.getElementById('update-banner').style.display = 'block';
                    document.getElementById('update-remote-version').textContent = data.remote_version;
                    document.getElementById('update-current-version').textContent = data.current_version;
                    document.getElementById('update-release-notes').textContent = data.release_notes || 'No release notes.';
                    document.getElementById('update-github-link').href = data.html_url || '#';
                    
                    // Format published date
                    if (data.published_at) {
                        const d = new Date(data.published_at);
                        document.getElementById('update-published').textContent = d.toLocaleDateString();
                    }
                    
                    // Hide version badge
                    document.getElementById('version-badge').style.display = 'none';
                } else if (data.success) {
                    // Up to date - show small version badge
                    document.getElementById('version-badge').style.display = 'block';
                    document.getElementById('version-current').textContent = data.current_version;
                    document.getElementById('update-banner').style.display = 'none';
                }
                // If check failed (no internet, etc.), silently ignore
            })
            .catch(() => {
                // Network error - silently ignore, don't bother the user
            });
        }
        
        function applyUpdate() {
            if (!confirm('This will download the latest version from GitHub, replace the current web editor, and restart the service. You will be briefly disconnected.\\n\\nContinue?')) {
                return;
            }
            
            const btn = document.getElementById('update-apply-btn');
            btn.disabled = true;
            btn.textContent = '⏳ Updating...';
            
            const progress = document.getElementById('update-progress');
            progress.style.display = 'block';
            document.getElementById('update-progress-text').textContent = '⏳ Downloading update from GitHub...';
            
            fetch('/api/update/apply', { method: 'POST' })
            .then(res => res.json())
            .then(data => {
                if (data.success) {
                    document.getElementById('update-progress-text').innerHTML = 
                        '✅ Update applied! Updated to <strong>' + data.new_version + '</strong>. Backup saved. Reloading page...';
                    progress.style.background = 'rgba(34, 197, 94, 0.15)';
                    progress.style.border = '1px solid #22c55e';
                    // Wait for service to restart then reload
                    setTimeout(() => {
                        window.location.href = '/?tab=dashboard&message=Successfully updated to ' + data.new_version + '&message_type=success';
                    }, 4000);
                } else {
                    document.getElementById('update-progress-text').textContent = 
                        '❌ Update failed: ' + (data.error || 'Unknown error');
                    progress.style.background = 'rgba(239, 68, 68, 0.15)';
                    progress.style.border = '1px solid #ef4444';
                    btn.disabled = false;
                    btn.textContent = '⬆️ Update Now';
                }
            })
            .catch(err => {
                // Service probably restarted successfully but killed our connection
                document.getElementById('update-progress-text').innerHTML = 
                    '✅ Service is restarting... Reloading page in a moment.';
                progress.style.background = 'rgba(34, 197, 94, 0.15)';
                setTimeout(() => {
                    window.location.href = '/?tab=dashboard&message=Update applied successfully&message_type=success';
                }, 5000);
            });
        }
        
        function dismissUpdate() {
            document.getElementById('update-banner').style.display = 'none';
        }
        
        // === MEDIAMTX UPDATE CHECKER FUNCTIONS ===
        
        var mediamtxUpdateCheckDone = false;
        var mediamtxSkippedVersion = localStorage.getItem('mediamtx_skipped_version') || '';
        
        function checkMediaMTXUpdate() {
            fetch('/api/mediamtx/version/check')
            .then(res => res.json())
            .then(data => {
                if (data.success && data.update_available) {
                    // Check if user skipped this version
                    if (data.remote_version === mediamtxSkippedVersion) {
                        // Show as up to date with skip note
                        document.getElementById('mediamtx-version-badge').style.display = 'block';
                        document.getElementById('mediamtx-version-badge').innerHTML = 
                            '✅ MediaMTX <span id="mediamtx-version-current">' + data.current_version + '</span> — <span style="color:#666;">update ' + data.remote_version + ' skipped</span> ' +
                            '<button onclick="unskipMediaMTXUpdate()" style="margin-left: 10px; background: #2563eb; color: white; border: none; border-radius: 4px; padding: 4px 12px; cursor: pointer; font-size: 12px;">Check for Updates</button>';
                        return;
                    }
                    // Show update banner
                    document.getElementById('mediamtx-update-banner').style.display = 'block';
                    document.getElementById('mediamtx-update-remote-version').textContent = data.remote_version;
                    document.getElementById('mediamtx-update-current-version').textContent = data.current_version;
                    document.getElementById('mediamtx-update-release-notes').textContent = data.release_notes || 'No release notes.';
                    document.getElementById('mediamtx-update-github-link').href = data.html_url || '#';
                    
                    // Reset progress area and button from any previous upgrade
                    document.getElementById('mediamtx-update-progress').style.display = 'none';
                    document.getElementById('mediamtx-update-progress').style.background = '';
                    document.getElementById('mediamtx-update-progress').style.border = '';
                    document.getElementById('mediamtx-update-apply-btn').disabled = false;
                    document.getElementById('mediamtx-update-apply-btn').textContent = '⬆️ Upgrade MediaMTX';
                    
                    if (data.published_at) {
                        const d = new Date(data.published_at);
                        document.getElementById('mediamtx-update-published').textContent = d.toLocaleDateString();
                    }
                    
                    document.getElementById('mediamtx-version-badge').style.display = 'none';
                } else if (data.success) {
                    document.getElementById('mediamtx-version-badge').style.display = 'block';
                    document.getElementById('mediamtx-version-badge').innerHTML = 
                        '✅ MediaMTX <span id="mediamtx-version-current">' + data.current_version + '</span> — up to date';
                    document.getElementById('mediamtx-update-banner').style.display = 'none';
                }
            })
            .catch(() => {});
        }
        
        function applyMediaMTXUpdate() {
            if (!confirm('This will:\\n\\n1. Stop MediaMTX\\n2. Back up the current binary\\n3. Download the latest version\\n4. Replace the binary (your config YAML is preserved)\\n5. Restart MediaMTX\\n6. Auto-test stream verification\\n\\nActive streams will be interrupted. Continue?')) {
                return;
            }
            
            const btn = document.getElementById('mediamtx-update-apply-btn');
            btn.disabled = true;
            btn.textContent = '⏳ Upgrading...';
            
            const progress = document.getElementById('mediamtx-update-progress');
            progress.style.display = 'block';
            document.getElementById('mediamtx-update-progress-text').textContent = '⏳ Step 1/3: Stopping MediaMTX and downloading new version...';
            
            fetch('/api/mediamtx/version/upgrade', { method: 'POST' })
            .then(res => res.json())
            .then(data => {
                if (data.success) {
                    // Step 2: Auto-test
                    document.getElementById('mediamtx-update-progress-text').innerHTML = 
                        '⏳ Step 2/3: Upgraded to <strong>' + data.new_version + '</strong>. Running stream verification test...';
                    
                    return fetch('/api/mediamtx/version/test', { method: 'POST' })
                    .then(res => res.json())
                    .then(testData => {
                        if (testData.success && testData.passed) {
                            // All good!
                            document.getElementById('mediamtx-update-progress-text').innerHTML = 
                                '✅ Step 3/3: Upgrade verified! MediaMTX <strong>' + data.new_version + '</strong> — ' +
                                'Codec: ' + (testData.codec || 'OK') + ' ✅ | Tracks: ' + (testData.tracks || 'N/A');
                            progress.style.background = 'rgba(34, 197, 94, 0.15)';
                            progress.style.border = '1px solid #22c55e';
                            setTimeout(() => {
                                document.getElementById('mediamtx-update-banner').style.display = 'none';
                                mediamtxUpdateCheckDone = false;
                                checkMediaMTXUpdate();
                                // Show rollback option with previous version
                                showRollbackBanner(data.previous_version || 'previous', 'Backup from upgrade to ' + data.new_version);
                            }, 4000);
                        } else {
                            // Test failed — offer rollback
                            var failReason = testData.error || testData.reason || 'Stream test failed';
                            document.getElementById('mediamtx-update-progress-text').innerHTML = 
                                '⚠️ Step 3/3: Upgrade completed but stream test failed: <strong>' + failReason + '</strong><br>' +
                                '<span style="color: #fbbf24;">Recommendation: Roll back to the previous version.</span>';
                            progress.style.background = 'rgba(251, 191, 36, 0.15)';
                            progress.style.border = '1px solid #fbbf24';
                            
                            // Show rollback banner
                            showRollbackBanner(data.previous_version || 'previous', 'Stream verification failed after upgrade');
                            
                            btn.disabled = false;
                            btn.textContent = '⬆️ Upgrade MediaMTX';
                        }
                    });
                } else {
                    document.getElementById('mediamtx-update-progress-text').textContent = 
                        '❌ Upgrade failed: ' + (data.error || 'Unknown error') + (data.rollback ? ' (rolled back to previous version)' : '');
                    progress.style.background = 'rgba(239, 68, 68, 0.15)';
                    progress.style.border = '1px solid #ef4444';
                    btn.disabled = false;
                    btn.textContent = '⬆️ Upgrade MediaMTX';
                }
            })
            .catch(err => {
                document.getElementById('mediamtx-update-progress-text').textContent = 
                    '❌ Error: ' + err;
                progress.style.background = 'rgba(239, 68, 68, 0.15)';
                btn.disabled = false;
                btn.textContent = '⬆️ Upgrade MediaMTX';
            });
        }
        
        function showRollbackBanner(version, reason) {
            document.getElementById('mediamtx-rollback-banner').style.display = 'block';
            document.getElementById('rollback-version').textContent = version;
            document.getElementById('rollback-reason').textContent = reason;
            // Reset button state
            var btn = document.getElementById('mediamtx-rollback-btn');
            btn.disabled = false;
            btn.textContent = '⏪ Rollback';
        }
        
        function dismissRollback() {
            document.getElementById('mediamtx-rollback-banner').style.display = 'none';
        }
        
        function rollbackMediaMTX() {
            if (!confirm('This will:\\n\\n1. Stop MediaMTX\\n2. Restore the previous binary from backup\\n3. Restart MediaMTX\\n\\nActive streams will be interrupted. Continue?')) {
                return;
            }
            
            const btn = document.getElementById('mediamtx-rollback-btn');
            btn.disabled = true;
            btn.textContent = '⏳ Rolling back...';
            
            fetch('/api/mediamtx/version/rollback', { method: 'POST' })
            .then(res => res.json())
            .then(data => {
                if (data.success) {
                    var msg = '✅ Rolled back to MediaMTX ' + (data.restored_version || 'previous version') + '.';
                    if (data.fields_removed && data.fields_removed.length > 0) {
                        msg += ' | Auto-removed incompatible YAML fields: ' + data.fields_removed.join(', ');
                    }
                    alert(msg);
                    document.getElementById('mediamtx-rollback-banner').style.display = 'none';
                    document.getElementById('mediamtx-update-banner').style.display = 'none';
                    // Update the version badge properly
                    document.getElementById('mediamtx-version-badge').style.display = 'block';
                    document.getElementById('mediamtx-version-badge').innerHTML = 
                        '⏪ MediaMTX <span id="mediamtx-version-current">' + (data.restored_version || 'previous version') + '</span> — rolled back successfully ' +
                        '<button onclick="mediamtxUpdateCheckDone=false;checkMediaMTXUpdate();" style="margin-left: 10px; background: #2563eb; color: white; border: none; border-radius: 4px; padding: 4px 12px; cursor: pointer; font-size: 12px;">Check for Updates</button>';
                } else {
                    alert('❌ Rollback failed: ' + (data.error || 'Unknown error'));
                    btn.disabled = false;
                    btn.textContent = '⏪ Rollback';
                }
            })
            .catch(err => {
                alert('❌ Rollback error: ' + err);
                btn.disabled = false;
                btn.textContent = '⏪ Rollback';
            });
        }
        
        function checkRollbackAvailable() {
            fetch('/api/mediamtx/version/rollback/status')
            .then(res => res.json())
            .then(data => {
                if (data.available) {
                    showRollbackBanner(data.backup_version || 'unknown', 'Backup from ' + (data.backup_date || 'recent upgrade'));
                }
            })
            .catch(() => {});
        }
        
        function skipMediaMTXUpdate() {
            const version = document.getElementById('mediamtx-update-remote-version').textContent;
            if (confirm('Skip MediaMTX ' + version + '? You can still upgrade later from the dashboard.')) {
                localStorage.setItem('mediamtx_skipped_version', version);
                mediamtxSkippedVersion = version;
                document.getElementById('mediamtx-update-banner').style.display = 'none';
                const currentVer = document.getElementById('mediamtx-update-current-version').textContent;
                document.getElementById('mediamtx-version-badge').style.display = 'block';
                document.getElementById('mediamtx-version-badge').innerHTML = 
                    '✅ MediaMTX <span id="mediamtx-version-current">' + currentVer + '</span> — <span style="color:#666;">update ' + version + ' skipped</span> ' +
                    '<button onclick="unskipMediaMTXUpdate()" style="margin-left: 10px; background: #2563eb; color: white; border: none; border-radius: 4px; padding: 4px 12px; cursor: pointer; font-size: 12px;">Check for Updates</button>';
            }
        }
        
        function unskipMediaMTXUpdate() {
            localStorage.removeItem('mediamtx_skipped_version');
            mediamtxSkippedVersion = '';
            mediamtxUpdateCheckDone = false;
            checkMediaMTXUpdate();
        }
        
        function dismissMediaMTXUpdate() {
            document.getElementById('mediamtx-update-banner').style.display = 'none';
        }
        
        // === END MEDIAMTX UPDATE CHECKER FUNCTIONS ===
        
        // Refresh YAML content
        function refreshYAML() {
            fetch('/get_yaml')
                .then(r => r.text())
                .then(yaml => {
                    document.getElementById('yaml-textarea').value = yaml;
                    alert('YAML refreshed!');
                })
                .catch(err => alert('Error refreshing YAML: ' + err));
        }
        
        // Public Access Toggle
        function loadPublicAccessStatus() {
            fetch('/api/public-access/status')
                .then(r => r.json())
                .then(data => {
                    const toggle = document.getElementById('public-access-toggle');
                    if (toggle) toggle.checked = data.enabled;
                });
        }
        
        function togglePublicAccess() {
            const toggle = document.getElementById('public-access-toggle');
            const isEnabled = toggle.checked;
            
            const action = isEnabled ? 'Enabling' : 'Disabling';
            const statusMsg = document.createElement('div');
            statusMsg.style.cssText = 'position: fixed; top: 20px; right: 20px; background: #2196F3; color: white; padding: 15px 20px; border-radius: 6px; z-index: 10000;';
            statusMsg.textContent = action + ' public access... Restarting MediaMTX...';
            document.body.appendChild(statusMsg);
            
            fetch('/api/public-access/toggle', {method: 'POST'})
                .then(r => r.json())
                .then(data => {
                    document.body.removeChild(statusMsg);
                    if (data.success) {
                        alert(data.message + '\\n\\nMediaMTX has been restarted.');
                        // Delay starts AFTER user clicks OK on the alert
                        if (typeof loadMediaMTXUsers === 'function') {
                            setTimeout(function() {
                                loadMediaMTXUsers();
                                // Retry again after 3 more seconds in case first attempt got empty
                                setTimeout(loadMediaMTXUsers, 3000);
                            }, 2000);
                        }
                        setTimeout(loadPublicAccessStatus, 2000);
                    } else {
                        alert('Error: ' + data.error);
                        loadPublicAccessStatus();
                    }
                })
                .catch(err => {
                    document.body.removeChild(statusMsg);
                    alert('Error: ' + err);
                    loadPublicAccessStatus();
                });
        }
        
        // Test Stream Viewer Toggle
        function loadTestStreamViewerStatus() {
            fetch('/api/teststream-viewer/status')
                .then(r => r.json())
                .then(data => {
                    const toggle = document.getElementById('teststream-viewer-toggle');
                    if (toggle) toggle.checked = data.enabled;
                });
        }
        
        function toggleTestStreamViewer() {
            const toggle = document.getElementById('teststream-viewer-toggle');
            const isEnabled = toggle.checked;
            
            const action = isEnabled ? 'Enabling' : 'Disabling';
            const statusMsg = document.createElement('div');
            statusMsg.style.cssText = 'position: fixed; top: 20px; right: 20px; background: #2196F3; color: white; padding: 15px 20px; border-radius: 6px; z-index: 10000;';
            statusMsg.textContent = action + ' test stream viewer... Restarting MediaMTX...';
            document.body.appendChild(statusMsg);
            
            fetch('/api/teststream-viewer/toggle', {method: 'POST'})
                .then(r => r.json())
                .then(data => {
                    document.body.removeChild(statusMsg);
                    if (data.success) {
                        alert(data.message + '\\n\\nMediaMTX has been restarted.');
                    } else {
                        alert('Error: ' + data.error);
                        loadTestStreamViewerStatus();
                    }
                })
                .catch(err => {
                    document.body.removeChild(statusMsg);
                    alert('Error: ' + err);
                    loadTestStreamViewerStatus();
                });
        }
        
        // SRT Passphrase Status (read-only display)
        function loadSRTPassphraseStatus() {
            fetch('/api/srt-passphrase/status')
                .then(r => r.json())
                .then(data => {
                    const valueDisplay = document.getElementById('srt-passphrase-value');
                    const helpDisplay = document.getElementById('srt-passphrase-help');
                    if (!valueDisplay) return;
                    if (data.publishPassphrase || data.readPassphrase) {
                        let text = '🔒 Active — ';
                        if (data.publishPassphrase) text += 'Publish: ' + data.publishPassphrase;
                        if (data.readPassphrase) {
                            if (data.publishPassphrase) text += ' | ';
                            text += 'Read: ' + data.readPassphrase;
                        }
                        valueDisplay.textContent = text;
                        valueDisplay.style.color = '#ff9800';
                        if (helpDisplay) helpDisplay.innerHTML = 'To test SRT streams using the URL below, clear the passphrase in the <strong>Protocols</strong> tab. Otherwise, SRT clients must provide the passphrase to connect.';
                    } else {
                        valueDisplay.textContent = '🔓 No passphrase set — SRT streams are open access';
                        valueDisplay.style.color = '#4CAF50';
                        if (helpDisplay) helpDisplay.textContent = 'SRT streams can be accessed using the URL below without authentication.';
                    }
                })
                .catch(() => {
                    const valueDisplay = document.getElementById('srt-passphrase-value');
                    if (valueDisplay) {
                        valueDisplay.textContent = '⚠️ Unable to check passphrase status';
                        valueDisplay.style.color = '#999';
                    }
                });
        }

        // Protocol Enable/Disable Toggles
        function loadProtocolStatuses() {
            fetch('/api/protocols/status')
                .then(r => r.json())
                .then(data => {
                    document.getElementById('protocol-rtsp-toggle').checked = data.rtsp;
                    document.getElementById('protocol-hls-toggle').checked = data.hls;
                    document.getElementById('protocol-srt-toggle').checked = data.srt;
                });
        }
        
        function toggleProtocol(protocol) {
            const toggle = document.getElementById(`protocol-${protocol}-toggle`);
            const isEnabled = toggle.checked;
            
            if (!confirm(`${isEnabled ? 'Enable' : 'Disable'} ${protocol.toUpperCase()}? MediaMTX will restart.`)) {
                toggle.checked = !isEnabled;
                return;
            }
            
            const statusMsg = document.createElement('div');
            statusMsg.style.cssText = 'position: fixed; top: 20px; right: 20px; background: #2196F3; color: white; padding: 15px 20px; border-radius: 6px; z-index: 10000;';
            statusMsg.textContent = `${isEnabled ? 'Enabling' : 'Disabling'} ${protocol.toUpperCase()}... Restarting MediaMTX...`;
            document.body.appendChild(statusMsg);
            
            fetch('/api/protocols/toggle', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({protocol: protocol, enabled: isEnabled})
            })
                .then(r => r.json())
                .then(data => {
                    document.body.removeChild(statusMsg);
                    if (data.success) {
                        alert(data.message + '\\n\\nMediaMTX has been restarted.');
                    } else {
                        alert('Error: ' + data.error);
                        loadProtocolStatuses();
                    }
                })
                .catch(err => {
                    document.body.removeChild(statusMsg);
                    alert('Error: ' + err);
                    loadProtocolStatuses();
                });
        }
        
        // Load toggle states on page load
        document.addEventListener('DOMContentLoaded', function() {
            // Load dashboard immediately if it's the active tab
            const dashboardTab = document.getElementById('dashboard');
            if (dashboardTab && dashboardTab.classList.contains('active')) {
                startDashboardRefresh();
            }
            
            // Stagger status checks to avoid overwhelming the backend
            setTimeout(loadPublicAccessStatus, 100);
            setTimeout(loadTestStreamViewerStatus, 300);
            setTimeout(loadSRTPassphraseStatus, 500);
            setTimeout(loadProtocolStatuses, 700);
            setTimeout(loadMediaMTXUsers, 900);
        });
        
        // === THEME / STYLING FUNCTIONS ===
        
        function updatePreview() {
            const headerColor = document.getElementById('theme-headerColor').value;
            const headerColorEnd = document.getElementById('theme-headerColorEnd').value;
            const accentColor = document.getElementById('theme-accentColor').value;
            
            // Sync text inputs with color pickers
            document.getElementById('theme-headerColor-text').value = headerColor;
            document.getElementById('theme-headerColorEnd-text').value = headerColorEnd;
            document.getElementById('theme-accentColor-text').value = accentColor;
            
            // Update preview box
            document.getElementById('preview-header').style.background = 
                `linear-gradient(135deg, ${headerColor} 0%, ${headerColorEnd} 100%)`;
            document.getElementById('preview-active-tab').style.color = accentColor;
            document.getElementById('preview-active-tab').style.borderBottom = `3px solid ${accentColor}`;
            document.getElementById('preview-section-title').style.color = accentColor;
            
            // Live-update the actual page header and accent elements
            document.querySelector('.header').style.background = 
                `linear-gradient(135deg, ${headerColor} 0%, ${headerColorEnd} 100%)`;
            
            // Update active tab color
            const activeTab = document.querySelector('.tab.active');
            if (activeTab) {
                activeTab.style.color = accentColor;
                activeTab.style.borderBottomColor = accentColor;
            }
            
            // Update section titles
            document.querySelectorAll('.section-title').forEach(el => {
                el.style.color = accentColor;
            });
        }
        
        function updateTextPreview() {
            const title = document.getElementById('theme-headerTitle').value;
            const subtitle = document.getElementById('theme-subtitle').value;
            
            // Update preview
            document.getElementById('preview-title').textContent = '🎥 ' + title;
            document.getElementById('preview-subtitle').textContent = subtitle;
            
            // Live-update actual header
            const headerH1 = document.querySelector('.header h1');
            if (headerH1) headerH1.textContent = '🎥 ' + title;
            const headerP = document.querySelector('.header p');
            if (headerP) headerP.textContent = subtitle;
        }
        
        function applyPreset(headerColor, headerColorEnd, accentColor) {
            document.getElementById('theme-headerColor').value = headerColor;
            document.getElementById('theme-headerColorEnd').value = headerColorEnd;
            document.getElementById('theme-accentColor').value = accentColor;
            updatePreview();
        }
        
        function saveTheme() {
            const theme = {
                headerColor: document.getElementById('theme-headerColor').value,
                headerColorEnd: document.getElementById('theme-headerColorEnd').value,
                accentColor: document.getElementById('theme-accentColor').value,
                headerTitle: document.getElementById('theme-headerTitle').value,
                subtitle: document.getElementById('theme-subtitle').value
            };
            
            fetch('/api/theme/settings', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify(theme)
            })
            .then(res => res.json())
            .then(data => {
                if (data.success) {
                    const statusEl = document.getElementById('theme-status');
                    statusEl.style.display = 'block';
                    statusEl.innerHTML = '<div class="alert alert-success">✅ Theme saved! Reloading...</div>';
                    // Reload to fully apply theme to all CSS
                    setTimeout(() => {
                        window.location.href = '/?tab=styling&message=Theme saved successfully&message_type=success';
                    }, 1000);
                } else {
                    const statusEl = document.getElementById('theme-status');
                    statusEl.style.display = 'block';
                    statusEl.innerHTML = '<div class="alert alert-danger">❌ Failed to save theme: ' + (data.error || 'Unknown error') + '</div>';
                }
            })
            .catch(err => {
                const statusEl = document.getElementById('theme-status');
                statusEl.style.display = 'block';
                statusEl.innerHTML = '<div class="alert alert-danger">❌ Error: ' + err.message + '</div>';
            });
        }
        
        // === LOGO FUNCTIONS ===
        
        function previewLogoUpload(input) {
            if (input.files && input.files[0]) {
                const file = input.files[0];
                // Max 500KB
                if (file.size > 512000) {
                    alert('Logo file must be under 500KB');
                    input.value = '';
                    return;
                }
                document.getElementById('logo-filename').textContent = file.name;
                document.getElementById('logo-upload-btn').disabled = false;
                
                // Show local preview
                const reader = new FileReader();
                reader.onload = function(e) {
                    const img = document.getElementById('logo-preview-img');
                    img.src = e.target.result;
                    img.style.display = 'block';
                    document.getElementById('logo-preview-placeholder').style.display = 'none';
                };
                reader.readAsDataURL(file);
            }
        }
        
        function uploadLogo() {
            const input = document.getElementById('logo-upload-input');
            if (!input.files || !input.files[0]) return;
            
            const formData = new FormData();
            formData.append('logo', input.files[0]);
            
            fetch('/api/theme/logo', {
                method: 'POST',
                body: formData
            })
            .then(res => res.json())
            .then(data => {
                if (data.success) {
                    // Update header logo immediately
                    const headerImg = document.getElementById('agency-logo-img');
                    headerImg.src = '/api/theme/logo?t=' + Date.now();
                    headerImg.style.display = 'block';
                    document.getElementById('agency-logo-placeholder').style.display = 'none';
                    document.getElementById('logo-upload-btn').disabled = true;
                    document.getElementById('logo-filename').textContent = '✅ Logo uploaded!';
                } else {
                    alert('Failed to upload logo: ' + (data.error || 'Unknown error'));
                }
            })
            .catch(err => alert('Error uploading logo: ' + err.message));
        }
        
        function removeLogo() {
            fetch('/api/theme/logo/remove', { method: 'POST' })
            .then(res => res.json())
            .then(data => {
                if (data.success) {
                    // Hide header logo
                    document.getElementById('agency-logo-img').style.display = 'none';
                    document.getElementById('agency-logo-placeholder').style.display = 'none';
                    // Reset preview
                    document.getElementById('logo-preview-img').style.display = 'none';
                    document.getElementById('logo-preview-placeholder').style.display = 'block';
                    document.getElementById('logo-filename').textContent = 'Logo removed';
                    document.getElementById('logo-upload-input').value = '';
                    document.getElementById('logo-upload-btn').disabled = true;
                }
            });
        }
        
        // Load logo into styling tab preview if it exists
        (function loadLogoPreview() {
            {% if logo_exists %}
            const previewImg = document.getElementById('logo-preview-img');
            if (previewImg) {
                previewImg.src = '/api/theme/logo';
                previewImg.style.display = 'block';
                const placeholder = document.getElementById('logo-preview-placeholder');
                if (placeholder) placeholder.style.display = 'none';
            }
            {% endif %}
        })();
        
        // === END LOGO FUNCTIONS ===
        
        // === END THEME FUNCTIONS ===
    </script>
</body>
</html>
'''

def load_config():
    """Load MediaMTX configuration - preserves comments"""
    import time
    import fcntl
    max_retries = 5
    
    for attempt in range(max_retries):
        try:
            with open(CONFIG_FILE, 'r') as f:
                # Acquire shared lock (multiple readers OK, but blocks writers)
                fcntl.flock(f.fileno(), fcntl.LOCK_SH | fcntl.LOCK_NB)
                try:
                    config = yaml.load(f)
                    
                    # Clean up any string "None" values in SRT passphrases
                    if config and 'pathDefaults' in config:
                        if config['pathDefaults'].get('srtPublishPassphrase') == 'None':
                            del config['pathDefaults']['srtPublishPassphrase']
                        if config['pathDefaults'].get('srtReadPassphrase') == 'None':
                            del config['pathDefaults']['srtReadPassphrase']
                    
                    return config
                finally:
                    # Release lock
                    fcntl.flock(f.fileno(), fcntl.LOCK_UN)
        except (IOError, OSError, BlockingIOError) as e:
            # File is locked or being written - retry
            if attempt < max_retries - 1:
                wait_time = 0.3 * (attempt + 1)  # 0.3, 0.6, 0.9, 1.2, 1.5 seconds
                time.sleep(wait_time)
            else:
                print(f"ERROR: Failed to load config after {max_retries} attempts: {e}", flush=True)
                return None
        except Exception as e:
            if attempt < max_retries - 1:
                wait_time = 0.3 * (attempt + 1)
                time.sleep(wait_time)
            else:
                import traceback
                print(f"ERROR: Failed to load config after {max_retries} attempts: {e}", flush=True)
                traceback.print_exc()
                return None

def read_yaml_field(field_name, default=None):
    """Read a single top-level field from mediamtx.yml without ruamel.yaml.
    Handles simple values like strings, yes/no, numbers, and bracket lists."""
    try:
        with open(CONFIG_FILE, 'r') as f:
            for line in f:
                if line.startswith(field_name + ':'):
                    value = line.split(':', 1)[1].strip()
                    if not value or value == '':
                        return default
                    # Strip quotes
                    if (value.startswith('"') and value.endswith('"')) or \
                       (value.startswith("'") and value.endswith("'")):
                        value = value[1:-1]
                    # Parse bracket list like [tcp] or [udp, tcp]
                    if value.startswith('[') and value.endswith(']'):
                        inner = value[1:-1].strip()
                        if not inner:
                            return []
                        return [item.strip().strip("'\"") for item in inner.split(',')]
                    return value
    except Exception as e:
        print(f"ERROR reading field {field_name}: {e}", flush=True)
    return default

def read_yaml_users():
    """Read authInternalUsers directly from YAML file without ruamel.yaml.
    Returns a list of user dicts with user, pass, ips, permissions."""
    try:
        with open(CONFIG_FILE, 'r') as f:
            lines = f.readlines()
        
        users = []
        in_auth_users = False
        current_user = None
        in_permissions = False
        current_perm = None
        
        for line in lines:
            stripped = line.strip()
            
            # Detect start of authInternalUsers section
            if stripped.startswith('authInternalUsers:'):
                in_auth_users = True
                continue
            
            if not in_auth_users:
                continue
            
            # Detect end of section - a line with no indent that isn't a comment or blank
            if stripped and not line.startswith(' ') and not line.startswith('#') and not stripped.startswith('-'):
                break
            
            # New user entry starts with "- user:"
            if stripped.startswith('- user:'):
                # Save previous user
                if current_user is not None:
                    if current_perm:
                        current_user['permissions'].append(current_perm)
                        current_perm = None
                    users.append(current_user)
                
                username = stripped.split(':', 1)[1].strip()
                # Strip quotes
                if (username.startswith("'") and username.endswith("'")) or \
                   (username.startswith('"') and username.endswith('"')):
                    username = username[1:-1]
                current_user = {'user': username, 'pass': '', 'ips': [], 'permissions': []}
                in_permissions = False
                current_perm = None
                continue
            
            if current_user is None:
                continue
            
            # Parse user properties
            if stripped.startswith('pass:') and not in_permissions:
                password = stripped.split(':', 1)[1].strip()
                if (password.startswith("'") and password.endswith("'")) or \
                   (password.startswith('"') and password.endswith('"')):
                    password = password[1:-1]
                current_user['pass'] = password
            elif stripped.startswith('ips:') and not in_permissions:
                # Parse inline list like ['127.0.0.1'] or []
                ips_str = stripped.split(':', 1)[1].strip()
                if ips_str.startswith('[') and ips_str.endswith(']'):
                    inner = ips_str[1:-1].strip()
                    if inner:
                        current_user['ips'] = [ip.strip().strip("'\"") for ip in inner.split(',')]
                    else:
                        current_user['ips'] = []
            elif stripped == 'permissions:':
                in_permissions = True
                current_perm = None
            elif in_permissions and stripped.startswith('- action:'):
                # Save previous permission if exists
                if current_perm:
                    current_user['permissions'].append(current_perm)
                action = stripped.split(':', 1)[1].strip()
                current_perm = {'action': action}
            elif in_permissions and stripped.startswith('path:') and current_perm:
                path_val = stripped.split(':', 1)[1].strip()
                current_perm['path'] = path_val
        
        # Don't forget the last user
        if current_user is not None:
            if current_perm:
                current_user['permissions'].append(current_perm)
            users.append(current_user)
        
        return users
    except Exception as e:
        print(f"ERROR reading users from YAML: {e}", flush=True)
        import traceback
        traceback.print_exc()
        return []

def save_config_sed(field, value):
    """Save a single field using sed - avoids YAML corruption"""
    try:
        # Escape special characters for sed
        value_escaped = str(value).replace('/', '\\/')
        
        # Use sed to update the field
        subprocess.run(['sed', '-i', f's/^{field}: .*/{field}: {value_escaped}/', CONFIG_FILE], check=True)
        return True
    except Exception as e:
        print(f"ERROR in save_config_sed: {e}", flush=True)
        return False

def save_config(config):
    """Save MediaMTX configuration using ruamel.yaml - FIX for user management"""
    try:
        # Create backup first
        backup_file = os.path.join(BACKUP_DIR, f'mediamtx.yml.{datetime.now().strftime("%Y%m%d_%H%M%S")}')
        subprocess.run(['cp', CONFIG_FILE, backup_file], check=True)
        
        # Write config using ruamel.yaml
        with open(CONFIG_FILE, 'w') as f:
            yaml.dump(config, f)
        
        # Add group comments (but use FIXED version that doesn't truncate)
        add_group_comments_to_yaml_FIXED()
        
        return True
    except Exception as e:
        print(f"ERROR in save_config: {e}", flush=True)
        import traceback
        traceback.print_exc()
        return False

def add_group_comments_to_yaml_FIXED():
    """Add group name comments - FIXED to not truncate file"""
    try:
        group_metadata = load_group_metadata()
        
        with open(CONFIG_FILE, 'r') as f:
            lines = f.readlines()
        
        new_lines = []
        in_auth_users = False
        
        for i, line in enumerate(lines):
            # Detect start of authInternalUsers section
            if 'authInternalUsers:' in line:
                in_auth_users = True
                new_lines.append(line)
                continue
            
            # Detect end of authInternalUsers section - FIXED LOGIC
            if in_auth_users and line.strip() and len(line) > 0:
                # End section if we hit a top-level YAML key (line starts with letter, no indentation)
                if line[0].isalpha() and not line.startswith(' ') and not line.startswith('\t'):
                    in_auth_users = False
            
            # If in auth section and this is a user line
            if in_auth_users and '- user:' in line:
                # Extract username
                username = line.split('user:')[1].strip()
                # Check if we have a group name for this user
                if username in group_metadata:
                    group_name = group_metadata[username]
                    # Check if previous line is already a comment for this group
                    if new_lines and new_lines[-1].strip().startswith('#'):
                        # Replace existing comment
                        new_lines[-1] = f"# {group_name}\n"
                    else:
                        # Add new comment
                        new_lines.append(f"# {group_name}\n")
            
            new_lines.append(line)
        
        # Write back
        with open(CONFIG_FILE, 'w') as f:
            f.writelines(new_lines)
            
    except Exception as e:
        print(f"ERROR in add_group_comments: {e}", flush=True)
        import traceback
        traceback.print_exc()

def add_group_comments_to_yaml():
    """Add group name comments above each user in YAML - removes orphaned comments"""
    try:
        # Load group names from metadata
        group_metadata = load_group_metadata()
        
        # Don't return early even if empty - we still need to clean up orphaned comments!
        if not group_metadata:
            group_metadata = {}  # Use empty dict for consistency
        
        # Read YAML as text lines
        with open(CONFIG_FILE, 'r') as f:
            lines = f.readlines()
        
        new_lines = []
        in_auth_section = False
        
        for idx, line in enumerate(lines):
            # Start of auth section
            if 'authInternalUsers:' in line:
                in_auth_section = True
                new_lines.append(line)
                continue
            
            # End of auth section - look for next section that starts with a letter (top-level key)
            # Must check it's not indented and not a comment/dash
            if in_auth_section and line and len(line) > 0 and line[0].isalpha():
                in_auth_section = False
            
            # Inside auth section - skip ALL comment lines
            if in_auth_section and line.strip().startswith('#'):
                continue  # Remove this comment entirely
            
            # User entry - add comment if user has a group
            if in_auth_section and line.strip().startswith('- user:'):
                username = line.split('user:')[1].strip()
                
                # Special case: Check if this is the internal FFmpeg 'any' user (with 127.0.0.1)
                # Look ahead to check IPs on the next few lines
                is_internal_ffmpeg = False
                if username == 'any':
                    # Look ahead up to 5 lines to find ips line
                    for i in range(1, min(6, len(lines) - idx)):
                        next_line = lines[idx + i]
                        if 'ips:' in next_line and '127.0.0.1' in next_line:
                            is_internal_ffmpeg = True
                            break
                        # Stop if we hit another user entry
                        if next_line.strip().startswith('- user:'):
                            break
                
                # Add appropriate comment
                indent = len(line) - len(line.lstrip())
                if is_internal_ffmpeg:
                    # Always label internal FFmpeg user
                    new_lines.append(' ' * indent + f'# Internal - FFmpeg\n')
                elif username in group_metadata:
                    # Use metadata for other users
                    group_name = group_metadata[username]
                    new_lines.append(' ' * indent + f'# {group_name}\n')
            
            new_lines.append(line)
        
        # Write back
        with open(CONFIG_FILE, 'w') as f:
            f.writelines(new_lines)
    
    except Exception as e:
        # Don't fail the save if comment injection fails
        pass


def get_service_status():
    """Get MediaMTX service status"""
    try:
        result = subprocess.run(['systemctl', 'is-active', SERVICE_NAME], 
                              capture_output=True, text=True)
        return {'active': result.stdout.strip() == 'active'}
    except:
        return {'active': False}

def get_backups():
    """Get list of backup files"""
    try:
        files = sorted([f for f in os.listdir(BACKUP_DIR) if f.startswith('mediamtx.yml.')], reverse=True)
        return files[:10]  # Last 10 backups
    except:
        return []

@app.route('/login', methods=['GET', 'POST'])
def login():
    """Login page"""
    import glob
    theme = load_theme()
    logo_exists = len(glob.glob(LOGO_FILE + '.*')) > 0
    
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        role = authenticate_user(username, password)
        
        if role:
            session['logged_in'] = True
            session['username'] = username
            session['role'] = role
            return redirect(url_for('index'))
        else:
            return render_template_string(LOGIN_TEMPLATE, error='Invalid username or password', first_time=False, theme=theme, logo_exists=logo_exists)
    
    # Check if this is first time (default credentials still in use)
    users = load_users()
    first_time = any(u['username'] == 'admin' and u['password'] == 'admin' for u in users)
    
    return render_template_string(LOGIN_TEMPLATE, first_time=first_time, error=None, theme=theme, logo_exists=logo_exists)

@app.route('/logout')
def logout():
    """Logout"""
    session.clear()
    return redirect(url_for('login'))

@app.route('/change_password', methods=['POST'])
@login_required
def change_password():
    """Change current user's password"""
    current_password = request.form.get('current_password')
    new_password = request.form.get('new_password')
    confirm_password = request.form.get('confirm_password')
    tab = request.form.get('current_tab', 'account')
    
    username = session.get('username')
    users = load_users()
    
    # Find current user
    current_user = next((u for u in users if u['username'] == username), None)
    if not current_user:
        return redirect(f'/?message=User not found&message_type=danger&tab={tab}')
    
    # Verify current password
    if current_password != current_user['password']:
        return redirect(f'/?message=Current password is incorrect&message_type=danger&tab={tab}')
    
    # Verify new passwords match
    if new_password != confirm_password:
        return redirect(f'/?message=New passwords do not match&message_type=danger&tab={tab}')
    
    # Verify new password is not empty
    if not new_password or len(new_password) < 4:
        return redirect(f'/?message=New password must be at least 4 characters&message_type=danger&tab={tab}')
    
    # Update password
    current_user['password'] = new_password
    save_users(users)
    
    return redirect(f'/?message=Password changed successfully&message_type=success&tab={tab}')

@app.route('/api/status')
@login_required
def api_status():
    """Get MediaMTX service status"""
    try:
        result = subprocess.run(['systemctl', 'is-active', SERVICE_NAME], capture_output=True, text=True)
        status = result.stdout.strip()
        
        if status == 'active':
            state = 'running'
            color = 'success'
        elif status == 'activating':
            state = 'starting'
            color = 'warning'
        else:
            state = 'stopped'
            color = 'danger'
        
        return jsonify({'status': state, 'color': color})
    except:
        return jsonify({'status': 'unknown', 'color': 'secondary'})

@app.route('/api/streams')
@login_required
def api_streams():
    """Get active streams from MediaMTX API"""
    try:
        import requests
        # Use 'any' user with blank password for API access
        response = requests.get('http://localhost:9997/v3/paths/list', auth=('any', ''), timeout=2)
        if response.status_code == 200:
            data = response.json()
            streams = []
            
            # Load group metadata for mapping usernames to group names
            group_metadata = load_group_metadata()
            
            # Get HLS domain from MediaMTX config (read from certificate path)
            hls_domain = None
            hls_encryption_on = False
            try:
                hls_cert = read_yaml_field('hlsServerCert', '')
                hls_encryption_val = read_yaml_field('hlsEncryption', 'no')
                hls_encryption_on = hls_encryption_val in ['yes', 'true', True]
                if hls_cert and isinstance(hls_cert, str):
                    import re
                    match = re.search(r'/([a-z0-9.-]+\.[a-z]{2,})/\1\.crt', hls_cert)
                    if match:
                        hls_domain = match.group(1)
            except:
                pass
            
            # Fallback to server IP if domain not found
            if not hls_domain:
                hls_domain = request.host.split(':')[0]
            
            # Build a set of all available path names (including live/ paths)
            available_paths = {item.get('name', '') for item in data.get('items', [])}
            
            # Load external sources metadata once (to filter pull sources from active streams)
            ext_sources = load_external_sources_metadata()
            
            for item in data.get('items', []):
                path_name = item.get('name', '')
                # Skip internal relay streams and 'all' path
                if path_name and path_name != 'all' and not path_name.startswith('live/'):
                    stream_info = {
                        'name': path_name,
                        'readers': 0,  # Will update from detail call
                        'ready': item.get('ready', False),
                        'publisher_group': None,
                        'publisher_username': None,
                        'source_type': None
                    }
                    
                    # Try to get publisher username and reader count from path details
                    try:
                        detail_response = requests.get(f'http://localhost:9997/v3/paths/get/{path_name}', timeout=1)
                        if detail_response.status_code == 200:
                            detail_data = detail_response.json()
                            
                            # Get reader count and breakdown by type
                            readers_data = detail_data.get('readers', [])
                            if isinstance(readers_data, list):
                                stream_info['readers'] = len(readers_data)
                                
                                # Count readers by type
                                reader_breakdown = {}
                                for reader in readers_data:
                                    reader_type = reader.get('type', 'unknown')
                                    # Simplify type names
                                    if reader_type == 'hlsMuxer':
                                        type_name = 'HLS'
                                    elif reader_type == 'rtspSession':
                                        type_name = 'RTSP'
                                    elif reader_type == 'rtmpConn':
                                        type_name = 'RTMP'
                                    elif reader_type == 'webRTCSession':
                                        type_name = 'WebRTC'
                                    elif reader_type == 'srtConn':
                                        type_name = 'SRT'
                                    else:
                                        type_name = reader_type.upper()
                                    
                                    reader_breakdown[type_name] = reader_breakdown.get(type_name, 0) + 1
                                
                                stream_info['reader_breakdown'] = reader_breakdown
                            else:
                                stream_info['readers'] = readers_data
                                stream_info['reader_breakdown'] = {}
                            
                            # Check for live/ path readers (subtract 1 for FFmpeg)
                            # Only query if the live/ path actually exists
                            live_path_name = f'live/{path_name}'
                            if live_path_name in available_paths:
                                try:
                                    live_response = requests.get(f'http://localhost:9997/v3/paths/get/{live_path_name}', timeout=1)
                                    if live_response.status_code == 200:
                                        live_data = live_response.json()
                                        live_readers = live_data.get('readers', [])
                                        if isinstance(live_readers, list):
                                            # Subtract 1 for internal FFmpeg, don't go below 0
                                            live_count = max(0, len(live_readers) - 1)
                                            if live_count > 0:
                                                stream_info['readers'] += live_count
                                                # Add to breakdown
                                                for reader in live_readers[:-1]:  # Skip last one (FFmpeg)
                                                    reader_type = reader.get('type', 'unknown')
                                                    if reader_type == 'rtspSession':
                                                        type_name = 'RTSP'
                                                    elif reader_type == 'hlsMuxer':
                                                        type_name = 'HLS'
                                                    elif reader_type == 'rtmpConn':
                                                        type_name = 'RTMP'
                                                    elif reader_type == 'webRTCSession':
                                                        type_name = 'WebRTC'
                                                    elif reader_type == 'srtConn':
                                                        type_name = 'SRT'
                                                    else:
                                                        type_name = reader_type.upper()
                                                    
                                                    if 'reader_breakdown' not in stream_info:
                                                        stream_info['reader_breakdown'] = {}
                                                    stream_info['reader_breakdown'][type_name] = stream_info['reader_breakdown'].get(type_name, 0) + 1
                                except:
                                    pass
                            
                            # Get source info
                            source = detail_data.get('source', {})
                            if source:
                                source_type = source.get('type', '')
                                stream_info['source_type'] = source_type
                                
                                # Try to get user (for RTSP/RTMP streams)
                                source_user = source.get('user', '')
                                if source_user:
                                    stream_info['publisher_username'] = source_user
                                    # Map to group name
                                    if source_user == 'any':
                                        stream_info['publisher_group'] = 'Localhost (FFmpeg)'
                                    else:
                                        group_name = group_metadata.get(source_user, '')
                                        if group_name:
                                            stream_info['publisher_group'] = group_name
                                        else:
                                            stream_info['publisher_group'] = 'Unnamed Group'
                                elif source_type == 'srtConn':
                                    # SRT connection - show as SRT Publisher
                                    stream_info['publisher_group'] = 'SRT Publisher'
                                    stream_info['publisher_username'] = 'srt'
                                elif source_type:
                                    # Other connection types
                                    stream_info['publisher_group'] = f'{source_type.upper()} Publisher'
                    except:
                        pass  # If we can't get details, just continue
                    
                    # Generate HLS URL - use https only if hlsEncryption is enabled
                    hls_protocol = 'https' if hls_encryption_on else 'http'
                    stream_info['hls_url'] = f"{hls_protocol}://{hls_domain}:8888/{path_name}/index.m3u8"
                    
                    # Only add streams that are ready (have an active source)
                    # External sources (pull) only show when ready (actually receiving video)
                    # Push sources show if ready OR have a publisher connected
                    if path_name in ext_sources:
                        # External source - only show when video is flowing
                        if stream_info['ready']:
                            streams.append(stream_info)
                    else:
                        # Regular push stream
                        if stream_info['ready'] or stream_info['publisher_group']:
                            streams.append(stream_info)
            
            return jsonify({'streams': streams})
        else:
            return jsonify({'streams': [], 'error': 'MediaMTX API not responding'})
    except Exception as e:
        return jsonify({'streams': [], 'error': str(e)})

@app.route('/api/webeditor/users')
@admin_required
def api_get_webeditor_users():
    """Get list of web editor users (admin only)"""
    users = load_users()
    # Don't send passwords to client
    safe_users = [{'username': u['username'], 'role': u['role']} for u in users]
    return jsonify({'users': safe_users})

@app.route('/api/webeditor/users/add', methods=['POST'])
@admin_required
def api_add_webeditor_user():
    """Add new web editor user (admin only)"""
    data = request.get_json()
    username = data.get('username', '').strip()
    password = data.get('password', '').strip()
    role = data.get('role', 'viewer')
    
    if not username or not password:
        return jsonify({'success': False, 'error': 'Username and password required'}), 400
    
    if role not in ['admin', 'viewer']:
        return jsonify({'success': False, 'error': 'Invalid role'}), 400
    
    users = load_users()
    
    # Check if username already exists
    if any(u['username'] == username for u in users):
        return jsonify({'success': False, 'error': 'Username already exists'}), 400
    
    users.append({'username': username, 'password': password, 'role': role})
    save_users(users)
    
    return jsonify({'success': True})

@app.route('/api/webeditor/users/delete', methods=['POST'])
@admin_required
def api_delete_webeditor_user():
    """Delete web editor user (admin only)"""
    data = request.get_json()
    username = data.get('username', '')
    
    if username == session.get('username'):
        return jsonify({'success': False, 'error': 'Cannot delete your own account'}), 400
    
    users = load_users()
    users = [u for u in users if u['username'] != username]
    save_users(users)
    
    return jsonify({'success': True})

@app.route('/api/mediamtx/users')
@login_required
def api_get_mediamtx_users():
    """Get list of MediaMTX authorized users (excludes localhost exemption and hidden teststream viewer)"""
    
    # Use direct YAML reader instead of ruamel.yaml to avoid parser crashes
    all_users = read_yaml_users()
    
    if not all_users:
        return jsonify({'users': []})
    
    # Load group names metadata
    group_metadata = load_group_metadata()
    
    users_list = []
    
    for user in all_users:
        username = user.get('user', '')
        ips = user.get('ips', [])
        perms = user.get('permissions', [])
        
        # Skip localhost exemption (hidden from UI)
        if username == 'any' and '127.0.0.1' in ips:
            continue
        
        # Skip hidden teststream viewer (has path: teststream)
        if username == 'any' and ips == [] and user.get('pass', '') == '':
            has_teststream_path = any(p.get('path') == 'teststream' for p in perms)
            if has_teststream_path:
                continue
        
        user_info = {
            'user': username,
            'pass': user.get('pass', ''),
            'ips': ips,
            'permissions': perms,
            'groupName': group_metadata.get(username, '')
        }
        users_list.append(user_info)
    
    return jsonify({'users': users_list})

@app.route('/api/mediamtx/users/add', methods=['POST'])
@admin_required
def api_add_mediamtx_user():
    """Add new MediaMTX authorized user with group name - uses direct YAML manipulation"""
    data = request.get_json()
    group_name = data.get('groupName', '').strip()
    username = data.get('username', '').strip()
    password = data.get('password', '').strip()
    permissions = data.get('permissions', [])
    
    if not username:
        return jsonify({'success': False, 'error': 'Username required'}), 400
    
    if not permissions:
        return jsonify({'success': False, 'error': 'At least one permission required'}), 400
    
    # Check if "Public" group already exists
    if group_name and group_name.lower() == 'public':
        group_metadata = load_group_metadata()
        for existing_user, existing_group in group_metadata.items():
            if existing_group.lower() == 'public':
                return jsonify({'success': False, 'error': 'Only one "Public" group is allowed.'}), 400
    
    # Read current config to check for duplicates
    config = load_config()
    if not config:
        return jsonify({'success': False, 'error': 'Failed to load config'}), 500
    
    if 'authInternalUsers' not in config:
        config['authInternalUsers'] = []
    
    # Check for duplicate usernames
    for user in config['authInternalUsers']:
        if user.get('user') == username:
            if username == 'any':
                existing_ips = user.get('ips', [])
                if existing_ips == []:
                    return jsonify({'success': False, 'error': 'Username already exists with no IP restriction'}), 400
            else:
                return jsonify({'success': False, 'error': 'Username already exists'}), 400
    
    # Build new user YAML text
    group_comment = f"# {group_name}\n" if group_name else ""
    user_yaml = f"""{group_comment}- user: {username}
  pass: {password if password else "''"}
  ips: []
  permissions:
"""
    for perm in permissions:
        user_yaml += f"  - action: {perm}\n"
    
    # Read file and insert before authHTTPAddress
    with open(CONFIG_FILE, 'r') as f:
        lines = f.readlines()
    
    new_lines = []
    inserted = False
    
    for line in lines:
        if not inserted and 'authHTTPAddress:' in line:
            # Insert new user before authHTTPAddress
            new_lines.append(user_yaml)
            inserted = True
        new_lines.append(line)
    
    # Write back
    with open(CONFIG_FILE, 'w') as f:
        f.writelines(new_lines)
    
    # Save group metadata
    if group_name:
        group_metadata = load_group_metadata()
        group_metadata[username] = group_name
        save_group_metadata(group_metadata)
    
    # Restart MediaMTX
    try:
        subprocess.run(['sudo', 'systemctl', 'restart', SERVICE_NAME], check=True, timeout=10)
        time.sleep(3)
    except:
        pass
    
    return jsonify({'success': True})

@app.route('/api/mediamtx/users/update', methods=['POST'])
@admin_required
def api_update_mediamtx_user():
    """Update existing MediaMTX user - smarter than delete+recreate"""
    data = request.get_json()
    old_username = data.get('oldUsername', '').strip()
    old_ips = data.get('oldIps', [])  # To identify which 'any' user we're editing
    group_name = data.get('groupName', '').strip()
    username = data.get('username', '').strip()
    password = data.get('password', '').strip()
    permissions = data.get('permissions', [])
    
    if not username:
        return jsonify({'success': False, 'error': 'Username required'}), 400
    
    # Password can be blank
    
    if not permissions:
        return jsonify({'success': False, 'error': 'At least one permission required'}), 400
    
    # Check if renaming to "Public" group (only one allowed)
    if group_name and group_name.lower() == 'public':
        group_metadata = load_group_metadata()
        # Check if any OTHER user has "Public" group
        for existing_user, existing_group in group_metadata.items():
            if existing_group.lower() == 'public' and existing_user != old_username:
                return jsonify({'success': False, 'error': 'Only one "Public" group is allowed. Please choose a different group name.'}), 400
    
    config = load_config()
    
    if 'authInternalUsers' not in config:
        return jsonify({'success': False, 'error': 'No users configured'}), 400
    
    # Find the specific user to update (match by username AND ips to handle multiple 'any' users)
    user_found = False
    for user in config['authInternalUsers']:
        if user.get('user') == old_username:
            # For 'any' users, also check IPs to find the right one
            if old_username == 'any':
                user_ips = user.get('ips', [])
                # Match the specific 'any' user by IPs
                if user_ips == old_ips:
                    # Update this user
                    user['user'] = username
                    user['pass'] = password
                    user['permissions'] = [{'action': perm} for perm in permissions]
                    user_found = True
                    break
            else:
                # For non-'any' users, just match username
                user['user'] = username
                user['pass'] = password
                user['permissions'] = [{'action': perm} for perm in permissions]
                user_found = True
                break
    
    if not user_found:
        return jsonify({'success': False, 'error': 'User not found'}), 404
    
    # Update group name in metadata
    group_metadata = load_group_metadata()
    # Remove old username from metadata if username changed
    if old_username != username and old_username in group_metadata:
        del group_metadata[old_username]
    # Set new group name
    if group_name:
        group_metadata[username] = group_name
        save_group_metadata(group_metadata)
    
    if save_config(config):
        # Restart MediaMTX to apply changes
        try:
            subprocess.run(['sudo', 'systemctl', 'restart', SERVICE_NAME], check=True, timeout=10)
            time.sleep(3)
        except:
            pass
        return jsonify({'success': True})
    else:
        return jsonify({'success': False, 'error': 'Failed to save config'}), 500
        return jsonify({'success': False, 'error': 'Failed to save config'}), 500

@app.route('/api/mediamtx/users/revoke', methods=['POST'])
@admin_required
def api_revoke_mediamtx_user():
    """Revoke/delete MediaMTX authorized user"""
    data = request.get_json()
    username = data.get('username', '')
    ips = data.get('ips', [])
    
    config = load_config()
    
    if 'authInternalUsers' not in config:
        return jsonify({'success': False, 'error': 'No users configured'}), 400
    
    # Don't allow deleting localhost exemption (the specific 'any' user with 127.0.0.1)
    if username == 'any' and ips and '127.0.0.1' in ips:
        return jsonify({'success': False, 'error': 'Cannot delete localhost exemption (required for FFmpeg)'}), 400
    
    # Remove the specific user (match by username AND ips for 'any' users)
    original_count = len(config['authInternalUsers'])
    if username == 'any':
        # For 'any' users, match by IPs to delete the right one
        config['authInternalUsers'] = [u for u in config['authInternalUsers'] 
                                        if not (u.get('user') == username and u.get('ips', []) == ips)]
    else:
        # For other users, just match username
        config['authInternalUsers'] = [u for u in config['authInternalUsers'] if u.get('user') != username]
    
    if len(config['authInternalUsers']) == original_count:
        return jsonify({'success': False, 'error': 'User not found'}), 404
    
    # Remove from group metadata
    group_metadata = load_group_metadata()
    if username in group_metadata:
        del group_metadata[username]
        save_group_metadata(group_metadata)
    
    if save_config(config):
        # Restart MediaMTX to apply changes
        try:
            subprocess.run(['sudo', 'systemctl', 'restart', SERVICE_NAME], check=True, timeout=10)
            time.sleep(3)
        except:
            pass
        return jsonify({'success': True})
    else:
        return jsonify({'success': False, 'error': 'Failed to save config'}), 500

@app.route('/')
@login_required
def index():
    import time
    
    # Retry loading config - can fail briefly after MediaMTX restart
    config = None
    for attempt in range(5):
        try:
            config = load_config()
            if config is not None:
                break
        except Exception:
            pass
        time.sleep(0.5)
    
    if config is None:
        return "Error loading configuration file", 500
    
    # Get YAML content for advanced editor
    with open(CONFIG_FILE, 'r') as f:
        yaml_content = f.read()
    
    # Check if agency logo exists
    import glob
    logo_matches = glob.glob(LOGO_FILE + '.*')
    logo_exists = len(logo_matches) > 0
    
    # Determine RTSP transport mode for template dropdown
    transports = config.get('rtspTransports', ['tcp'])
    if isinstance(transports, list):
        if len(transports) >= 3:
            rtsp_transport_mode = 'all'
        elif len(transports) >= 2 and 'udp' in transports:
            rtsp_transport_mode = 'udp_tcp'
        elif 'tcp' in transports:
            rtsp_transport_mode = 'tcp'
        else:
            rtsp_transport_mode = 'tcp'
    else:
        rtsp_transport_mode = 'tcp'
    
    return render_template_string(
        HTML_TEMPLATE,
        config=config,
        yaml_content=yaml_content,
        service_status=get_service_status(),
        backups=get_backups(),
        message=request.args.get('message'),
        message_type=request.args.get('message_type', 'info'),
        username=session.get('username', 'admin'),
        tab=request.args.get('tab', 'dashboard'),
        role=session.get('role', 'admin'),
        theme=load_theme(),
        logo_exists=logo_exists,
        rtsp_transport_mode=rtsp_transport_mode
    )

@app.route('/save_basic', methods=['POST'])
@admin_required
def save_basic():
    tab = request.form.get('current_tab', 'basic')
    
    try:
        # Create backup first
        backup_file = os.path.join(BACKUP_DIR, f'mediamtx.yml.{datetime.now().strftime("%Y%m%d_%H%M%S")}')
        subprocess.run(['cp', CONFIG_FILE, backup_file], check=True)
        
        # Get form values
        log_level = request.form.get('logLevel')
        read_timeout = request.form.get('readTimeout')
        write_timeout = request.form.get('writeTimeout')
        
        # Use sed to update values directly (avoid ruamel.yaml corruption)
        subprocess.run(['sed', '-i', f's/^logLevel: .*/logLevel: {log_level}/', CONFIG_FILE], check=True)
        subprocess.run(['sed', '-i', f's/^readTimeout: .*/readTimeout: {read_timeout}/', CONFIG_FILE], check=True)
        subprocess.run(['sed', '-i', f's/^writeTimeout: .*/writeTimeout: {write_timeout}/', CONFIG_FILE], check=True)
        
        return redirect(f'/?message=Basic settings saved successfully&message_type=success&tab={tab}')
    except Exception as e:
        print(f"ERROR saving basic settings: {e}", flush=True)
        return redirect(f'/?message=Failed to save settings&message_type=danger&tab={tab}')

@app.route('/save_protocols', methods=['POST'])
@admin_required
def save_protocols():
    tab = request.form.get('current_tab', 'protocols')
    
    try:
        # Create backup first
        backup_file = os.path.join(BACKUP_DIR, f'mediamtx.yml.{datetime.now().strftime("%Y%m%d_%H%M%S")}')
        subprocess.run(['cp', CONFIG_FILE, backup_file], check=True)
        
        # Get form values
        rtsp_port = request.form.get('rtspAddress')
        rtsp_transports = request.form.get('rtspTransports')
        rtsp_encryption = request.form.get('rtspEncryption')
        rtsps_port = request.form.get('rtspsAddress')
        rtmp_port = request.form.get('rtmpAddress')
        rtmp_encryption = request.form.get('rtmpEncryption')  
        hls_port = request.form.get('hlsAddress')
        srt_port = request.form.get('srtAddress')
        srt_publish = request.form.get('srtPublishPassphrase', '').strip()
        srt_read = request.form.get('srtReadPassphrase', '').strip()
        
        # Validate RTSP encryption
        if rtsp_encryption in ['optional', 'strict']:
            # Check if certificates exist
            config = load_config()
            cert_key = config.get('rtspServerKey', '').strip()
            cert_file = config.get('rtspServerCert', '').strip()
            
            if not cert_key or not cert_file:
                return redirect(f'/?message=Cannot enable RTSP encryption: Certificate paths not configured!&message_type=danger&tab={tab}')
            
            if not os.path.exists(cert_key) or not os.path.exists(cert_file):
                return redirect(f'/?message=Cannot enable RTSP encryption: Certificate files not found!&message_type=danger&tab={tab}')
        
        # Validate SRT passphrases
        if srt_publish and (len(srt_publish) < 10 or len(srt_publish) > 79):
            return redirect(f'/?message=SRT Publish Passphrase must be 10-79 characters&message_type=danger&tab={tab}')
        
        if srt_read and (len(srt_read) < 10 or len(srt_read) > 79):
            return redirect(f'/?message=SRT Read Passphrase must be 10-79 characters&message_type=danger&tab={tab}')
        
        # Use sed to update protocol settings directly - only write values that exist in the form
        if rtsp_port:
            subprocess.run(['sed', '-i', f's/^rtspAddress: .*/rtspAddress: :{rtsp_port}/', CONFIG_FILE], check=True)
        # RTSP transport protocols (list format)
        if rtsp_transports:
            # Convert comma-separated to YAML list format: [tcp] or [udp, tcp] or [udp, multicast, tcp]
            transport_list = '[' + ', '.join(rtsp_transports.split(',')) + ']'
            result = subprocess.run(['grep', '-c', '^rtspTransports:', CONFIG_FILE], capture_output=True, text=True)
            if result.stdout.strip() != '0':
                subprocess.run(['sed', '-i', f's/^rtspTransports: .*/rtspTransports: {transport_list}/', CONFIG_FILE], check=True)
            else:
                # Insert after rtspAddress line
                subprocess.run(['sed', '-i', f'/^rtspAddress:/a rtspTransports: {transport_list}', CONFIG_FILE], check=True)
        # RTSP/RTMP encryption need quotes - they take string values ("no", "optional", "strict")
        if rtsp_encryption and rtsp_encryption in ['no', 'optional', 'strict']:
            subprocess.run(['sed', '-i', f's/^rtspEncryption: .*/rtspEncryption: "{rtsp_encryption}"/', CONFIG_FILE], check=True)
        if rtsps_port:
            subprocess.run(['sed', '-i', f's/^rtspsAddress: .*/rtspsAddress: :{rtsps_port}/', CONFIG_FILE], check=True)
        if rtmp_port:
            subprocess.run(['sed', '-i', f's/^rtmpAddress: .*/rtmpAddress: :{rtmp_port}/', CONFIG_FILE], check=True)
        if rtmp_encryption and rtmp_encryption in ['no', 'optional', 'strict']:
            subprocess.run(['sed', '-i', f's/^rtmpEncryption: .*/rtmpEncryption: "{rtmp_encryption}"/', CONFIG_FILE], check=True)
        if hls_port:
            subprocess.run(['sed', '-i', f's/^hlsAddress: .*/hlsAddress: :{hls_port}/', CONFIG_FILE], check=True)
        if srt_port:
            subprocess.run(['sed', '-i', f's/^srtAddress: .*/srtAddress: :{srt_port}/', CONFIG_FILE], check=True)
        
        # Handle SRT passphrases - use sed to update, insert if line doesn't exist
        if srt_publish:
            # Try to replace existing line
            result = subprocess.run(['grep', '-q', '^  srtPublishPassphrase:', CONFIG_FILE])
            if result.returncode == 0:
                subprocess.run(['sed', '-i', f's/^  srtPublishPassphrase:.*/  srtPublishPassphrase: {srt_publish}/', CONFIG_FILE], check=True)
            else:
                subprocess.run(['sed', '-i', f'/^  overridePublisher:/a\\  srtPublishPassphrase: {srt_publish}', CONFIG_FILE], check=True)
        else:
            # Clear value but keep the line
            result = subprocess.run(['grep', '-q', '^  srtPublishPassphrase:', CONFIG_FILE])
            if result.returncode == 0:
                subprocess.run(['sed', '-i', 's/^  srtPublishPassphrase:.*/  srtPublishPassphrase:/', CONFIG_FILE], check=True)
        
        if srt_read:
            result = subprocess.run(['grep', '-q', '^  srtReadPassphrase:', CONFIG_FILE])
            if result.returncode == 0:
                subprocess.run(['sed', '-i', f's/^  srtReadPassphrase:.*/  srtReadPassphrase: {srt_read}/', CONFIG_FILE], check=True)
            else:
                subprocess.run(['sed', '-i', f'/^  maxReaders:/a\\  srtReadPassphrase: {srt_read}', CONFIG_FILE], check=True)
        else:
            result = subprocess.run(['grep', '-q', '^  srtReadPassphrase:', CONFIG_FILE])
            if result.returncode == 0:
                subprocess.run(['sed', '-i', 's/^  srtReadPassphrase:.*/  srtReadPassphrase:/', CONFIG_FILE], check=True)
        
        # Restart MediaMTX
        subprocess.run(['sudo', 'systemctl', 'restart', SERVICE_NAME], check=True)
        time.sleep(3)
        return redirect(f'/?message=Protocol settings saved and MediaMTX restarted successfully!&message_type=success&tab={tab}')
        
    except Exception as e:
        print(f"ERROR saving protocols: {e}", flush=True)
        return redirect(f'/?message=Failed to save settings: {str(e)}&message_type=danger&tab={tab}')

@app.route('/get_yaml')
@login_required
def get_yaml():
    """Get current YAML content"""
    try:
        with open(CONFIG_FILE, 'r') as f:
            return f.read()
    except Exception as e:
        return f"Error reading YAML: {str(e)}", 500

@app.route('/save_yaml', methods=['POST'])
@admin_required
def save_yaml():
    yaml_content = request.form.get('yaml_content')
    tab = request.form.get('current_tab', 'advanced')
    
    try:
        # Validate YAML
        from io import StringIO
        yaml.load(StringIO(yaml_content))
        
        # Create backup
        backup_file = os.path.join(BACKUP_DIR, f'mediamtx.yml.{datetime.now().strftime("%Y%m%d_%H%M%S")}')
        subprocess.run(['cp', CONFIG_FILE, backup_file], check=True)
        
        # Save new content (preserves all comments and formatting)
        with open(CONFIG_FILE, 'w') as f:
            f.write(yaml_content)
        
        return redirect(f'/?message=YAML saved successfully&message_type=success&tab={tab}')
    except Exception as e:
        return redirect(f'/?message=Invalid YAML syntax: {str(e)}&message_type=danger&tab={tab}')

@app.route('/validate_yaml', methods=['POST'])
@login_required
def validate_yaml():
    yaml_content = request.form.get('yaml_content')
    
    try:
        from io import StringIO
        yaml.load(StringIO(yaml_content))
        return redirect('/?message=YAML syntax is valid ✓&message_type=success&tab=advanced')
    except Exception as e:
        return redirect(f'/?message=Invalid YAML syntax: {str(e)}&message_type=danger&tab=advanced')

@app.route('/service/<action>', methods=['POST'])
@admin_required
def service_control(action):
    tab = request.form.get('current_tab', 'service')
    try:
        if action in ['start', 'stop', 'restart']:
            subprocess.run(['systemctl', action, SERVICE_NAME], check=True)
            action_past = 'stopped' if action == 'stop' else (action + 'ed')
            return redirect(f'/?message=Service {action_past} successfully&message_type=success&tab={tab}')
        else:
            return redirect(f'/?message=Invalid action&message_type=danger&tab={tab}')
    except Exception as e:
        return redirect(f'/?message=Failed to {action} service: {str(e)}&message_type=danger&tab={tab}')

@app.route('/backup', methods=['POST'])
@admin_required
def create_backup():
    tab = request.form.get('current_tab', 'service')
    try:
        backup_file = os.path.join(BACKUP_DIR, f'mediamtx.yml.{datetime.now().strftime("%Y%m%d_%H%M%S")}')
        subprocess.run(['cp', CONFIG_FILE, backup_file], check=True)
        return redirect(f'/?message=Backup created successfully&message_type=success&tab={tab}')
    except Exception as e:
        return redirect(f'/?message=Failed to create backup: {str(e)}&message_type=danger&tab={tab}')

@app.route('/restore/<backup_name>', methods=['POST'])
@admin_required
def restore_backup(backup_name):
    tab = request.form.get('current_tab', 'service')
    try:
        backup_file = os.path.join(BACKUP_DIR, backup_name)
        if not os.path.exists(backup_file):
            return redirect(f'/?message=Backup not found&message_type=danger&tab={tab}')
        
        # Create a backup of current config before restoring
        current_backup = os.path.join(BACKUP_DIR, f'mediamtx.yml.pre_restore_{datetime.now().strftime("%Y%m%d_%H%M%S")}')
        subprocess.run(['cp', CONFIG_FILE, current_backup], check=True)
        
        # Restore
        subprocess.run(['cp', backup_file, CONFIG_FILE], check=True)
        
        # Restart service
        subprocess.run(['sudo', 'systemctl', 'restart', SERVICE_NAME], check=True)
        
        return redirect(f'/?message=Backup restored and service restarted&message_type=success&tab={tab}')
    except Exception as e:
        return redirect(f'/?message=Failed to restore backup: {str(e)}&message_type=danger')

@app.route('/stream_logs')
@login_required
def stream_logs():
    """Stream MediaMTX logs in real-time using Server-Sent Events"""
    def generate():
        # Start journalctl process
        process = subprocess.Popen(
            ['journalctl', '-u', SERVICE_NAME, '-f', '-n', '50'],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
            bufsize=1
        )
        
        try:
            for line in iter(process.stdout.readline, ''):
                if line:
                    # Send log line as Server-Sent Event
                    yield f"data: {line.strip()}\n\n"
        finally:
            process.terminate()
            process.wait()
    
    return app.response_class(generate(), mimetype='text/event-stream')


@app.route('/api/yaml/content')
@login_required
def api_yaml_content():
    """Get current YAML content"""
    try:
        with open(CONFIG_FILE, 'r') as f:
            return f.read(), 200, {'Content-Type': 'text/plain'}
    except Exception as e:
        return str(e), 500

# Test video directory
TEST_VIDEO_DIR = '/opt/mediamtx-webeditor/test_videos'
if not os.path.exists(TEST_VIDEO_DIR):
    os.makedirs(TEST_VIDEO_DIR)

@app.route('/api/test/upload', methods=['POST'])
@login_required
def upload_test_video():
    """Upload test video"""
    if 'test_file' not in request.files:
        return jsonify({'success': False, 'error': 'No file'}), 400
    file = request.files['test_file']
    if file.filename == '':
        return jsonify({'success': False, 'error': 'No file selected'}), 400
    if not file.filename.endswith('.ts'):
        return jsonify({'success': False, 'error': 'Only .ts files'}), 400
    filename = file.filename
    filepath = os.path.join(TEST_VIDEO_DIR, filename)
    try:
        file.save(filepath)
        return jsonify({'success': True, 'filename': filename})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/test/files')
@login_required
def list_test_files():
    """List test files"""
    try:
        files = []
        if os.path.exists(TEST_VIDEO_DIR):
            for filename in os.listdir(TEST_VIDEO_DIR):
                if filename.endswith('.ts'):
                    filepath = os.path.join(TEST_VIDEO_DIR, filename)
                    size = os.path.getsize(filepath)
                    files.append({'name': filename, 'size': size, 'size_mb': round(size / (1024 * 1024), 2)})
        # Sort with truck_60.ts always first
        files.sort(key=lambda f: (0 if f['name'] == 'truck_60.ts' else 1, f['name']))
        return jsonify({'files': files})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/test/delete/<filename>', methods=['POST'])
@login_required
def delete_test_file(filename):
    """Delete test file"""
    try:
        # Protect truck_60.ts - required for upgrade verification tests
        if filename == 'truck_60.ts':
            return jsonify({'success': False, 'error': 'truck_60.ts cannot be deleted — it is required for MediaMTX upgrade verification'}), 400
        
        filepath = os.path.join(TEST_VIDEO_DIR, filename)
        if os.path.exists(filepath) and filename.endswith('.ts'):
            os.remove(filepath)
            return jsonify({'success': True})
        return jsonify({'success': False, 'error': 'Not found'}), 404
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/test/optimize/<filename>', methods=['POST'])
@login_required
def optimize_test_file(filename):
    """Optimize test file with FFmpeg for better compatibility"""
    try:
        input_path = os.path.join(TEST_VIDEO_DIR, filename)
        if not os.path.exists(input_path) or not filename.endswith('.ts'):
            return jsonify({'success': False, 'error': 'File not found'}), 404
        
        # Create output filename
        output_filename = filename.replace('.ts', '_optimized.ts')
        output_path = os.path.join(TEST_VIDEO_DIR, output_filename)
        
        # Check if optimized version already exists
        if os.path.exists(output_path):
            return jsonify({'success': False, 'error': 'Optimized version already exists'}), 400
        
        # Run FFmpeg optimization
        # Re-encode to H.264/AAC for maximum compatibility
        # Preserve all streams including KLV metadata from drone footage
        # Fix timestamp issues that cause freezing on loop
        cmd = [
            'ffmpeg', '-i', input_path,
            '-map', '0',                    # Map all streams (video, audio, data/KLV)
            '-c:v', 'libx264',              # H.264 video codec
            '-preset', 'fast',              # Encoding speed
            '-crf', '23',                   # Quality (lower = better, 23 is good)
            '-g', '30',                     # Keyframe every 30 frames (1 sec at 30fps)
            '-c:a', 'aac',                  # AAC audio codec
            '-b:a', '128k',                 # Audio bitrate
            '-c:d', 'copy',                 # Copy data streams (KLV metadata) without re-encoding
            '-avoid_negative_ts', 'make_zero',  # Fix negative timestamps
            '-vsync', 'cfr',                # Constant frame rate (fixes sync issues)
            '-max_muxing_queue_size', '1024',   # Prevent queue overruns
            '-fflags', '+genpts',           # Generate presentation timestamps
            '-f', 'mpegts',                 # MPEG-TS format
            '-y',                           # Overwrite output
            output_path
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
        
        if result.returncode == 0 and os.path.exists(output_path):
            return jsonify({'success': True, 'filename': output_filename})
        else:
            error_msg = result.stderr if result.stderr else 'FFmpeg failed'
            return jsonify({'success': False, 'error': error_msg}), 500
            
    except subprocess.TimeoutExpired:
        return jsonify({'success': False, 'error': 'Optimization timed out (>15 minutes)'}), 500
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

# Global variable to track streaming process
test_stream_process = None
test_stream_filename = None

@app.route('/api/test/stream/start/<filename>', methods=['POST'])
@login_required
def start_test_stream(filename):
    """Start streaming test file"""
    global test_stream_process, test_stream_filename
    try:
        # Stop existing stream if any
        if test_stream_process:
            test_stream_process.terminate()
            try:
                test_stream_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                test_stream_process.kill()
                test_stream_process.wait()
            test_stream_process = None
        
        filepath = os.path.join(TEST_VIDEO_DIR, filename)
        if not os.path.exists(filepath):
            return jsonify({'success': False, 'error': 'File not found'}), 404
        
        # Read SRT passphrase from config (from pathDefaults)
        config = load_config()
        srt_passphrase = ''
        if config and 'pathDefaults' in config:
            srt_passphrase = config['pathDefaults'].get('srtPublishPassphrase', '') or ''
        
        # Build SRT URL with passphrase
        srt_url = 'srt://localhost:8890?streamid=publish:teststream'
        if srt_passphrase:
            srt_url += f'&passphrase={srt_passphrase}'
        
        # Start FFmpeg streaming via SRT
        # Use stream copy for minimal CPU usage
        # -map 0 ensures ALL streams are copied (video, audio, AND KLV data)
        cmd = [
            'ffmpeg',
            '-re',
            '-stream_loop', '-1',
            '-i', filepath,
            '-map', '0',
            '-c', 'copy',
            '-mpegts_flags', 'system_b',
            '-f', 'mpegts',
            srt_url
        ]
        
        # Don't capture stdout/stderr - let FFmpeg output go to system logs
        # Capturing causes buffer overflow on long-running streams
        test_stream_process = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        test_stream_filename = filename
        
        return jsonify({'success': True, 'filename': filename})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/test/stream/stop', methods=['POST'])
@login_required
def stop_test_stream():
    """Stop streaming test file"""
    global test_stream_process, test_stream_filename
    try:
        if test_stream_process:
            test_stream_process.terminate()
            try:
                test_stream_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                # Force kill if terminate didn't work
                test_stream_process.kill()
                test_stream_process.wait()
            test_stream_process = None
            test_stream_filename = None
            return jsonify({'success': True})
        return jsonify({'success': False, 'error': 'No stream running'}), 400
    except Exception as e:
        # Clean up process reference even on error
        test_stream_process = None
        test_stream_filename = None
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/test/stream/status')
@login_required
def get_test_stream_status():
    """Get current streaming status"""
    global test_stream_process, test_stream_filename
    if test_stream_process and test_stream_process.poll() is None:
        return jsonify({'streaming': True, 'filename': test_stream_filename})
    else:
        test_stream_process = None
        test_stream_filename = None
        return jsonify({'streaming': False, 'filename': None})

@app.route('/api/stream-urls')
@login_required
def get_stream_urls():
    """Get stream URLs for test streams"""
    # Get streaming domain and protocol from MediaMTX config
    stream_info = get_streaming_domain()
    
    # Use domain from cert if available, otherwise use request host (IP)
    domain = stream_info['domain'] if stream_info['domain'] else request.host.split(':')[0]
    protocol = stream_info['protocol']
    
    urls = {
        'rtsp': f'rtsp://{domain}:8554/teststream',
        'srt': f'srt://{domain}:8890?streamid=read:teststream',
        'hls': f'{protocol}://{domain}:8888/teststream/index.m3u8'
    }
    
    return jsonify(urls)


@app.route('/api/public-access/status')
@login_required
def get_public_access_status():
    """Check if PUBLIC access is enabled - reads directly from YAML file"""
    try:
        with open(CONFIG_FILE, 'r') as f:
            content = f.read()
        
        # Look for the PUBLIC comment marker followed by user: any
        lines = content.split('\n')
        for i, line in enumerate(lines):
            if '# PUBLIC' in line:
                # Check next lines for user: any with no path restrictions
                for j in range(i + 1, min(i + 10, len(lines))):
                    if 'user: any' in lines[j]:
                        # Found PUBLIC user block
                        return jsonify({'enabled': True})
                    if lines[j].strip() and not lines[j].startswith(' ') and not lines[j].startswith('-') and not lines[j].startswith('#'):
                        break
        
        return jsonify({'enabled': False})
    except Exception as e:
        print(f"ERROR in get_public_access_status: {e}", flush=True)
        return jsonify({'enabled': False})
@app.route('/api/public-access/toggle', methods=['POST'])
@login_required
def toggle_public_access():
    """Toggle PUBLIC access on/off - uses direct file manipulation (no save_config)"""
    try:
        # Read YAML file directly to check current state
        with open(CONFIG_FILE, 'r') as f:
            yaml_content = f.read()
        
        # Check if PUBLIC user exists (any user with no path restrictions)
        public_exists = False
        lines = yaml_content.split('\n')
        in_public_user = False
        
        for i, line in enumerate(lines):
            if '# PUBLIC' in line:
                # Check next few lines for the any user
                if i + 1 < len(lines) and 'user: any' in lines[i + 1]:
                    # Check if this any user has no path restrictions
                    has_path = False
                    for j in range(i + 1, min(i + 10, len(lines))):
                        if 'path:' in lines[j]:
                            has_path = True
                            break
                        if lines[j].strip() and lines[j][0] not in [' ', '\t', '-', '#']:
                            break
                    
                    if not has_path:
                        public_exists = True
                        break
        
        if public_exists:
            # DISABLE: Remove PUBLIC user section using sed
            # This is complex, so we'll use Python to rewrite the file
            with open(CONFIG_FILE, 'r') as f:
                lines = f.readlines()
            
            new_lines = []
            skip_until_next_user = False
            found_public = False
            
            for i, line in enumerate(lines):
                if '# PUBLIC' in line and not found_public:
                    # Start skipping from PUBLIC comment
                    skip_until_next_user = True
                    found_public = True
                    continue
                
                if skip_until_next_user:
                    # Skip until we hit next comment or top-level key
                    if line.strip() and line[0] == '#' and '# PUBLIC' not in line:
                        # Hit another comment, stop skipping
                        skip_until_next_user = False
                        new_lines.append(line)
                    elif line.strip() and line[0].isalpha():
                        # Hit top-level key, stop skipping
                        skip_until_next_user = False
                        new_lines.append(line)
                    # Otherwise keep skipping
                else:
                    new_lines.append(line)
            
            # Write back
            with open(CONFIG_FILE, 'w') as f:
                f.writelines(new_lines)
            
            # Remove from group metadata
            group_metadata = load_group_metadata()
            if 'any' in group_metadata:
                del group_metadata['any']
                save_group_metadata(group_metadata)
            
            subprocess.run(['sudo', 'systemctl', 'restart', SERVICE_NAME], check=True, timeout=10)
            return jsonify({'success': True, 'enabled': False, 'message': 'Public access disabled'})
            
        else:
            # ENABLE: Add PUBLIC user section
            # Find the end of authInternalUsers section
            with open(CONFIG_FILE, 'r') as f:
                lines = f.readlines()
            
            new_lines = []
            inserted = False
            
            for i, line in enumerate(lines):
                new_lines.append(line)
                
                # Find last user before authHTTPAddress
                if not inserted and 'authHTTPAddress:' in line:
                    # Insert PUBLIC user before authHTTPAddress
                    public_user = """# PUBLIC
- user: any
  pass: ''
  ips: []
  permissions:
  - action: read
  - action: publish
  - action: playback
"""
                    new_lines.insert(-1, public_user)
                    inserted = True
            
            # Write back
            with open(CONFIG_FILE, 'w') as f:
                f.writelines(new_lines)
            
            # Save to group metadata
            group_metadata = load_group_metadata()
            group_metadata['any'] = 'PUBLIC'
            save_group_metadata(group_metadata)
            
            subprocess.run(['sudo', 'systemctl', 'restart', SERVICE_NAME], check=True, timeout=10)
            return jsonify({'success': True, 'enabled': True, 'message': 'Public access enabled'})
            
    except Exception as e:
        print(f"ERROR in toggle_public_access: {e}", flush=True)
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/teststream-viewer/status')
@login_required
def get_teststream_viewer_status():
    """Check if teststream viewer is enabled - reads directly from YAML file"""
    try:
        with open(CONFIG_FILE, 'r') as f:
            content = f.read()
        
        # Look for the teststream public viewer block
        # Pattern: user: any with pass: '' and path: teststream
        lines = content.split('\n')
        for i, line in enumerate(lines):
            if 'path: teststream' in line:
                # Look backwards for user: any with pass: ''
                for j in range(max(0, i - 10), i):
                    if "user: any" in lines[j]:
                        # Check for empty pass
                        for k in range(j, i):
                            if "pass: ''" in lines[k]:
                                return jsonify({'enabled': True})
        
        return jsonify({'enabled': False})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/teststream-viewer/toggle', methods=['POST'])
@login_required
def toggle_teststream_viewer():
    """Toggle teststream viewer on/off"""
    try:
        config = load_config()
        
        # Handle failed config load
        if config is None:
            return jsonify({'success': False, 'error': 'Failed to load config, try again'}), 500
        
        users = config.get('authInternalUsers', [])
        
        # Check current state
        viewer_exists = False
        for user in users:
            if (user.get('user') == 'any' and 
                user.get('pass', '') == '' and 
                user.get('ips', []) == []):
                perms = user.get('permissions', [])
                for perm in perms:
                    if perm.get('path') == 'teststream':
                        viewer_exists = True
                        break
        
        if viewer_exists:
            # Remove teststream viewer
            if 'authInternalUsers' not in config:
                return jsonify({'success': False, 'error': 'No users'}), 400
            
            # Remove the any user with path: teststream
            config['authInternalUsers'] = [u for u in config['authInternalUsers'] 
                if not (u.get('user') == 'any' and 
                        u.get('pass', '') == '' and 
                        u.get('ips', []) == [] and
                        any(p.get('path') == 'teststream' for p in u.get('permissions', [])))]
            
            save_config(config)
            subprocess.run(['sudo', 'systemctl', 'restart', SERVICE_NAME], check=True, timeout=10)
            
            return jsonify({'success': True, 'enabled': False, 'message': 'Test stream viewer disabled'})
        else:
            # Add teststream viewer (hidden from UI)
            new_user = {
                'user': 'any',
                'pass': '',
                'ips': [],
                'permissions': [
                    {'action': 'read', 'path': 'teststream'}
                ]
            }
            
            if 'authInternalUsers' not in config:
                config['authInternalUsers'] = []
            
            config['authInternalUsers'].append(new_user)
            
            # Don't add to group_names.json - keep it hidden!
            
            save_config(config)
            subprocess.run(['sudo', 'systemctl', 'restart', SERVICE_NAME], check=True, timeout=10)
            
            return jsonify({'success': True, 'enabled': True, 'message': 'Test stream viewer enabled'})
            
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/hlsviewer-credential')
@login_required
def api_hlsviewer_credential():
    """Get hlsviewer credential for embedded HLS playback"""
    credential = get_hlsviewer_credential()
    if credential:
        return jsonify(credential)
    else:
        return jsonify({'error': 'hlsviewer credential not found'}), 404

@app.route('/api/srt-passphrase/status')
@login_required
def get_srt_passphrase_status():
    """Check if SRT passphrase is set - reads directly from YAML file"""
    try:
        publishPassphrase = ''
        readPassphrase = ''
        
        with open(CONFIG_FILE, 'r') as f:
            for line in f:
                stripped = line.strip()
                if stripped.startswith('srtPublishPassphrase:'):
                    val = stripped.split(':', 1)[1].strip()
                    if val and val != '""' and val != "''":
                        publishPassphrase = val
                elif stripped.startswith('srtReadPassphrase:'):
                    val = stripped.split(':', 1)[1].strip()
                    if val and val != '""' and val != "''":
                        readPassphrase = val
        
        return jsonify({
            'enabled': False,
            'publishPassphrase': publishPassphrase,
            'readPassphrase': readPassphrase
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/srt-passphrase/toggle', methods=['POST'])
@login_required
def toggle_srt_passphrase():
    """Toggle SRT passphrase on/off for testing"""
    import time
    try:
        data = request.get_json()
        enabled = data.get('enabled', False)
        
        print(f"DEBUG: SRT toggle - enabled={enabled}", flush=True)
        
        # Load config directly with retries
        config = None
        for attempt in range(5):
            try:
                config = load_config()
                if config is not None:
                    break
                print(f"DEBUG: Attempt {attempt+1}/5 - config is None, waiting...", flush=True)
                time.sleep(0.5)
            except Exception as e:
                print(f"DEBUG: Attempt {attempt+1}/5 - exception: {e}", flush=True)
                if attempt < 4:
                    time.sleep(0.5)
                else:
                    raise
        
        if config is None:
            return jsonify({'success': False, 'error': 'Failed to load config after retries'}), 500
        
        if 'pathDefaults' not in config:
            config['pathDefaults'] = {}
        
        print(f"DEBUG: pathDefaults before: {config.get('pathDefaults', {})}", flush=True)
        
        if enabled:
            # TURNING ON = DISABLE passphrases for testing
            # Backup current passphrases
            pub = config.get('pathDefaults', {}).get('srtPublishPassphrase', '')
            read = config.get('pathDefaults', {}).get('srtReadPassphrase', '')
            
            if pub or read:
                save_srt_passphrase_backup(pub, read)
                print(f"DEBUG: Backed up passphrases - Publish: {pub}, Read: {read}", flush=True)
            
            # Remove passphrases from config
            config['pathDefaults'].pop('srtPublishPassphrase', None)
            config['pathDefaults'].pop('srtReadPassphrase', None)
            message = 'SRT passphrases disabled for testing (backed up)'
        else:
            # TURNING OFF = RESTORE passphrases
            backup = load_srt_passphrase_backup()
            
            if backup:
                # Restore from backup
                if backup.get('publishPassphrase'):
                    config['pathDefaults']['srtPublishPassphrase'] = backup['publishPassphrase']
                if backup.get('readPassphrase'):
                    config['pathDefaults']['srtReadPassphrase'] = backup['readPassphrase']
                
                print(f"DEBUG: Restored passphrases from backup", flush=True)
                clear_srt_passphrase_backup()
                message = 'SRT passphrases restored'
            else:
                message = 'No passphrases to restore'
        
        print(f"DEBUG: pathDefaults after: {config.get('pathDefaults', {})}", flush=True)
        
        if not save_config(config):
            return jsonify({'success': False, 'error': 'Failed to save config'}), 500
            
        subprocess.run(['sudo', 'systemctl', 'restart', SERVICE_NAME], check=True, timeout=10)
        
        return jsonify({'success': True, 'enabled': enabled, 'message': message})
            
    except Exception as e:
        print(f"ERROR in toggle_srt_passphrase: {e}", flush=True)
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/protocols/status')
@login_required
def get_protocols_status():
    """Get enable/disable status for all protocols"""
    try:
        return jsonify({
            'rtsp': read_yaml_field('rtsp', 'yes') == 'yes',
            'rtmp': read_yaml_field('rtmp', 'yes') == 'yes',
            'hls': read_yaml_field('hls', 'yes') == 'yes',
            'webrtc': read_yaml_field('webrtc', 'yes') == 'yes',
            'srt': read_yaml_field('srt', 'yes') == 'yes'
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/protocols/toggle', methods=['POST'])
@login_required
def toggle_protocol():
    """Toggle protocol on/off"""
    try:
        data = request.get_json()
        protocol = data.get('protocol', '')
        enabled = data.get('enabled', False)
        
        if protocol not in ['rtsp', 'rtmp', 'hls', 'webrtc', 'srt']:
            return jsonify({'success': False, 'error': 'Invalid protocol'}), 400
        
        value = 'yes' if enabled else 'no'
        subprocess.run(['sed', '-i', f's/^{protocol}: .*/{protocol}: {value}/', CONFIG_FILE], check=True)
        subprocess.run(['sudo', 'systemctl', 'restart', SERVICE_NAME], check=True, timeout=10)
        time.sleep(3)
        
        message = f'{protocol.upper()} {"enabled" if enabled else "disabled"}'
        return jsonify({'success': True, 'enabled': enabled, 'message': message})
            
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# === RECORDING ENDPOINTS ===

RECORDINGS_DIR = '/opt/mediamtx-webeditor/recordings'

@app.route('/api/recordings/settings')
@login_required
def get_recording_settings():
    """Get current recording settings from MediaMTX config"""
    try:
        # Read directly from file to avoid ruamel.yaml issues
        with open(CONFIG_FILE, 'r') as f:
            lines = f.readlines()
        
        enabled = False
        retention = '168h'
        
        # Find pathDefaults section
        in_path_defaults = False
        for line in lines:
            if 'pathDefaults:' in line:
                in_path_defaults = True
                continue
            
            if in_path_defaults:
                # Exit if we hit another top-level section
                if line.strip() and not line.startswith(' ') and not line.startswith('\t'):
                    break
                
                if 'record:' in line:
                    enabled = 'yes' in line.lower()
                elif 'recordDeleteAfter:' in line:
                    parts = line.split(':', 1)
                    if len(parts) > 1:
                        retention = parts[1].strip()
        
        return jsonify({'enabled': enabled, 'retention': retention})
    except Exception as e:
        print(f"Error reading recording settings: {e}")
        return jsonify({'enabled': False, 'retention': '168h'})

@app.route('/api/recordings/settings', methods=['POST'])
@login_required
def save_recording_settings():
    """Save recording settings to MediaMTX config using sed (avoids ruamel.yaml corruption)"""
    try:
        data = request.get_json()
        enabled = data.get('enabled', False)
        retention = data.get('retention', '168h')
        
        # Ensure retention has a time unit suffix (MediaMTX requires string like "72h" not just number)
        # If retention is just a number (like "0"), add "s" suffix
        if retention and retention.strip() and not retention.strip()[-1].isalpha():
            retention = retention.strip() + 's'
        
        record_value = 'yes' if enabled else 'no'
        record_path = f'{RECORDINGS_DIR}/%path_%Y-%m-%d_%H-%M-%S-%f'
        record_format = 'mpegts'
        
        # Ensure recordings directory exists
        os.makedirs(RECORDINGS_DIR, exist_ok=True)
        
        # Use sed to update settings in place (safe, doesn't corrupt YAML)
        commands = [
            # Update or add record setting
            f"sed -i '/^  record:/c\\  record: {record_value}' {CONFIG_FILE}",
            # Update or add recordPath
            f"sed -i '/^  recordPath:/c\\  recordPath: {record_path}' {CONFIG_FILE}",
            # Update or add recordFormat  
            f"sed -i '/^  recordFormat:/c\\  recordFormat: {record_format}' {CONFIG_FILE}",
            # Update or add recordDeleteAfter
            f"sed -i '/^  recordDeleteAfter:/c\\  recordDeleteAfter: {retention}' {CONFIG_FILE}",
        ]
        
        for cmd in commands:
            subprocess.run(cmd, shell=True, check=True)
        
        # Restart MediaMTX to apply changes
        subprocess.run(['sudo', 'systemctl', 'restart', SERVICE_NAME], check=True, timeout=10)
        
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/recordings/disk-usage')
@login_required
def get_disk_usage():
    """Get disk usage stats"""
    try:
        stat = os.statvfs('/')
        total = stat.f_blocks * stat.f_frsize
        free = stat.f_bavail * stat.f_frsize
        used = total - free
        
        return jsonify({
            'total': total,
            'used': used,
            'free': free
        })
    except Exception as e:
        return jsonify({'total': 0, 'used': 0, 'free': 0})

@app.route('/api/recordings/list')
@login_required
def list_recordings():
    """List all recorded files with expiration info"""
    try:
        recordings = []
        
        # Get current retention setting - read directly from file
        retention_str = '168h'  # Default 7 days
        try:
            with open(CONFIG_FILE, 'r') as f:
                lines = f.readlines()
            
            in_path_defaults = False
            for line in lines:
                if 'pathDefaults:' in line:
                    in_path_defaults = True
                    continue
                
                if in_path_defaults:
                    if line.strip() and not line.startswith(' ') and not line.startswith('\t'):
                        break
                    
                    if 'recordDeleteAfter:' in line:
                        parts = line.split(':', 1)
                        if len(parts) > 1:
                            retention_str = parts[1].strip()
                        break
        except:
            pass
        
        # Parse retention hours
        retention_hours = 168  # Default
        if retention_str not in ['0', '0s'] and retention_str.endswith('h'):
            retention_hours = int(retention_str[:-1])
        
        if os.path.exists(RECORDINGS_DIR):
            # Walk through all subdirectories
            for root, dirs, files in os.walk(RECORDINGS_DIR):
                for file in files:
                    if file.endswith('.mp4') or file.endswith('.ts'):
                        filepath = os.path.join(root, file)
                        stat = os.stat(filepath)
                        size_mb = round(stat.st_size / 1024 / 1024, 2)
                        created = datetime.fromtimestamp(stat.st_mtime)
                        date_str = created.strftime('%Y-%m-%d %H:%M:%S')
                        
                        # Check if currently recording (modified in last 10 seconds)
                        is_recording = (datetime.now() - created).total_seconds() < 10
                        
                        # Calculate expiration
                        if retention_str in ['0', '0s']:
                            expires_text = 'Never'
                            expires_color = '#4CAF50'
                            expires_text = 'Never'
                            expires_color = '#4CAF50'
                        else:
                            expires_at = created + timedelta(hours=retention_hours)
                            time_left = expires_at - datetime.now()
                            days_left = time_left.days
                            
                            if days_left < 0:
                                expires_text = 'Expired'
                                expires_color = '#f44336'
                            elif days_left == 0:
                                hours_left = int(time_left.total_seconds() / 3600)
                                expires_text = f'{hours_left}h'
                                expires_color = '#f44336'
                            elif days_left <= 2:
                                expires_text = f'{days_left}d'
                                expires_color = '#FF9800'
                            else:
                                expires_text = f'{days_left}d'
                                expires_color = '#999'
                        
                        recordings.append({
                            'name': file,
                            'path': filepath,
                            'size_mb': size_mb,
                            'date': date_str,
                            'expires_text': expires_text,
                            'expires_color': expires_color,
                            'is_recording': is_recording
                        })
            
            # Sort by date, newest first
            recordings.sort(key=lambda x: x['date'], reverse=True)
        
        return jsonify({'recordings': recordings})
    except Exception as e:
        return jsonify({'recordings': []})

@app.route('/api/recordings/download/<filename>')
@login_required
def download_recording(filename):
    """Download a recording"""
    try:
        # Search for file in recordings directory
        for root, dirs, files in os.walk(RECORDINGS_DIR):
            if filename in files:
                filepath = os.path.join(root, filename)
                return send_file(filepath, as_attachment=True)
        
        return jsonify({'error': 'File not found'}), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/recordings/convert-mp4/<filename>')
@login_required
def convert_mp4(filename):
    """Convert .ts recording to MP4 on-the-fly and serve for download"""
    try:
        # Find the .ts file
        ts_filepath = None
        for root, dirs, files in os.walk(RECORDINGS_DIR):
            if filename in files:
                ts_filepath = os.path.join(root, filename)
                break
        
        if not ts_filepath:
            return jsonify({'error': 'File not found'}), 404
        
        # Create temp MP4 file
        mp4_filename = filename.replace('.ts', '.mp4')
        temp_mp4 = os.path.join('/tmp', f'convert_{datetime.now().strftime("%Y%m%d_%H%M%S")}_{mp4_filename}')
        
        # Convert using FFmpeg (fast copy, just remux container)
        result = subprocess.run([
            'ffmpeg',
            '-i', ts_filepath,
            '-c', 'copy',  # Stream copy - no re-encoding (fast!)
            '-f', 'mp4',
            '-movflags', '+faststart',  # Optimize for web playback
            temp_mp4
        ], capture_output=True, timeout=300)  # 5 minute timeout
        
        if result.returncode != 0:
            if os.path.exists(temp_mp4):
                os.remove(temp_mp4)
            return jsonify({'error': 'Conversion failed', 'details': result.stderr.decode()}), 500
        
        # Send file and schedule deletion
        def remove_file(path):
            try:
                os.remove(path)
            except:
                pass
        
        response = send_file(temp_mp4, as_attachment=True, download_name=mp4_filename)
        
        # Delete temp file after response is sent
        @response.call_on_close
        def cleanup():
            remove_file(temp_mp4)
        
        return response
        
    except subprocess.TimeoutExpired:
        if os.path.exists(temp_mp4):
            os.remove(temp_mp4)
        return jsonify({'error': 'Conversion timed out (file too large)'}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/recordings/delete/<filename>', methods=['POST'])
@login_required
def delete_recording(filename):
    """Delete a recording"""
    try:
        # Search for file in recordings directory
        for root, dirs, files in os.walk(RECORDINGS_DIR):
            if filename in files:
                filepath = os.path.join(root, filename)
                os.remove(filepath)
                return jsonify({'success': True})
        
        return jsonify({'success': False, 'error': 'File not found'}), 404
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/recordings/play/<filename>')
@login_required
def play_recording(filename):
    """Serve HLS.js player with on-the-fly HLS generation"""
    try:
        # Generate unique session ID for temp files
        import uuid
        session_id = str(uuid.uuid4())
        
        # Build HLS stream URL
        hls_url = f"/api/recordings/hls/{session_id}/{filename}/index.m3u8"
        
        # Serve HLS.js player (same as live streams!)
        player_html = f'''
<!DOCTYPE html>
<html>
<head>
    <title>{filename}</title>
    <script src="https://cdn.jsdelivr.net/npm/hls.js@latest"></script>
    <style>
        body {{
            margin: 0;
            padding: 0;
            background: #000;
            display: flex;
            justify-content: center;
            align-items: center;
            height: 100vh;
            font-family: Arial, sans-serif;
        }}
        video {{
            max-width: 100%;
            max-height: 100vh;
            outline: none;
        }}
    </style>
</head>
<body>
    <video id="video" controls></video>
    <script>
        var video = document.getElementById('video');
        var videoSrc = '{hls_url}';
        
        if (Hls.isSupported()) {{
            var hls = new Hls();
            hls.loadSource(videoSrc);
            hls.attachMedia(video);
            hls.on(Hls.Events.MANIFEST_PARSED, function() {{
                video.play();
            }});
        }} else if (video.canPlayType('application/vnd.apple.mpegurl')) {{
            video.src = videoSrc;
            video.addEventListener('loadedmetadata', function() {{
                video.play();
            }});
        }}
    </script>
</body>
</html>
'''
        return player_html
    except Exception as e:
        return f"Error loading player: {str(e)}", 500

@app.route('/api/recordings/hls/<session_id>/<filename>/<path:hls_file>')
@login_required
def serve_hls_recording(session_id, filename, hls_file):
    """Generate and serve HLS playlist/segments on-the-fly"""
    try:
        import tempfile
        import threading
        
        # Find source recording
        source_path = None
        for root, dirs, files in os.walk(RECORDINGS_DIR):
            if filename in files:
                source_path = os.path.join(root, filename)
                break
        
        if not source_path:
            return "Recording not found", 404
        
        # Create temp directory for this session
        temp_dir = os.path.join(tempfile.gettempdir(), f"mediamtx_hls_{session_id}")
        os.makedirs(temp_dir, exist_ok=True)
        
        playlist_path = os.path.join(temp_dir, "index.m3u8")
        
        # If playlist doesn't exist, start FFmpeg to generate HLS
        if not os.path.exists(playlist_path):
            # Start FFmpeg in background to generate HLS
            def generate_hls():
                subprocess.run([
                    'ffmpeg', '-i', source_path,
                    '-c', 'copy',
                    '-f', 'hls',
                    '-hls_time', '2',
                    '-hls_list_size', '0',
                    '-hls_flags', 'independent_segments',
                    playlist_path
                ], stderr=subprocess.DEVNULL)
            
            thread = threading.Thread(target=generate_hls, daemon=True)
            thread.start()
            
            # Wait for playlist to be created (up to 5 seconds)
            import time
            for _ in range(50):
                if os.path.exists(playlist_path):
                    break
                time.sleep(0.1)
        
        # Serve the requested HLS file
        requested_file = os.path.join(temp_dir, hls_file)
        
        if not os.path.exists(requested_file):
            # Wait a bit for segment to be generated
            import time
            for _ in range(30):
                if os.path.exists(requested_file):
                    break
                time.sleep(0.1)
        
        if os.path.exists(requested_file):
            if hls_file.endswith('.m3u8'):
                return send_file(requested_file, mimetype='application/vnd.apple.mpegurl')
            else:
                return send_file(requested_file, mimetype='video/mp2t')
        
        return "File not ready", 404
    except Exception as e:
        return f"Error: {str(e)}", 500

# === END RECORDING ENDPOINTS ===

# === UPDATE ENDPOINTS ===

@app.route('/api/update/check')
@admin_required
def check_for_update():
    """Check GitHub for newer release"""
    try:
        import urllib.request
        import ssl
        
        # Create SSL context
        ctx = ssl.create_default_context()
        
        req = urllib.request.Request(GITHUB_API_URL, headers={
            'Accept': 'application/vnd.github.v3+json',
            'User-Agent': 'MediaMTX-WebEditor/' + CURRENT_VERSION
        })
        
        with urllib.request.urlopen(req, timeout=10, context=ctx) as response:
            data = json.loads(response.read().decode())
        
        remote_version = data.get('tag_name', '')
        release_notes = data.get('body', 'No release notes provided.')
        published_at = data.get('published_at', '')
        html_url = data.get('html_url', '')
        
        # Compare versions (strip 'v' prefix for comparison)
        local_ver = CURRENT_VERSION.lstrip('v')
        remote_ver = remote_version.lstrip('v')
        
        # Simple version comparison using tuple of ints
        def parse_version(v):
            try:
                parts = v.split('.')
                return tuple(int(p) for p in parts)
            except:
                return (0, 0, 0)
        
        update_available = parse_version(remote_ver) > parse_version(local_ver)
        
        return jsonify({
            'success': True,
            'current_version': CURRENT_VERSION,
            'remote_version': remote_version,
            'update_available': update_available,
            'release_notes': release_notes,
            'published_at': published_at,
            'html_url': html_url
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'current_version': CURRENT_VERSION,
            'error': str(e)
        })

@app.route('/api/update/apply', methods=['POST'])
@admin_required
def apply_update():
    """Download latest version from GitHub and replace the running code"""
    try:
        import urllib.request
        import ssl
        import shutil
        
        ctx = ssl.create_default_context()
        
        webeditor_file = '/opt/mediamtx-webeditor/mediamtx_config_editor.py'
        backup_file = webeditor_file + f'.backup_{datetime.now().strftime("%Y%m%d_%H%M%S")}'
        temp_file = '/tmp/mediamtx_config_editor_update.py'
        
        # Step 1: Download new version to temp file
        req = urllib.request.Request(GITHUB_RAW_URL, headers={
            'User-Agent': 'MediaMTX-WebEditor/' + CURRENT_VERSION
        })
        
        with urllib.request.urlopen(req, timeout=30, context=ctx) as response:
            new_code = response.read()
        
        if len(new_code) < 1000:
            return jsonify({'success': False, 'error': 'Downloaded file too small, aborting (possible download error)'}), 400
        
        # Step 2: Verify it contains a version string (sanity check)
        new_code_str = new_code.decode('utf-8')
        if 'CURRENT_VERSION' not in new_code_str:
            return jsonify({'success': False, 'error': 'Downloaded file does not appear to be a valid web editor'}), 400
        
        # Extract new version for response
        new_version = 'unknown'
        for line in new_code_str.split('\n'):
            if line.strip().startswith('CURRENT_VERSION'):
                try:
                    new_version = line.split('=')[1].strip().strip('"').strip("'")
                except:
                    pass
                break
        
        # Step 3: Write to temp file first
        with open(temp_file, 'wb') as f:
            f.write(new_code)
        
        # Step 4: Backup current version
        if os.path.exists(webeditor_file):
            shutil.copy2(webeditor_file, backup_file)
        
        # Step 5: Replace with new version
        shutil.copy2(temp_file, webeditor_file)
        os.chmod(webeditor_file, 0o644)
        
        # Step 6: Clean up temp file
        os.remove(temp_file)
        
        # Step 7: Restart the web editor service
        subprocess.run(['sudo', 'systemctl', 'restart', 'mediamtx-webeditor'], timeout=10)
        
        return jsonify({
            'success': True,
            'new_version': new_version,
            'backup_file': backup_file
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

# === END UPDATE ENDPOINTS ===

# === MEDIAMTX VERSION ENDPOINTS ===

MEDIAMTX_GITHUB_API = 'https://api.github.com/repos/bluenviron/mediamtx/releases/latest'
MEDIAMTX_BINARY = '/usr/local/bin/mediamtx'

@app.route('/api/mediamtx/version/check')
@admin_required
def check_mediamtx_version():
    """Check installed MediaMTX version vs latest GitHub release"""
    try:
        import urllib.request
        import ssl
        
        # Get installed version
        installed_version = 'unknown'
        try:
            result = subprocess.run([MEDIAMTX_BINARY, '--version'], capture_output=True, text=True, timeout=5)
            # Output is typically just the version like "v1.16.1" or "1.16.1"
            version_output = result.stdout.strip() or result.stderr.strip()
            # Extract version - look for pattern like v1.16.1 or 1.16.1
            import re
            match = re.search(r'v?(\d+\.\d+\.\d+)', version_output)
            if match:
                installed_version = 'v' + match.group(1)
        except Exception as e:
            print(f"Error getting MediaMTX version: {e}", flush=True)
        
        # Get latest from GitHub
        ctx = ssl.create_default_context()
        req = urllib.request.Request(MEDIAMTX_GITHUB_API, headers={
            'Accept': 'application/vnd.github.v3+json',
            'User-Agent': 'MediaMTX-WebEditor/' + CURRENT_VERSION
        })
        
        with urllib.request.urlopen(req, timeout=10, context=ctx) as response:
            data = json.loads(response.read().decode())
        
        remote_version = data.get('tag_name', '')
        release_notes = data.get('body', 'No release notes provided.')
        published_at = data.get('published_at', '')
        html_url = data.get('html_url', '')
        
        # Compare versions
        def parse_version(v):
            try:
                parts = v.lstrip('v').split('.')
                return tuple(int(p) for p in parts)
            except:
                return (0, 0, 0)
        
        update_available = parse_version(remote_version) > parse_version(installed_version)
        
        return jsonify({
            'success': True,
            'current_version': installed_version,
            'remote_version': remote_version,
            'update_available': update_available,
            'release_notes': release_notes,
            'published_at': published_at,
            'html_url': html_url
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        })

@app.route('/api/mediamtx/version/upgrade', methods=['POST'])
@admin_required
def upgrade_mediamtx():
    """Upgrade MediaMTX binary - preserves config YAML"""
    try:
        import urllib.request
        import ssl
        import shutil
        import tarfile
        
        ctx = ssl.create_default_context()
        
        # Step 1: Get latest release info to find download URL
        req = urllib.request.Request(MEDIAMTX_GITHUB_API, headers={
            'Accept': 'application/vnd.github.v3+json',
            'User-Agent': 'MediaMTX-WebEditor/' + CURRENT_VERSION
        })
        
        with urllib.request.urlopen(req, timeout=10, context=ctx) as response:
            data = json.loads(response.read().decode())
        
        remote_version = data.get('tag_name', '')
        
        # Find the linux amd64 tar.gz asset
        download_url = None
        for asset in data.get('assets', []):
            name = asset.get('name', '')
            if 'linux_amd64' in name and name.endswith('.tar.gz'):
                download_url = asset.get('browser_download_url', '')
                break
        
        if not download_url:
            return jsonify({'success': False, 'error': 'Could not find linux_amd64 download URL'}), 400
        
        # Step 2: Stop MediaMTX
        print(f"UPGRADE: Stopping MediaMTX for upgrade to {remote_version}...", flush=True)
        
        # Get current version before stopping
        previous_version = ''
        try:
            ver_result = subprocess.run([MEDIAMTX_BINARY, '--version'], capture_output=True, text=True, timeout=5)
            previous_version = ver_result.stdout.strip() if ver_result.returncode == 0 else ''
        except:
            pass
        
        subprocess.run(['sudo', 'systemctl', 'stop', 'mediamtx'], timeout=15)
        time.sleep(2)
        
        # Step 3: Backup current binary AND config YAML
        backup_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = f'{MEDIAMTX_BINARY}.backup_{backup_timestamp}'
        yaml_backup_path = f'{CONFIG_FILE}.backup_{backup_timestamp}'
        
        if os.path.exists(MEDIAMTX_BINARY):
            shutil.copy2(MEDIAMTX_BINARY, backup_path)
            print(f"UPGRADE: Binary backed up to {backup_path}", flush=True)
        
        if os.path.exists(CONFIG_FILE):
            shutil.copy2(CONFIG_FILE, yaml_backup_path)
            print(f"UPGRADE: YAML config backed up to {yaml_backup_path}", flush=True)
        
        # Step 4: Download new version
        print(f"UPGRADE: Downloading {download_url}...", flush=True)
        tmp_tar = '/tmp/mediamtx_upgrade.tar.gz'
        tmp_dir = '/tmp/mediamtx_upgrade'
        
        req = urllib.request.Request(download_url, headers={
            'User-Agent': 'MediaMTX-WebEditor/' + CURRENT_VERSION
        })
        
        with urllib.request.urlopen(req, timeout=60, context=ctx) as response:
            with open(tmp_tar, 'wb') as f:
                f.write(response.read())
        
        # Step 5: Extract binary
        if os.path.exists(tmp_dir):
            shutil.rmtree(tmp_dir)
        os.makedirs(tmp_dir)
        
        with tarfile.open(tmp_tar, 'r:gz') as tar:
            tar.extractall(tmp_dir)
        
        # Find the mediamtx binary in extracted files
        new_binary = os.path.join(tmp_dir, 'mediamtx')
        if not os.path.exists(new_binary):
            # Try to find it
            for root, dirs, files in os.walk(tmp_dir):
                if 'mediamtx' in files:
                    new_binary = os.path.join(root, 'mediamtx')
                    break
        
        if not os.path.exists(new_binary):
            # Rollback binary and YAML
            if os.path.exists(backup_path):
                shutil.copy2(backup_path, MEDIAMTX_BINARY)
            if os.path.exists(yaml_backup_path):
                shutil.copy2(yaml_backup_path, CONFIG_FILE)
            subprocess.run(['sudo', 'systemctl', 'start', 'mediamtx'], timeout=15)
            return jsonify({'success': False, 'error': 'Binary not found in download', 'rollback': True}), 400
        
        # Step 6: Replace binary (NOT the yaml)
        shutil.copy2(new_binary, MEDIAMTX_BINARY)
        os.chmod(MEDIAMTX_BINARY, 0o755)
        print(f"UPGRADE: Binary replaced with {remote_version}", flush=True)
        
        # Step 7: Clean up
        os.remove(tmp_tar)
        shutil.rmtree(tmp_dir)
        
        # Step 8: Start MediaMTX with existing config
        subprocess.run(['sudo', 'systemctl', 'start', 'mediamtx'], timeout=15)
        time.sleep(2)
        
        # Verify it started
        result = subprocess.run(['systemctl', 'is-active', 'mediamtx'], capture_output=True, text=True)
        if result.stdout.strip() != 'active':
            # Rollback binary and YAML
            print(f"UPGRADE: MediaMTX failed to start, rolling back...", flush=True)
            shutil.copy2(backup_path, MEDIAMTX_BINARY)
            os.chmod(MEDIAMTX_BINARY, 0o755)
            if os.path.exists(yaml_backup_path):
                shutil.copy2(yaml_backup_path, CONFIG_FILE)
            subprocess.run(['sudo', 'systemctl', 'start', 'mediamtx'], timeout=15)
            return jsonify({'success': False, 'error': 'MediaMTX failed to start with new version. Rolled back to previous version.', 'rollback': True}), 400
        
        print(f"UPGRADE: MediaMTX successfully upgraded to {remote_version}", flush=True)
        
        return jsonify({
            'success': True,
            'new_version': remote_version,
            'previous_version': previous_version,
            'backup_path': backup_path
        })
    except Exception as e:
        # Try to restart MediaMTX in case it was stopped
        try:
            subprocess.run(['sudo', 'systemctl', 'start', 'mediamtx'], timeout=15)
        except:
            pass
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/mediamtx/version/test', methods=['POST'])
@admin_required
def test_mediamtx_upgrade():
    """Auto-test MediaMTX after upgrade - start test stream, verify codec detection and HLS"""
    test_proc = None
    try:
        import urllib.request
        import ssl
        
        # Find a test video - prefer truck_60.ts (known H264 + KLV)
        test_video = None
        if os.path.exists(TEST_VIDEO_DIR):
            # First look for truck_60.ts specifically
            truck_path = os.path.join(TEST_VIDEO_DIR, 'truck_60.ts')
            if os.path.exists(truck_path):
                test_video = truck_path
            else:
                # Fall back to any .ts file
                for f in sorted(os.listdir(TEST_VIDEO_DIR)):
                    if f.endswith('.ts'):
                        test_video = os.path.join(TEST_VIDEO_DIR, f)
                        break
        
        if not test_video:
            return jsonify({'success': True, 'passed': True, 'reason': 'No test video available to verify, skipping test'})
        
        # Use the configured teststream path
        test_path = 'teststream'
        
        # Stop any existing test stream first
        global test_stream_process
        if test_stream_process and test_stream_process.poll() is None:
            test_stream_process.terminate()
            try:
                test_stream_process.wait(timeout=5)
            except:
                test_stream_process.kill()
            test_stream_process = None
            time.sleep(2)
        
        # Read SRT passphrase from config
        config = load_config()
        srt_passphrase = ''
        if config and 'pathDefaults' in config:
            srt_passphrase = config['pathDefaults'].get('srtPublishPassphrase', '') or ''
        
        srt_url = f'srt://localhost:8890?streamid=publish:{test_path}'
        if srt_passphrase:
            srt_url += f'&passphrase={srt_passphrase}'
        
        cmd = [
            'ffmpeg', '-re', '-stream_loop', '0',
            '-i', test_video,
            '-map', '0', '-c', 'copy',
            '-mpegts_flags', 'system_b',
            '-f', 'mpegts', '-t', '15',
            srt_url
        ]
        
        print(f"UPGRADE TEST: Starting test stream: {' '.join(cmd)}", flush=True)
        test_proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        
        # Wait for stream to register with retry
        # MediaMTX needs time to accept SRT connection and detect codecs
        tracks = []
        codec_ok = False
        hls_ok = False
        
        for attempt in range(4):
            time.sleep(3)
            
            try:
                ctx = ssl.create_default_context()
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_NONE
                
                req = urllib.request.Request(f'http://localhost:9997/v3/paths/list')
                with urllib.request.urlopen(req, timeout=5) as response:
                    path_data = json.loads(response.read().decode())
                
                for item in path_data.get('items', []):
                    if item.get('name') == test_path and item.get('ready', False):
                        tracks = item.get('tracks', [])
                        codec_ok = any('H264' in t or 'H265' in t or 'AV1' in t for t in tracks)
                        break
                
                if tracks:
                    print(f"UPGRADE TEST: Attempt {attempt+1} - Tracks detected: {tracks}", flush=True)
                    break
                else:
                    print(f"UPGRADE TEST: Attempt {attempt+1} - No tracks yet, retrying...", flush=True)
                    
            except Exception as e:
                print(f"UPGRADE TEST: Attempt {attempt+1} - Paths check error: {e}", flush=True)
        
        # Check HLS availability
        if codec_ok:
            try:
                time.sleep(2)  # Give HLS muxer time to create
                req = urllib.request.Request(f'https://localhost:8888/{test_path}/index.m3u8')
                with urllib.request.urlopen(req, timeout=5, context=ctx) as response:
                    hls_content = response.read().decode()
                    hls_ok = '#EXTM3U' in hls_content
            except:
                # Try HTTP
                try:
                    req = urllib.request.Request(f'http://localhost:8888/{test_path}/index.m3u8')
                    with urllib.request.urlopen(req, timeout=5) as response:
                        hls_content = response.read().decode()
                        hls_ok = '#EXTM3U' in hls_content
                except:
                    hls_ok = False
        
        # Clean up test stream
        if test_proc and test_proc.poll() is None:
            test_proc.terminate()
            try:
                test_proc.wait(timeout=5)
            except:
                test_proc.kill()
        
        # Determine result
        if codec_ok:
            return jsonify({
                'success': True,
                'passed': True,
                'codec': tracks[0] if tracks else 'Unknown',
                'tracks': ', '.join(tracks),
                'hls_ok': hls_ok,
                'reason': 'All checks passed'
            })
        elif tracks:
            return jsonify({
                'success': True,
                'passed': False,
                'codec': tracks[0] if tracks else 'Unknown',
                'tracks': ', '.join(tracks),
                'hls_ok': False,
                'reason': f'Codec detected as {tracks[0]} instead of H264 — HLS will not work'
            })
        else:
            return jsonify({
                'success': True,
                'passed': False,
                'codec': 'None',
                'tracks': 'None detected',
                'hls_ok': False,
                'reason': 'Stream did not register — no tracks detected'
            })
        
    except Exception as e:
        # Clean up on error
        if test_proc and test_proc.poll() is None:
            test_proc.terminate()
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/mediamtx/version/rollback', methods=['POST'])
@admin_required
def rollback_mediamtx():
    """Rollback MediaMTX to the most recent backup - auto-fixes YAML compatibility"""
    try:
        import shutil
        import glob
        
        # Find most recent binary backup
        backups = sorted(glob.glob(f'{MEDIAMTX_BINARY}.backup_*'), reverse=True)
        
        if not backups:
            return jsonify({'success': False, 'error': 'No backup found to rollback to'}), 400
        
        latest_backup = backups[0]
        
        # Extract timestamp from backup filename to find matching YAML backup
        backup_timestamp = latest_backup.split('backup_')[1] if 'backup_' in latest_backup else ''
        yaml_backup = f'{CONFIG_FILE}.backup_{backup_timestamp}' if backup_timestamp else ''
        
        # Get version of backup
        restored_version = ''
        try:
            ver_result = subprocess.run([latest_backup, '--version'], capture_output=True, text=True, timeout=5)
            restored_version = ver_result.stdout.strip() if ver_result.returncode == 0 else ''
        except:
            pass
        
        # Stop MediaMTX
        print(f"ROLLBACK: Stopping MediaMTX...", flush=True)
        subprocess.run(['sudo', 'systemctl', 'stop', 'mediamtx'], timeout=15)
        time.sleep(2)
        
        # Backup current YAML before we modify anything (so we can undo rollback)
        pre_rollback_yaml = f'{CONFIG_FILE}.pre_rollback'
        shutil.copy2(CONFIG_FILE, pre_rollback_yaml)
        
        # Restore binary
        shutil.copy2(latest_backup, MEDIAMTX_BINARY)
        os.chmod(MEDIAMTX_BINARY, 0o755)
        print(f"ROLLBACK: Binary restored from {latest_backup}", flush=True)
        
        # Restore YAML if backup exists
        if yaml_backup and os.path.exists(yaml_backup):
            shutil.copy2(yaml_backup, CONFIG_FILE)
            print(f"ROLLBACK: YAML config restored from {yaml_backup}", flush=True)
        
        # Try to start — if it fails, auto-fix unknown fields
        fields_removed = []
        max_fix_attempts = 5
        
        for attempt in range(max_fix_attempts + 1):
            subprocess.run(['sudo', 'systemctl', 'start', 'mediamtx'], timeout=15)
            time.sleep(3)
            
            result = subprocess.run(['systemctl', 'is-active', 'mediamtx'], capture_output=True, text=True)
            if result.stdout.strip() == 'active':
                # Success!
                print(f"ROLLBACK: MediaMTX started successfully (removed fields: {fields_removed or 'none'})", flush=True)
                break
            
            if attempt >= max_fix_attempts:
                # Give up — restore the pre-rollback state
                print(f"ROLLBACK: Failed after {max_fix_attempts} fix attempts, restoring pre-rollback state", flush=True)
                shutil.copy2(pre_rollback_yaml, CONFIG_FILE)
                # We need to restore the newer binary too since old one won't start
                # Find the newest non-backup mediamtx or re-download
                return jsonify({'success': False, 'error': f'MediaMTX failed to start after rollback. Removed fields {fields_removed} but still failing.'}), 500
            
            # Parse error from journal
            log_result = subprocess.run(
                ['journalctl', '-u', 'mediamtx', '-n', '5', '--no-pager', '-o', 'cat'],
                capture_output=True, text=True
            )
            
            # Look for "json: unknown field "fieldName""
            import re
            match = re.search(r'unknown field "([^"]+)"', log_result.stdout)
            if match:
                bad_field = match.group(1)
                print(f"ROLLBACK: Removing incompatible field '{bad_field}' from YAML (attempt {attempt+1})", flush=True)
                
                # Remove the field from YAML
                with open(CONFIG_FILE, 'r') as f:
                    lines = f.readlines()
                with open(CONFIG_FILE, 'w') as f:
                    for line in lines:
                        # Match top-level field (no leading whitespace)
                        if line.startswith(bad_field + ':'):
                            fields_removed.append(bad_field)
                            continue
                        f.write(line)
                
                # Stop before retry
                subprocess.run(['sudo', 'systemctl', 'stop', 'mediamtx'], timeout=15)
                time.sleep(1)
            else:
                # Unknown error, not a field issue
                return jsonify({'success': False, 'error': f'MediaMTX failed to start: {log_result.stdout[-200:]}'}), 500
        
        # Clean up
        try:
            os.remove(latest_backup)
            if yaml_backup and os.path.exists(yaml_backup):
                os.remove(yaml_backup)
            if os.path.exists(pre_rollback_yaml):
                os.remove(pre_rollback_yaml)
        except:
            pass
        
        print(f"ROLLBACK: Successfully restored to {restored_version}", flush=True)
        
        return jsonify({
            'success': True,
            'restored_version': restored_version,
            'fields_removed': fields_removed,
            'backup_used': latest_backup
        })
        
    except Exception as e:
        # Try to start MediaMTX
        try:
            subprocess.run(['sudo', 'systemctl', 'start', 'mediamtx'], timeout=15)
        except:
            pass
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/mediamtx/version/rollback/status')
@login_required
def rollback_status():
    """Check if a rollback backup is available"""
    try:
        import glob
        
        backups = sorted(glob.glob(f'{MEDIAMTX_BINARY}.backup_*'), reverse=True)
        
        if not backups:
            return jsonify({'available': False})
        
        latest_backup = backups[0]
        
        # Parse date from filename: mediamtx.backup_20260212_193841
        backup_date = ''
        try:
            timestamp = latest_backup.split('backup_')[1]
            date_part = timestamp[:8]
            time_part = timestamp[9:]
            backup_date = f'{date_part[:4]}-{date_part[4:6]}-{date_part[6:8]} {time_part[:2]}:{time_part[2:4]}:{time_part[4:6]}'
        except:
            backup_date = 'unknown'
        
        # Get version of backup
        backup_version = ''
        try:
            ver_result = subprocess.run([latest_backup, '--version'], capture_output=True, text=True, timeout=5)
            backup_version = ver_result.stdout.strip() if ver_result.returncode == 0 else ''
        except:
            pass
        
        return jsonify({
            'available': True,
            'backup_version': backup_version,
            'backup_date': backup_date,
            'backup_path': latest_backup,
            'yaml_backup': os.path.exists(f'{CONFIG_FILE}.backup_{latest_backup.split("backup_")[1]}') if 'backup_' in latest_backup else False
        })
    except:
        return jsonify({'available': False})

# === END MEDIAMTX VERSION ENDPOINTS ===

# === THEME ENDPOINTS ===

@app.route('/api/theme/settings')
@login_required
def get_theme_settings():
    """Get current theme settings"""
    return jsonify(load_theme())

@app.route('/api/theme/settings', methods=['POST'])
@admin_required
def save_theme_settings():
    """Save theme settings"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'error': 'No data provided'}), 400
        
        theme = {
            'headerColor': data.get('headerColor', DEFAULT_THEME['headerColor']),
            'headerColorEnd': data.get('headerColorEnd', DEFAULT_THEME['headerColorEnd']),
            'accentColor': data.get('accentColor', DEFAULT_THEME['accentColor']),
            'headerTitle': data.get('headerTitle', DEFAULT_THEME['headerTitle'])[:100],
            'subtitle': data.get('subtitle', DEFAULT_THEME['subtitle'])[:100]
        }
        
        # Basic hex color validation
        import re
        hex_pattern = re.compile(r'^#[0-9a-fA-F]{6}$')
        for key in ['headerColor', 'headerColorEnd', 'accentColor']:
            if not hex_pattern.match(theme[key]):
                return jsonify({'success': False, 'error': f'Invalid color format for {key}: {theme[key]}'}), 400
        
        save_theme(theme)
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

# === END THEME ENDPOINTS ===

# === LOGO ENDPOINTS ===

@app.route('/api/theme/logo')
def get_logo():
    """Serve the uploaded agency logo (no auth required so login page can show it)"""
    import glob
    matches = glob.glob(LOGO_FILE + '.*')
    if matches and os.path.exists(matches[0]):
        return send_file(matches[0])
    return '', 404

@app.route('/api/theme/logo', methods=['POST'])
@admin_required
def upload_logo():
    """Upload agency logo"""
    try:
        if 'logo' not in request.files:
            return jsonify({'success': False, 'error': 'No file provided'}), 400
        
        file = request.files['logo']
        if file.filename == '':
            return jsonify({'success': False, 'error': 'No file selected'}), 400
        
        # Check file size (500KB max)
        file.seek(0, 2)
        size = file.tell()
        file.seek(0)
        if size > 512000:
            return jsonify({'success': False, 'error': 'File too large (max 500KB)'}), 400
        
        # Get extension
        ext = os.path.splitext(file.filename)[1].lower()
        if ext not in ['.png', '.jpg', '.jpeg', '.gif', '.svg', '.webp']:
            return jsonify({'success': False, 'error': 'Invalid file type. Use PNG, JPG, GIF, SVG, or WebP.'}), 400
        
        # Remove any existing logo files
        import glob
        for old in glob.glob(LOGO_FILE + '.*'):
            os.remove(old)
        
        # Save new logo
        save_path = LOGO_FILE + ext
        file.save(save_path)
        os.chmod(save_path, 0o644)
        
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/theme/logo/remove', methods=['POST'])
@admin_required
def remove_logo():
    """Remove the uploaded agency logo"""
    try:
        import glob
        for old in glob.glob(LOGO_FILE + '.*'):
            os.remove(old)
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

# === END LOGO ENDPOINTS ===

# === EXTERNAL SOURCES ENDPOINTS ===

EXTERNAL_SOURCES_FILE = '/opt/mediamtx-webeditor/external_sources.json'

def load_external_sources_metadata():
    """Load external sources metadata (tracks which paths are external sources)"""
    if os.path.exists(EXTERNAL_SOURCES_FILE):
        try:
            with open(EXTERNAL_SOURCES_FILE, 'r') as f:
                return json.load(f)
        except:
            pass
    return {}

def save_external_sources_metadata(metadata):
    """Save external sources metadata"""
    os.makedirs(os.path.dirname(EXTERNAL_SOURCES_FILE), exist_ok=True)
    with open(EXTERNAL_SOURCES_FILE, 'w') as f:
        json.dump(metadata, f, indent=2)
    os.chmod(EXTERNAL_SOURCES_FILE, 0o600)

@app.route('/api/external-sources')
@login_required
def api_list_external_sources():
    """List all configured external sources with their connection status"""
    try:
        sources_metadata = load_external_sources_metadata()
        
        if not sources_metadata:
            return jsonify({'sources': []})
        
        # Get status from MediaMTX API
        path_statuses = {}
        try:
            import requests
            response = requests.get('http://localhost:9997/v3/paths/list', auth=('any', ''), timeout=2)
            if response.status_code == 200:
                data = response.json()
                for item in data.get('items', []):
                    path_name = item.get('name', '')
                    if path_name in sources_metadata:
                        if item.get('ready', False):
                            path_statuses[path_name] = 'ready'
                        else:
                            # Check if source is configured (waiting/retrying)
                            source_info = item.get('source', {})
                            if source_info:
                                path_statuses[path_name] = 'waiting'
                            else:
                                path_statuses[path_name] = 'not_ready'
        except:
            pass
        
        sources = []
        for name, meta in sources_metadata.items():
            enabled = meta.get('enabled', True)
            source_status = 'disabled' if not enabled else path_statuses.get(name, 'not_ready')
            sources.append({
                'name': name,
                'source_url': meta.get('source_url', ''),
                'on_demand': meta.get('on_demand', False),
                'enabled': enabled,
                'status': source_status
            })
        
        return jsonify({'sources': sources})
    except Exception as e:
        return jsonify({'sources': [], 'error': str(e)})

@app.route('/api/external-sources/add', methods=['POST'])
@admin_required
def api_add_external_source():
    """Add an external source path to mediamtx.yml"""
    try:
        data = request.get_json()
        name = data.get('name', '').strip()
        source_url = data.get('sourceUrl', '').strip()
        on_demand = data.get('onDemand', False)
        
        if not name:
            return jsonify({'success': False, 'error': 'Stream name is required'}), 400
        
        if not source_url:
            return jsonify({'success': False, 'error': 'Source URL is required'}), 400
        
        # Validate URL scheme
        valid_schemes = ['srt://', 'rtsp://', 'rtsps://', 'udp+mpegts://', 'rtmp://', 'rtmps://', 'http://', 'https://']
        if not any(source_url.startswith(s) for s in valid_schemes):
            return jsonify({'success': False, 'error': f'Unsupported URL scheme. Supported: SRT, RTSP, UDP MPEG-TS, RTMP, HLS'}), 400
        
        # Validate name: lowercase, numbers, underscores
        import re
        if not re.match(r'^[a-z0-9_]+$', name):
            return jsonify({'success': False, 'error': 'Name must be lowercase letters, numbers, and underscores only'}), 400
        
        # Check reserved names
        reserved = ['teststream', 'all', 'all_others']
        if name in reserved:
            return jsonify({'success': False, 'error': f'"{name}" is a reserved path name'}), 400
        
        # Check if name already exists in sources metadata
        sources_metadata = load_external_sources_metadata()
        if name in sources_metadata:
            return jsonify({'success': False, 'error': f'External source "{name}" already exists'}), 400
        
        # Check if path already exists in YAML
        with open(CONFIG_FILE, 'r') as f:
            content = f.read()
        
        # Look for existing path with this name in the paths section
        if re.search(r'^\s{2}' + re.escape(name) + r':', content, re.MULTILINE):
            return jsonify({'success': False, 'error': f'Path "{name}" already exists in MediaMTX config'}), 400
        
        # Create backup
        backup_file = os.path.join(BACKUP_DIR, f'mediamtx.yml.{datetime.now().strftime("%Y%m%d_%H%M%S")}')
        subprocess.run(['cp', CONFIG_FILE, backup_file], check=True)
        
        # Build the path entry
        on_demand_value = 'yes' if on_demand else 'no'
        path_entry = f"\n  {name}:\n    source: {source_url}\n    sourceOnDemand: {on_demand_value}\n"
        
        # Insert into YAML - find the paths section and append before the last path or at end
        # Strategy: find the 'all_others:' or the regex path line and insert before it
        with open(CONFIG_FILE, 'r') as f:
            lines = f.readlines()
        
        # Find the paths: section and insert the new path before all_others or regex path
        new_lines = []
        in_paths = False
        inserted = False
        
        for i, line in enumerate(lines):
            # Detect start of paths section
            if line.strip() == 'paths:' or line.startswith('paths:'):
                in_paths = True
                new_lines.append(line)
                continue
            
            # Once in paths section, insert before all_others: or regex path ~^
            if in_paths and not inserted:
                stripped = line.strip()
                if stripped.startswith('all_others:') or stripped.startswith('~^') or stripped.startswith("'~^"):
                    # Insert our new path before this line
                    new_lines.append(path_entry)
                    inserted = True
            
            new_lines.append(line)
        
        # If we never found all_others or regex, append at end of file
        if not inserted:
            new_lines.append(path_entry)
        
        with open(CONFIG_FILE, 'w') as f:
            f.writelines(new_lines)
        
        # Save to metadata
        sources_metadata[name] = {
            'source_url': source_url,
            'on_demand': on_demand,
            'enabled': True
        }
        save_external_sources_metadata(sources_metadata)
        
        # Auto-create UFW rule for UDP sources
        if source_url.startswith('udp+mpegts://'):
            try:
                import re
                port_match = re.search(r':(\d+)', source_url.replace('udp+mpegts://', ''))
                if port_match:
                    udp_port = port_match.group(1)
                    subprocess.run(['sudo', 'ufw', 'allow', f'{udp_port}/udp'], 
                                   capture_output=True, timeout=10)
                    print(f"✓ UFW rule created: allow {udp_port}/udp", flush=True)
            except Exception as e:
                print(f"Warning: Could not create UFW rule: {e}", flush=True)
        
        # Restart MediaMTX
        subprocess.run(['sudo', 'systemctl', 'restart', SERVICE_NAME], check=True, timeout=10)
        time.sleep(3)
        
        return jsonify({'success': True})
    except Exception as e:
        print(f"ERROR adding external source: {e}", flush=True)
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/external-sources/delete', methods=['POST'])
@admin_required
def api_delete_external_source():
    """Delete an external source path from mediamtx.yml"""
    try:
        data = request.get_json()
        name = data.get('name', '').strip()
        
        if not name:
            return jsonify({'success': False, 'error': 'Source name is required'}), 400
        
        # Check it exists in metadata
        sources_metadata = load_external_sources_metadata()
        if name not in sources_metadata:
            return jsonify({'success': False, 'error': f'External source "{name}" not found'}), 404
        
        # Create backup
        backup_file = os.path.join(BACKUP_DIR, f'mediamtx.yml.{datetime.now().strftime("%Y%m%d_%H%M%S")}')
        subprocess.run(['cp', CONFIG_FILE, backup_file], check=True)
        
        # Remove the path entry from YAML
        # Read lines and find the path block to remove
        with open(CONFIG_FILE, 'r') as f:
            lines = f.readlines()
        
        new_lines = []
        skip_block = False
        in_paths = False
        
        for i, line in enumerate(lines):
            # Track if we're in paths section
            if line.strip() == 'paths:' or line.startswith('paths:'):
                in_paths = True
                new_lines.append(line)
                continue
            
            if in_paths and skip_block:
                # We're skipping lines belonging to the deleted path
                # Stop skipping when we hit another path entry (2-space indent + name:) or a top-level key
                stripped = line.strip()
                if stripped and not line.startswith('    ') and not line.startswith('\t\t'):
                    # This is either a new path entry (2-space) or top-level key (no indent)
                    if line.startswith('  ') and ':' in stripped:
                        # New path entry — stop skipping
                        skip_block = False
                    elif not line.startswith(' '):
                        # Top-level key — stop skipping, we've left paths section
                        skip_block = False
                        in_paths = False
                    # else: sub-property of our path (4+ spaces) — keep skipping
                
                if skip_block:
                    continue  # Skip this line
            
            # Check if this line starts the path block we want to delete
            if in_paths and not skip_block:
                # Match "  name:" with exactly 2-space indent
                import re
                if re.match(r'^  ' + re.escape(name) + r':\s*$', line):
                    skip_block = True
                    continue  # Skip the path name line
            
            new_lines.append(line)
        
        with open(CONFIG_FILE, 'w') as f:
            f.writelines(new_lines)
        
        # Remove UFW rule for UDP sources
        source_url = sources_metadata[name].get('source_url', '')
        if source_url.startswith('udp+mpegts://'):
            try:
                import re
                port_match = re.search(r':(\d+)', source_url.replace('udp+mpegts://', ''))
                if port_match:
                    udp_port = port_match.group(1)
                    subprocess.run(['sudo', 'ufw', 'delete', 'allow', f'{udp_port}/udp'],
                                   capture_output=True, timeout=10)
                    print(f"✓ UFW rule removed: {udp_port}/udp", flush=True)
            except Exception as e:
                print(f"Warning: Could not remove UFW rule: {e}", flush=True)
        
        # Remove from metadata
        del sources_metadata[name]
        save_external_sources_metadata(sources_metadata)
        
        # Restart MediaMTX
        subprocess.run(['sudo', 'systemctl', 'restart', SERVICE_NAME], check=True, timeout=10)
        time.sleep(3)
        
        return jsonify({'success': True})
    except Exception as e:
        print(f"ERROR deleting external source: {e}", flush=True)
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/external-sources/toggle', methods=['POST'])
@admin_required
def api_toggle_external_source():
    """Enable or disable an external source (removes/adds path from YAML without deleting metadata)"""
    try:
        data = request.get_json()
        name = data.get('name', '').strip()
        
        if not name:
            return jsonify({'success': False, 'error': 'Source name is required'}), 400
        
        sources_metadata = load_external_sources_metadata()
        if name not in sources_metadata:
            return jsonify({'success': False, 'error': f'External source "{name}" not found'}), 404
        
        currently_enabled = sources_metadata[name].get('enabled', True)
        
        # Create backup
        backup_file = os.path.join(BACKUP_DIR, f'mediamtx.yml.{datetime.now().strftime("%Y%m%d_%H%M%S")}')
        subprocess.run(['cp', CONFIG_FILE, backup_file], check=True)
        
        if currently_enabled:
            # DISABLE: Remove path from YAML but keep metadata
            with open(CONFIG_FILE, 'r') as f:
                lines = f.readlines()
            
            new_lines = []
            skip_block = False
            in_paths = False
            
            for i, line in enumerate(lines):
                if line.strip() == 'paths:' or line.startswith('paths:'):
                    in_paths = True
                    new_lines.append(line)
                    continue
                
                if in_paths and skip_block:
                    stripped = line.strip()
                    if stripped and not line.startswith('    ') and not line.startswith('\t\t'):
                        if line.startswith('  ') and ':' in stripped:
                            skip_block = False
                        elif not line.startswith(' '):
                            skip_block = False
                            in_paths = False
                    
                    if skip_block:
                        continue
                
                if in_paths and not skip_block:
                    import re
                    if re.match(r'^  ' + re.escape(name) + r':\s*$', line):
                        skip_block = True
                        continue
                
                new_lines.append(line)
            
            with open(CONFIG_FILE, 'w') as f:
                f.writelines(new_lines)
            
            sources_metadata[name]['enabled'] = False
            save_external_sources_metadata(sources_metadata)
            
        else:
            # ENABLE: Re-add path to YAML from metadata
            source_url = sources_metadata[name].get('source_url', '')
            on_demand = sources_metadata[name].get('on_demand', False)
            on_demand_value = 'yes' if on_demand else 'no'
            path_entry = f"\n  {name}:\n    source: {source_url}\n    sourceOnDemand: {on_demand_value}\n"
            
            with open(CONFIG_FILE, 'r') as f:
                lines = f.readlines()
            
            new_lines = []
            in_paths = False
            inserted = False
            
            for i, line in enumerate(lines):
                if line.strip() == 'paths:' or line.startswith('paths:'):
                    in_paths = True
                    new_lines.append(line)
                    continue
                
                if in_paths and not inserted:
                    stripped = line.strip()
                    if stripped.startswith('all_others:') or stripped.startswith('~^') or stripped.startswith("'~^"):
                        new_lines.append(path_entry)
                        inserted = True
                
                new_lines.append(line)
            
            if not inserted:
                new_lines.append(path_entry)
            
            with open(CONFIG_FILE, 'w') as f:
                f.writelines(new_lines)
            
            sources_metadata[name]['enabled'] = True
            save_external_sources_metadata(sources_metadata)
        
        # Restart MediaMTX
        subprocess.run(['sudo', 'systemctl', 'restart', SERVICE_NAME], check=True, timeout=10)
        time.sleep(3)
        
        new_state = not currently_enabled
        return jsonify({'success': True, 'enabled': new_state})
    except Exception as e:
        print(f"ERROR toggling external source: {e}", flush=True)
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/external-sources/switch-mode', methods=['POST'])
@admin_required
def api_switch_srt_mode():
    """Switch an SRT external source between caller and listener mode"""
    try:
        data = request.get_json()
        name = data.get('name', '').strip()
        
        if not name:
            return jsonify({'success': False, 'error': 'Source name is required'}), 400
        
        sources_metadata = load_external_sources_metadata()
        if name not in sources_metadata:
            return jsonify({'success': False, 'error': f'External source "{name}" not found'}), 404
        
        source_url = sources_metadata[name].get('source_url', '')
        if not source_url.startswith('srt://'):
            return jsonify({'success': False, 'error': 'Mode switching is only available for SRT sources'}), 400
        
        # Determine current mode and swap
        if 'mode=listener' in source_url:
            new_url = source_url.replace('mode=listener', 'mode=caller')
            new_mode = 'caller'
        else:
            new_url = source_url.replace('mode=caller', 'mode=listener')
            new_mode = 'listener'
        
        # Update metadata
        sources_metadata[name]['source_url'] = new_url
        save_external_sources_metadata(sources_metadata)
        
        # Update YAML if source is enabled
        if sources_metadata[name].get('enabled', True):
            # Create backup
            backup_file = os.path.join(BACKUP_DIR, f'mediamtx.yml.{datetime.now().strftime("%Y%m%d_%H%M%S")}')
            subprocess.run(['cp', CONFIG_FILE, backup_file], check=True)
            
            # Replace the source URL in the YAML
            with open(CONFIG_FILE, 'r') as f:
                content = f.read()
            
            content = content.replace(source_url, new_url)
            
            with open(CONFIG_FILE, 'w') as f:
                f.write(content)
            
            # Restart MediaMTX
            subprocess.run(['sudo', 'systemctl', 'restart', SERVICE_NAME], check=True, timeout=10)
            time.sleep(3)
        
        return jsonify({'success': True, 'mode': new_mode})
    except Exception as e:
        print(f"ERROR switching SRT mode: {e}", flush=True)
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/external-sources/edit', methods=['POST'])
@admin_required
def api_edit_external_source():
    """Edit an existing external source - updates URL in both metadata and YAML"""
    try:
        data = request.get_json()
        name = data.get('name', '').strip()
        new_source_url = data.get('sourceUrl', '').strip()
        on_demand = data.get('onDemand', False)
        
        if not name or not new_source_url:
            return jsonify({'success': False, 'error': 'Name and source URL are required'}), 400
        
        sources_metadata = load_external_sources_metadata()
        if name not in sources_metadata:
            return jsonify({'success': False, 'error': f'External source "{name}" not found'}), 404
        
        old_source_url = sources_metadata[name].get('source_url', '')
        is_enabled = sources_metadata[name].get('enabled', True)
        
        # Create backup
        backup_file = os.path.join(BACKUP_DIR, f'mediamtx.yml.{datetime.now().strftime("%Y%m%d_%H%M%S")}')
        subprocess.run(['cp', CONFIG_FILE, backup_file], check=True)
        
        # Update YAML if source is enabled
        if is_enabled:
            # Read the YAML and replace the source line for this path
            with open(CONFIG_FILE, 'r') as f:
                lines = f.readlines()
            
            new_lines = []
            in_our_path = False
            on_demand_value = 'yes' if on_demand else 'no'
            
            for i, line in enumerate(lines):
                import re
                # Detect our path entry
                if re.match(r'^  ' + re.escape(name) + r':\s*$', line):
                    in_our_path = True
                    new_lines.append(line)
                    continue
                
                if in_our_path:
                    stripped = line.strip()
                    # Replace source line
                    if stripped.startswith('source:'):
                        new_lines.append(f'    source: {new_source_url}\n')
                        continue
                    # Replace sourceOnDemand line
                    elif stripped.startswith('sourceOnDemand:'):
                        new_lines.append(f'    sourceOnDemand: {on_demand_value}\n')
                        continue
                    # Detect end of our path block
                    elif stripped and not line.startswith('    ') and not line.startswith('\t\t'):
                        in_our_path = False
                
                new_lines.append(line)
            
            with open(CONFIG_FILE, 'w') as f:
                f.writelines(new_lines)
        
        # Update metadata
        sources_metadata[name]['source_url'] = new_source_url
        sources_metadata[name]['on_demand'] = on_demand
        save_external_sources_metadata(sources_metadata)
        
        # Restart MediaMTX if enabled
        if is_enabled:
            subprocess.run(['sudo', 'systemctl', 'restart', SERVICE_NAME], check=True, timeout=10)
            time.sleep(3)
        
        return jsonify({'success': True})
    except Exception as e:
        print(f"ERROR editing external source: {e}", flush=True)
        return jsonify({'success': False, 'error': str(e)}), 500

# === END EXTERNAL SOURCES ENDPOINTS ===

# === DASHBOARD ENDPOINTS ===

@app.route('/api/dashboard/metrics')
@login_required
def get_dashboard_metrics():
    """Get all dashboard metrics in one call"""
    try:
        metrics = {}
        
        # Get MediaMTX API stats for active streams/viewers
        try:
            api_url = 'http://localhost:9997/v3/paths/list'
            api_response = subprocess.run(
                ['curl', '-s', api_url],
                capture_output=True,
                text=True,
                timeout=2
            )
            
            if api_response.returncode == 0:
                paths_data = json.loads(api_response.stdout)
                active_streams = 0
                total_viewers = 0
                streams_list = []
                
                if 'items' in paths_data:
                    # Build a map of live/ paths (subtract 1 for internal FFmpeg)
                    live_paths = {}
                    for path in paths_data['items']:
                        path_name = path.get('name', '')
                        if path_name.startswith('live/'):
                            stream_name = path_name[5:]  # Remove 'live/' prefix
                            readers_data = path.get('readers', [])
                            if isinstance(readers_data, list):
                                # Subtract 1 for internal FFmpeg reader
                                live_readers = max(0, len(readers_data) - 1)
                                live_paths[stream_name] = live_readers
                            else:
                                live_paths[stream_name] = max(0, (readers_data or 0) - 1)
                    
                    # Process main paths and add live/ viewers
                    for path in paths_data['items']:
                        path_name = path.get('name', '')
                        # Skip internal paths and live/ paths
                        if path_name and path_name != 'all' and not path_name.startswith('live/'):
                            # Count streams that are ready (have active source)
                            if path.get('ready', False):
                                active_streams += 1
                                readers_data = path.get('readers', [])
                                # readers can be a list (count length) or int (use directly)
                                if isinstance(readers_data, list):
                                    readers = len(readers_data)
                                else:
                                    readers = readers_data or 0
                                
                                # Add live/ viewers (minus FFmpeg)
                                if path_name in live_paths:
                                    readers += live_paths[path_name]
                                
                                total_viewers += readers
                                
                                streams_list.append({
                                    'name': path_name,
                                    'readers': readers,
                                    'source': path.get('sourceType', 'Unknown')
                                })
                
                metrics['active_streams'] = active_streams
                metrics['total_viewers'] = total_viewers
                metrics['streams'] = streams_list
        except:
            metrics['active_streams'] = 0
            metrics['total_viewers'] = 0
            metrics['streams'] = []
        
        # Get system CPU and RAM usage
        metrics['cpu_percent'] = psutil.cpu_percent(interval=0.1)
        mem = psutil.virtual_memory()
        metrics['ram_percent'] = mem.percent
        metrics['ram_used'] = mem.used
        metrics['ram_total'] = mem.total
        
        # Get disk usage
        disk = psutil.disk_usage('/')
        metrics['disk_percent'] = disk.percent
        metrics['disk_used'] = disk.used
        metrics['disk_total'] = disk.total
        metrics['disk_free'] = disk.free
        
        # Get network I/O rate (bandwidth)
        # Store previous values to calculate rate
        if not hasattr(get_dashboard_metrics, 'prev_net_io'):
            get_dashboard_metrics.prev_net_io = psutil.net_io_counters()
            get_dashboard_metrics.prev_time = time.time()
            metrics['network_rx_rate'] = 0
            metrics['network_tx_rate'] = 0
        else:
            current_net_io = psutil.net_io_counters()
            current_time = time.time()
            time_delta = current_time - get_dashboard_metrics.prev_time
            
            if time_delta > 0:
                # Calculate bytes per second
                rx_rate = (current_net_io.bytes_recv - get_dashboard_metrics.prev_net_io.bytes_recv) / time_delta
                tx_rate = (current_net_io.bytes_sent - get_dashboard_metrics.prev_net_io.bytes_sent) / time_delta
                
                metrics['network_rx_rate'] = rx_rate
                metrics['network_tx_rate'] = tx_rate
                
                # Update previous values
                get_dashboard_metrics.prev_net_io = current_net_io
                get_dashboard_metrics.prev_time = current_time
            else:
                metrics['network_rx_rate'] = 0
                metrics['network_tx_rate'] = 0
        
        # Get recordings size
        recordings_size = 0
        if os.path.exists(RECORDINGS_DIR):
            for root, dirs, files in os.walk(RECORDINGS_DIR):
                for file in files:
                    filepath = os.path.join(root, file)
                    if os.path.isfile(filepath):
                        recordings_size += os.path.getsize(filepath)
        metrics['recordings_size'] = recordings_size
        
        # Get server uptime (MediaMTX process)
        try:
            mediamtx_pid = subprocess.run(
                ['pgrep', 'mediamtx'],
                capture_output=True,
                text=True
            )
            if mediamtx_pid.returncode == 0:
                pid = int(mediamtx_pid.stdout.strip().split()[0])
                process = psutil.Process(pid)
                metrics['uptime'] = time.time() - process.create_time()
            else:
                metrics['uptime'] = 0
        except:
            metrics['uptime'] = 0
        
        return jsonify(metrics)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# === END DASHBOARD ENDPOINTS ===

if __name__ == '__main__':
    # Check if config file exists
    if not os.path.exists(CONFIG_FILE):
        print(f"Error: MediaMTX configuration file not found at {CONFIG_FILE}")
        print("Please install MediaMTX first using the installation script.")
        exit(1)
    
    # Auto-patch: Ensure IPv6 loopback (::1) is in the localhost API user
    # Without this, the web editor's API calls fail auth on systems that connect via IPv6
    try:
        with open(CONFIG_FILE, 'r') as f:
            content = f.read()
        if "ips: ['127.0.0.1']" in content and "::1" not in content:
            content = content.replace("ips: ['127.0.0.1']", "ips: ['127.0.0.1', '::1']", 1)
            with open(CONFIG_FILE, 'w') as f:
                f.write(content)
            print("✓ Patched mediamtx.yml: Added IPv6 loopback (::1) to localhost API user")
            # Restart MediaMTX to pick up the change
            subprocess.run(['sudo', 'systemctl', 'restart', SERVICE_NAME], timeout=10)
            time.sleep(3)
    except Exception as e:
        print(f"Warning: Could not auto-patch IPv6 loopback: {e}")
    
    print("="*50)
    print("MediaMTX Configuration Web Editor")
    print("="*50)
    print(f"Configuration file: {CONFIG_FILE}")
    print(f"Backup directory: {BACKUP_DIR}")
    print("")
    print("Starting web server on http://0.0.0.0:5000")
    print("Access from browser: http://<server-ip>:5000")
    print("")
    print("Press Ctrl+C to stop")
    print("="*50)
    
    app.run(host='0.0.0.0', port=5000, debug=False)
