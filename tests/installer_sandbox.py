"""A sandbox that runs the REAL installer scripts, with fake system commands (ops #1315).

No root, no network and no real MediaMTX are needed. The scripts run unchanged, except that the absolute
paths they write to (/usr/local, /etc/systemd/system, /opt/mediamtx-webeditor) are moved into a temp folder
and the "must be root" check is switched off, the same way the other tests sandbox the console file.
Everything else is the script as it is in the repository: that is what makes a test fail on the old script
for the right reason (the old script prints "is running!" while MediaMTX is down), not because a helper
function is missing.

Fake commands (made in `fakebin`, found first on PATH):
  systemctl   restart/start decide the state: the fake `mediamtx` binary is asked `--check CONFIG`; a binary
              that rejects the config leaves the unit failed. A binary whose first lines say `# flaps` is
              active for ONE check after the restart and then dies (systemd's 5 second restart loop).
  mediamtx    the "binary" in a release tarball. Its header lines say what it is:
                # fake-mediamtx vX.Y.Z
                # rejects: KEY      (it refuses a config that has a top-level KEY, like "unknown field")
                # flaps
  python3     `-m venv` makes a fake venv; `-m pip install` fails while FAKE_STATE/pip_fail exists;
              everything else (token_urlsafe, json) runs the real Python.
  curl, wget  answer from the fixtures the test made (latest release tag, tarball, checksums).
  apt-get, dnf, ufw, firewall-cmd, rpm, pgrep, restorecon, sleep, journalctl, uname, ffmpeg  recorded or no-ops.
  sed         on macOS only: makes GNU `sed -i` work with BSD sed. FAKE_KILL_SED=TEXT kills the script at its
              first `sed -i` whose arguments contain TEXT (a run that is stopped half way).
Every fake command appends its call to FAKE_STATE/calls.
"""
import hashlib
import io
import os
import platform
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
UBUNTU = os.path.join(ROOT, 'ubuntu-22.04', 'Ubuntu_22.04_MediaMTX_install.sh')
ROCKY = os.path.join(ROOT, 'rocky-9', 'Rocky_9_MediaMTX_install.sh')
EDITOR_INSTALLER = os.path.join(ROOT, 'config-editor', 'Install_MediaMTX_Config_Editor.sh')
VERSION = '9.9.9'
# Taken when this file is imported: another test in the same run may change sys.executable later.
REAL_PYTHON = sys.executable
REAL_SED = next(p for p in ('/usr/bin/sed', '/bin/sed') if os.path.exists(p))

# Upstream's shipped mediamtx.yml, cut down to what the Rocky installer edits.
UPSTREAM_CONFIG = """logLevel: info
api: no
apiAddress: :9997
apiAllowOrigins: ['*']
hlsTrustedProxies: []
webrtcTrustedProxies: []
authMethod: internal
authInternalUsers:
  # Default unprivileged user.
- user: any
  pass:
  ips: []
  permissions:
  - action: publish
  - action: read
  - action: playback
  # Localhost may do anything.
- user: any
  pass:
  ips: ['127.0.0.1', '::1']
  permissions:
  - action: api
moq: true
paths:
  all_others:
"""

FAKE_SYSTEMCTL = r'''#!/bin/bash
echo "systemctl $*" >> "$FAKE_STATE/calls"
cmd=$1; shift
case "$cmd" in
    restart|start)
        unit=${1%.service}
        if [ "$unit" = mediamtx ]; then
            bin="$FAKE_ROOT/usr/local/bin/mediamtx"
            if "$bin" --check "$FAKE_ROOT/usr/local/etc/mediamtx.yml" > /dev/null 2>&1; then
                if grep -q '^# flaps' "$bin"; then echo 1 > "$FAKE_STATE/left_$unit"; else echo 999999 > "$FAKE_STATE/left_$unit"; fi
            else
                echo 0 > "$FAKE_STATE/left_$unit"
            fi
        else
            echo 999999 > "$FAKE_STATE/left_$unit"
        fi
        exit 0 ;;
    is-active)
        [ "$1" = "--quiet" ] && shift
        unit=${1%.service}
        left=$(cat "$FAKE_STATE/left_$unit" 2>/dev/null || echo 0)
        if [ "$left" -gt 0 ]; then echo $((left - 1)) > "$FAKE_STATE/left_$unit"; echo active; exit 0; fi
        echo failed; exit 3 ;;
    *) exit 0 ;;
esac
'''

FAKE_MEDIAMTX_CHECK = r'''
if [ "$1" = "--check" ]; then
    for key in $(sed -n 's/^# rejects: //p' "$0"); do
        if grep -q "^$key:" "$2"; then
            echo "ERR: invalid configuration: json: unknown field \"$key\"" > "$FAKE_STATE/journal.txt"
            exit 1
        fi
    done
    exit 0
fi
if [ "$1" = "--version" ]; then sed -n 's/^# fake-mediamtx //p' "$0"; exit 0; fi
exit 0
'''

FAKE_PYTHON = r'''#!/bin/bash
echo "python3 $*" >> "$FAKE_STATE/calls"
REALPY="@REALPY@"
if [ "$1" = "-m" ] && [ "$2" = "venv" ]; then
    shift 2
    dir=""
    for a in "$@"; do
        case "$a" in
            --clear) clear=1 ;;
            --*) ;;
            *) dir=$a ;;
        esac
    done
    [ -n "${clear:-}" ] && rm -rf "$dir"
    mkdir -p "$dir/bin"
    printf 'home = /usr/bin\ncommand = /usr/bin/python3 -m venv --system-site-packages %s\n' "$dir" > "$dir/pyvenv.cfg"
    printf '#!/bin/bash\nexport REALPY="%s"\n' "$REALPY" > "$dir/bin/python3"
    cat >> "$dir/bin/python3" <<'INNER'
echo "venv-python $*" >> "$FAKE_STATE/calls"
here=$(cd "$(dirname "$0")/.." && pwd)
if [ "$1" = "-m" ] && [ "$2" = "pip" ]; then
    if [ -e "$FAKE_STATE/pip_fail" ]; then echo "pip: simulated failure (no network)" >&2; exit 1; fi
    touch "$here/.pip_ok"; exit 0
fi
case "$2" in
    *"import flask"*) [ -e "$here/.pip_ok" ]; exit $? ;;
    *"import psutil"*) exit 0 ;;
esac
exec "$REALPY" "$@"
INNER
    chmod 755 "$dir/bin/python3"
    printf '#!%s/bin/python3\n# pip\n' "$dir" > "$dir/bin/pip"
    chmod 755 "$dir/bin/pip"
    exit 0
fi
case "$2" in
    *version_info*) exit 0 ;;
esac
exec "$REALPY" "$@"
'''

FAKE_SED = r'''#!/bin/bash
if [ -n "${FAKE_KILL_SED:-}" ] && [[ " $* " == *" -i "* ]] && [[ "$*" == *"$FAKE_KILL_SED"* ]]; then
    echo "sed $* (killed)" >> "$FAKE_STATE/calls"; kill -9 $PPID; exit 137
fi
if [ "$(uname -s)" = Darwin ]; then
    args=()
    for a in "$@"; do
        if [ "$a" = "-i" ]; then args+=("-i" ""); else args+=("$a"); fi
    done
    exec /usr/bin/sed "${args[@]}"
fi
exec @REALSED@ "$@"
'''

SIMPLE = {
    'apt-get': 'exit 0',
    'dnf': 'exit 0',
    'ufw': 'exit 0',
    'restorecon': 'exit 0',
    'sleep': 'exit 0',
    'ffmpeg': 'echo "ffmpeg version fake"; exit 0',
    'pgrep': 'exit 1',
    'sync': 'exit 0',
    'uname': 'if [ "$1" = "-m" ]; then echo x86_64; else exec /usr/bin/uname "$@"; fi',
    'journalctl': 'cat "$FAKE_STATE/journal.txt" 2>/dev/null; exit 0',
    'curl': 'echo "{"; echo "  \\"tag_name\\": \\"v@VERSION@\\","; echo "}"',
    'rpm': 'if [ "$1" = "-E" ]; then echo 9; fi; exit 0',
    'firewall-cmd': 'if [ "$1" = "--state" ]; then echo running; fi; exit 0',
}


def _write_exe(path, text):
    with open(path, 'w') as f:
        f.write(text)
    os.chmod(path, os.stat(path).st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)


def fake_mediamtx(version='9.9.9', rejects=(), flaps=False):
    """The text of a fake MediaMTX binary."""
    head = '#!/bin/bash\n# fake-mediamtx v%s\n' % version
    for key in rejects:
        head += '# rejects: %s\n' % key
    if flaps:
        head += '# flaps\n'
    return head + FAKE_MEDIAMTX_CHECK


def binary_version(path):
    """The version a fake binary says it is, e.g. 'v1.0.0'."""
    with open(path) as f:
        for line in f:
            if line.startswith('# fake-mediamtx '):
                return line.split()[-1]
    return None


class Sandbox:
    def __init__(self, with_firewalld=False):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = os.path.realpath(self._tmp.name)
        self.root = os.path.join(self.dir, 'root')
        self.state = os.path.join(self.dir, 'state')
        self.fixtures = os.path.join(self.dir, 'fixtures')
        self.fakebin = os.path.join(self.dir, 'fakebin')
        self.work = os.path.join(self.dir, 'work')          # the "git checkout" the scripts run from
        for d in (self.state, self.fixtures, self.fakebin, self.work,
                  self.bin_dir, self.etc_dir, self.unit_dir, self.editor_dir):
            os.makedirs(d, exist_ok=True)
        self._make_fakes(with_firewalld)

    def cleanup(self):
        self._tmp.cleanup()

    # --- paths inside the sandbox -----------------------------------------------------------------
    @property
    def bin_dir(self):
        return os.path.join(self.root, 'usr', 'local', 'bin')

    @property
    def etc_dir(self):
        return os.path.join(self.root, 'usr', 'local', 'etc')

    @property
    def unit_dir(self):
        return os.path.join(self.root, 'etc', 'systemd', 'system')

    @property
    def editor_dir(self):
        return os.path.join(self.root, 'opt', 'mediamtx-webeditor')

    @property
    def binary(self):
        return os.path.join(self.bin_dir, 'mediamtx')

    @property
    def config(self):
        return os.path.join(self.etc_dir, 'mediamtx.yml')

    @property
    def unit(self):
        return os.path.join(self.unit_dir, 'mediamtx.service')

    @property
    def editor_unit(self):
        return os.path.join(self.unit_dir, 'mediamtx-webeditor.service')

    def read(self, path):
        with open(path) as f:
            return f.read()

    def write(self, path, text, mode=None):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w') as f:
            f.write(text)
        if mode:
            os.chmod(path, mode)

    def calls(self):
        try:
            return self.read(os.path.join(self.state, 'calls')).splitlines()
        except OSError:
            return []

    def backups(self, prefix):
        folder = os.path.dirname(prefix)
        base = os.path.basename(prefix)
        if not os.path.isdir(folder):
            return []
        return sorted(n for n in os.listdir(folder) if n.startswith(base))

    # --- building the fake world ---------------------------------------------------------------------
    def _make_fakes(self, with_firewalld):
        for name, body in SIMPLE.items():
            if name == 'firewall-cmd' and not with_firewalld:
                body = 'exit 252'          # "not running": a real firewall-cmd on the host must not be reached
            _write_exe(os.path.join(self.fakebin, name),
                       '#!/bin/bash\necho "%s $*" >> "$FAKE_STATE/calls"\n%s\n' % (name, body.replace('@VERSION@', VERSION)))
        _write_exe(os.path.join(self.fakebin, 'systemctl'), FAKE_SYSTEMCTL)
        _write_exe(os.path.join(self.fakebin, 'python3'), FAKE_PYTHON.replace('@REALPY@', REAL_PYTHON))
        _write_exe(os.path.join(self.fakebin, 'sed'), FAKE_SED.replace('@REALSED@', REAL_SED))
        _write_exe(os.path.join(self.fakebin, 'wget'), '''#!/bin/bash
echo "wget $*" >> "$FAKE_STATE/calls"
out=""; url=""
while [ $# -gt 0 ]; do
    case "$1" in
        -O) out=$2; shift 2 ;;
        -q) shift ;;
        *) url=$1; shift ;;
    esac
done
src="$FAKE_FIXTURES/$(basename "$url")"
[ -f "$src" ] || exit 8
cp "$src" "$out"
''')

    def release(self, binary_text, with_config=False):
        """Make the release the fake GitHub serves: a tarball with `binary_text` (and upstream's config)."""
        tarball = 'mediamtx_v%s_linux_amd64.tar.gz' % VERSION
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode='w:gz') as tf:
            data = binary_text.encode()
            info = tarfile.TarInfo('mediamtx')
            info.size, info.mode = len(data), 0o755
            tf.addfile(info, io.BytesIO(data))
            if with_config:
                cfg = UPSTREAM_CONFIG.encode()
                info = tarfile.TarInfo('mediamtx.yml')
                info.size, info.mode = len(cfg), 0o644
                tf.addfile(info, io.BytesIO(cfg))
        blob = buf.getvalue()
        with open(os.path.join(self.fixtures, tarball), 'wb') as f:
            f.write(blob)
        with open(os.path.join(self.fixtures, 'checksums.sha256'), 'w') as f:
            f.write('%s  %s\n' % (hashlib.sha256(blob).hexdigest(), tarball))

    def installed(self, binary_text=None, config=None):
        """A box that already has MediaMTX: its binary and its configuration."""
        if binary_text is not None:
            self.write(self.binary, binary_text, 0o755)
        if config is not None:
            self.write(self.config, config)

    def checkout(self, editor_version=None):
        """The folder the scripts run from. Copies the installer scripts and the editor's requirements."""
        for rel in ('ubuntu-22.04/Ubuntu_22.04_MediaMTX_install.sh', 'rocky-9/Rocky_9_MediaMTX_install.sh',
                    'config-editor/Install_MediaMTX_Config_Editor.sh'):
            src = os.path.join(ROOT, rel)
            dst = os.path.join(self.work, rel)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            with open(src, encoding='utf-8') as f:
                text = f.read()
            _write_exe(dst, self._sandbox_paths(text))
        for name in ('requirements.txt', 'requirements-psutil.txt'):
            shutil.copy(os.path.join(ROOT, 'config-editor', name), os.path.join(self.work, 'config-editor', name))
        # The editor file: a stub that says its version (the installer only copies it and reads that line).
        self.write(os.path.join(self.work, 'config-editor', 'mediamtx_config_editor.py'),
                   '# stub editor\nCURRENT_VERSION = "v%s"\n' % (editor_version or '2.1.21'))

    def _sandbox_paths(self, text):
        text = text.replace('[ "$EUID" -ne 0 ]', 'false')
        for a, b in (('/usr/local/', self.root + '/usr/local/'),
                     ('/etc/systemd/system/', self.unit_dir + '/'),
                     ('/opt/mediamtx-webeditor', self.editor_dir),
                     ('/etc/ssh/sshd_config', self.root + '/etc/ssh/sshd_config')):
            text = text.replace(a, b)
        return text

    def run(self, script, stdin='', env=None, timeout=120):
        """Run one installer script (a path relative to the checkout) and return the CompletedProcess."""
        e = dict(os.environ)
        e.update(PATH=self.fakebin + os.pathsep + os.environ['PATH'], FAKE_STATE=self.state,
                 FAKE_ROOT=self.root, FAKE_FIXTURES=self.fixtures, MTX_HEALTH_STEP='0')
        e.update(env or {})
        return subprocess.run(['bash', os.path.join(self.work, script)], cwd=self.work, env=e, input=stdin,
                              capture_output=True, text=True, timeout=timeout)


UBUNTU_SCRIPT = 'ubuntu-22.04/Ubuntu_22.04_MediaMTX_install.sh'
ROCKY_SCRIPT = 'rocky-9/Rocky_9_MediaMTX_install.sh'
EDITOR_SCRIPT = 'config-editor/Install_MediaMTX_Config_Editor.sh'
ROCKY_STDIN = 'tester\nSecretPass123\n'
