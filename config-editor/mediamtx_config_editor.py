#!/usr/bin/env python3
"""
MediaMTX Configuration Web Editor
Simple web interface to edit MediaMTX YAML configuration safely
"""

from flask import Flask, render_template_string, request, jsonify, redirect, url_for
import yaml
import os
import subprocess
from datetime import datetime

app = Flask(__name__)

# Configuration
CONFIG_FILE = '/usr/local/etc/mediamtx.yml'
BACKUP_DIR = '/usr/local/etc/mediamtx_backups'
SERVICE_NAME = 'mediamtx'

# Ensure backup directory exists
os.makedirs(BACKUP_DIR, exist_ok=True)

# HTML Template
HTML_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head>
    <title>MediaMTX Configuration Editor</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        
        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            padding: 20px;
        }
        
        .container {
            max-width: 1200px;
            margin: 0 auto;
            background: white;
            border-radius: 12px;
            box-shadow: 0 20px 60px rgba(0,0,0,0.3);
            overflow: hidden;
        }
        
        .header {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 30px;
            text-align: center;
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
            background: #f8f9fa;
            border-bottom: 2px solid #e9ecef;
        }
        
        .tab {
            flex: 1;
            padding: 15px 20px;
            text-align: center;
            background: #f8f9fa;
            border: none;
            cursor: pointer;
            font-size: 16px;
            font-weight: 500;
            transition: all 0.3s;
        }
        
        .tab:hover {
            background: #e9ecef;
        }
        
        .tab.active {
            background: white;
            color: #667eea;
            border-bottom: 3px solid #667eea;
        }
        
        .content {
            padding: 30px;
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
            color: #333;
        }
        
        .form-group input,
        .form-group select {
            width: 100%;
            padding: 12px;
            border: 2px solid #e9ecef;
            border-radius: 6px;
            font-size: 15px;
            transition: border-color 0.3s;
        }
        
        .form-group input:focus,
        .form-group select:focus {
            outline: none;
            border-color: #667eea;
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
            background: #d4edda;
            color: #155724;
            border: 1px solid #c3e6cb;
        }
        
        .alert-danger {
            background: #f8d7da;
            color: #721c24;
            border: 1px solid #f5c6cb;
        }
        
        .alert-info {
            background: #d1ecf1;
            color: #0c5460;
            border: 1px solid #bee5eb;
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
            background: #f8f9fa;
            padding: 15px;
            border-radius: 6px;
            margin-top: 10px;
        }
        
        .user-item {
            background: white;
            padding: 15px;
            margin-bottom: 10px;
            border-radius: 6px;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        
        textarea {
            width: 100%;
            min-height: 400px;
            font-family: 'Courier New', monospace;
            font-size: 13px;
            padding: 15px;
            border: 2px solid #e9ecef;
            border-radius: 6px;
        }
        
        .help-text {
            font-size: 14px;
            color: #6c757d;
            margin-top: 5px;
        }
        
        .section-title {
            font-size: 1.3rem;
            color: #667eea;
            margin-bottom: 20px;
            padding-bottom: 10px;
            border-bottom: 2px solid #e9ecef;
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🎥 MediaMTX Configuration Editor</h1>
            <p>Manage your streaming server settings with ease</p>
        </div>
        
        <div class="tabs">
            <button class="tab active" onclick="showTab('basic')">Basic Settings</button>
            <button class="tab" onclick="showTab('users')">Users & Auth</button>
            <button class="tab" onclick="showTab('protocols')">Protocols</button>
            <button class="tab" onclick="showTab('advanced')">Advanced YAML</button>
            <button class="tab" onclick="showTab('service')">Service Control</button>
        </div>
        
        <div class="content">
            {% if message %}
            <div class="alert alert-{{ message_type }}">
                {{ message }}
            </div>
            {% endif %}
            
            <!-- Basic Settings Tab -->
            <div id="basic" class="tab-content active">
                <h2 class="section-title">Basic Configuration</h2>
                <form method="POST" action="/save_basic">
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
            <div id="users" class="tab-content">
                <h2 class="section-title">User Management</h2>
                <form method="POST" action="/save_users">
                    <div class="form-group">
                        <label>Current Users</label>
                        <div class="user-list">
                            {% for user in config.authInternalUsers %}
                                {% if user.user != 'any' %}
                                <div class="user-item">
                                    <div>
                                        <strong>{{ user.user }}</strong>
                                        <p class="help-text">Permissions: {{ user.permissions | length }} actions</p>
                                    </div>
                                </div>
                                {% endif %}
                            {% endfor %}
                        </div>
                    </div>
                    
                    <h3 style="margin-top: 30px; margin-bottom: 15px;">Add/Update User</h3>
                    <div class="form-group">
                        <label>Username</label>
                        <input type="text" name="username" placeholder="Enter username" required>
                    </div>
                    
                    <div class="form-group">
                        <label>Password</label>
                        <input type="password" name="password" placeholder="Enter password" required>
                    </div>
                    
                    <div class="form-group">
                        <label>Permissions</label>
                        <select name="permissions" multiple size="4" style="height: auto;">
                            <option value="publish" selected>Publish (Stream to server)</option>
                            <option value="read" selected>Read (View streams)</option>
                            <option value="playback" selected>Playback (Access recordings)</option>
                            <option value="api">API Access</option>
                        </select>
                        <p class="help-text">Hold Ctrl/Cmd to select multiple</p>
                    </div>
                    
                    <button type="submit" class="btn btn-primary">Add/Update User</button>
                </form>
            </div>
            
            <!-- Protocols Tab -->
            <div id="protocols" class="tab-content">
                <h2 class="section-title">Protocol Settings</h2>
                <form method="POST" action="/save_protocols">
                    <h3>RTSP Settings</h3>
                    <div class="form-row">
                        <div class="form-group">
                            <label>RTSP Port</label>
                            <input type="number" name="rtspAddress" value="{{ config.rtspAddress.split(':')[1] if ':' in config.rtspAddress else '8554' }}" placeholder="8554">
                        </div>
                        
                        <div class="form-group">
                            <label>Encryption</label>
                            <select name="rtspEncryption">
                                <option value="no" {% if config.rtspEncryption == 'no' %}selected{% endif %}>Disabled</option>
                                <option value="optional" {% if config.rtspEncryption == 'optional' %}selected{% endif %}>Optional</option>
                                <option value="strict" {% if config.rtspEncryption == 'strict' %}selected{% endif %}>Strict</option>
                            </select>
                        </div>
                    </div>
                    
                    <h3 style="margin-top: 30px;">RTMP Settings</h3>
                    <div class="form-row">
                        <div class="form-group">
                            <label>RTMP Port</label>
                            <input type="number" name="rtmpAddress" value="{{ config.rtmpAddress.split(':')[1] if ':' in config.rtmpAddress else '1935' }}" placeholder="1935">
                        </div>
                        
                        <div class="form-group">
                            <label>RTMP Encryption</label>
                            <select name="rtmpEncryption">
                                <option value="no" {% if config.rtmpEncryption == 'no' %}selected{% endif %}>Disabled</option>
                                <option value="optional" {% if config.rtmpEncryption == 'optional' %}selected{% endif %}>Optional</option>
                                <option value="strict" {% if config.rtmpEncryption == 'strict' %}selected{% endif %}>Strict</option>
                            </select>
                        </div>
                    </div>
                    
                    <h3 style="margin-top: 30px;">HLS Settings</h3>
                    <div class="form-row">
                        <div class="form-group">
                            <label>HLS Port</label>
                            <input type="number" name="hlsAddress" value="{{ config.hlsAddress.split(':')[1] if ':' in config.hlsAddress else '8888' }}" placeholder="8888">
                        </div>
                        
                        <div class="form-group">
                            <label>HLS Encryption</label>
                            <select name="hlsEncryption">
                                <option value="no" {% if config.hlsEncryption == 'no' %}selected{% endif %}>Disabled</option>
                                <option value="yes" {% if config.hlsEncryption == 'yes' %}selected{% endif %}>Enabled</option>
                            </select>
                        </div>
                    </div>
                    
                    <h3 style="margin-top: 30px;">SRT Settings</h3>
                    <div class="form-group">
                        <label>SRT Port</label>
                        <input type="number" name="srtAddress" value="{{ config.srtAddress.split(':')[1] if ':' in config.srtAddress else '8890' }}" placeholder="8890">
                    </div>
                    
                    <button type="submit" class="btn btn-primary">Save Protocol Settings</button>
                </form>
            </div>
            
            <!-- Advanced YAML Tab -->
            <div id="advanced" class="tab-content">
                <h2 class="section-title">Advanced YAML Editor</h2>
                <div class="alert alert-info">
                    ⚠️ <strong>Warning:</strong> Direct YAML editing can break the configuration if syntax is invalid. Always create a backup first!
                </div>
                <form method="POST" action="/save_yaml">
                    <div class="form-group">
                        <textarea name="yaml_content">{{ yaml_content }}</textarea>
                    </div>
                    
                    <div class="btn-group">
                        <button type="submit" class="btn btn-primary">Save YAML</button>
                        <button type="submit" formaction="/validate_yaml" class="btn btn-success">Validate Only</button>
                    </div>
                </form>
            </div>
            
            <!-- Service Control Tab -->
            <div id="service" class="tab-content">
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
                        <button type="submit" class="btn btn-primary">Restart Service</button>
                    </form>
                    
                    <form method="POST" action="/service/stop" style="margin: 0;">
                        <button type="submit" class="btn btn-danger">Stop Service</button>
                    </form>
                    
                    <form method="POST" action="/service/start" style="margin: 0;">
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
        </div>
    </div>
    
    <script>
        function showTab(tabName) {
            // Hide all tabs
            const tabs = document.querySelectorAll('.tab');
            const contents = document.querySelectorAll('.tab-content');
            
            tabs.forEach(tab => tab.classList.remove('active'));
            contents.forEach(content => content.classList.remove('active'));
            
            // Show selected tab
            event.target.classList.add('active');
            document.getElementById(tabName).classList.add('active');
        }
    </script>
</body>
</html>
'''

def load_config():
    """Load MediaMTX configuration"""
    try:
        with open(CONFIG_FILE, 'r') as f:
            return yaml.safe_load(f)
    except Exception as e:
        return None

def save_config(config):
    """Save MediaMTX configuration"""
    try:
        # Create backup first
        backup_file = os.path.join(BACKUP_DIR, f'mediamtx.yml.{datetime.now().strftime("%Y%m%d_%H%M%S")}')
        subprocess.run(['cp', CONFIG_FILE, backup_file], check=True)
        
        # Save new config
        with open(CONFIG_FILE, 'w') as f:
            yaml.dump(config, f, default_flow_style=False, sort_keys=False)
        return True
    except Exception as e:
        return False

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

@app.route('/')
def index():
    config = load_config()
    
    if config is None:
        return "Error loading configuration file", 500
    
    # Get YAML content for advanced editor
    with open(CONFIG_FILE, 'r') as f:
        yaml_content = f.read()
    
    return render_template_string(
        HTML_TEMPLATE,
        config=config,
        yaml_content=yaml_content,
        service_status=get_service_status(),
        backups=get_backups(),
        message=request.args.get('message'),
        message_type=request.args.get('message_type', 'info')
    )

@app.route('/save_basic', methods=['POST'])
def save_basic():
    config = load_config()
    
    config['logLevel'] = request.form.get('logLevel')
    config['readTimeout'] = request.form.get('readTimeout')
    config['writeTimeout'] = request.form.get('writeTimeout')
    
    if save_config(config):
        return redirect('/?message=Basic settings saved successfully&message_type=success')
    else:
        return redirect('/?message=Failed to save settings&message_type=danger')

@app.route('/save_users', methods=['POST'])
def save_users():
    config = load_config()
    
    username = request.form.get('username')
    password = request.form.get('password')
    permissions = request.form.getlist('permissions')
    
    # Find or create user
    user_found = False
    for user in config['authInternalUsers']:
        if user['user'] == username:
            user['pass'] = password
            user['permissions'] = [{'action': perm, 'path': ''} for perm in permissions]
            user_found = True
            break
    
    if not user_found:
        # Add new user
        new_user = {
            'user': username,
            'pass': password,
            'ips': [],
            'permissions': [{'action': perm, 'path': ''} for perm in permissions]
        }
        # Insert before the 'any' user
        config['authInternalUsers'].insert(-1, new_user)
    
    if save_config(config):
        return redirect('/?message=User saved successfully&message_type=success')
    else:
        return redirect('/?message=Failed to save user&message_type=danger')

@app.route('/save_protocols', methods=['POST'])
def save_protocols():
    config = load_config()
    
    config['rtspAddress'] = f":{request.form.get('rtspAddress')}"
    config['rtspEncryption'] = request.form.get('rtspEncryption')
    config['rtmpAddress'] = f":{request.form.get('rtmpAddress')}"
    config['rtmpEncryption'] = request.form.get('rtmpEncryption')
    config['hlsAddress'] = f":{request.form.get('hlsAddress')}"
    config['hlsEncryption'] = request.form.get('hlsEncryption')
    config['srtAddress'] = f":{request.form.get('srtAddress')}"
    
    if save_config(config):
        return redirect('/?message=Protocol settings saved successfully&message_type=success')
    else:
        return redirect('/?message=Failed to save settings&message_type=danger')

@app.route('/save_yaml', methods=['POST'])
def save_yaml():
    yaml_content = request.form.get('yaml_content')
    
    try:
        # Validate YAML
        yaml.safe_load(yaml_content)
        
        # Create backup
        backup_file = os.path.join(BACKUP_DIR, f'mediamtx.yml.{datetime.now().strftime("%Y%m%d_%H%M%S")}')
        subprocess.run(['cp', CONFIG_FILE, backup_file], check=True)
        
        # Save new content
        with open(CONFIG_FILE, 'w') as f:
            f.write(yaml_content)
        
        return redirect('/?message=YAML saved successfully&message_type=success')
    except yaml.YAMLError as e:
        return redirect(f'/?message=Invalid YAML syntax: {str(e)}&message_type=danger')
    except Exception as e:
        return redirect(f'/?message=Failed to save: {str(e)}&message_type=danger')

@app.route('/validate_yaml', methods=['POST'])
def validate_yaml():
    yaml_content = request.form.get('yaml_content')
    
    try:
        yaml.safe_load(yaml_content)
        return redirect('/?message=YAML syntax is valid ✓&message_type=success')
    except yaml.YAMLError as e:
        return redirect(f'/?message=Invalid YAML syntax: {str(e)}&message_type=danger')

@app.route('/service/<action>', methods=['POST'])
def service_control(action):
    try:
        if action in ['start', 'stop', 'restart']:
            subprocess.run(['systemctl', action, SERVICE_NAME], check=True)
            return redirect(f'/?message=Service {action}ed successfully&message_type=success')
        else:
            return redirect('/?message=Invalid action&message_type=danger')
    except Exception as e:
        return redirect(f'/?message=Failed to {action} service: {str(e)}&message_type=danger')

@app.route('/backup', methods=['POST'])
def create_backup():
    try:
        backup_file = os.path.join(BACKUP_DIR, f'mediamtx.yml.{datetime.now().strftime("%Y%m%d_%H%M%S")}')
        subprocess.run(['cp', CONFIG_FILE, backup_file], check=True)
        return redirect('/?message=Backup created successfully&message_type=success')
    except Exception as e:
        return redirect(f'/?message=Failed to create backup: {str(e)}&message_type=danger')

@app.route('/restore/<backup_name>', methods=['POST'])
def restore_backup(backup_name):
    try:
        backup_file = os.path.join(BACKUP_DIR, backup_name)
        if not os.path.exists(backup_file):
            return redirect('/?message=Backup not found&message_type=danger')
        
        # Create a backup of current config before restoring
        current_backup = os.path.join(BACKUP_DIR, f'mediamtx.yml.pre_restore_{datetime.now().strftime("%Y%m%d_%H%M%S")}')
        subprocess.run(['cp', CONFIG_FILE, current_backup], check=True)
        
        # Restore
        subprocess.run(['cp', backup_file, CONFIG_FILE], check=True)
        
        # Restart service
        subprocess.run(['systemctl', 'restart', SERVICE_NAME], check=True)
        
        return redirect('/?message=Backup restored and service restarted&message_type=success')
    except Exception as e:
        return redirect(f'/?message=Failed to restore backup: {str(e)}&message_type=danger')

if __name__ == '__main__':
    # Check if config file exists
    if not os.path.exists(CONFIG_FILE):
        print(f"Error: MediaMTX configuration file not found at {CONFIG_FILE}")
        print("Please install MediaMTX first using the installation script.")
        exit(1)
    
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
