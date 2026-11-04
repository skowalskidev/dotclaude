"""Read-only host probes for workspace-write workers; never execute worker commands."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import socket
import socketserver
import subprocess
import tempfile
import threading

ENV = 'LOCAL_CAPACITY_PROBE_SOCKET'
IOSTAT = ['/usr/sbin/iostat', '-d', '-C', '-n', '0', '-c', '2', '-w', '1']


def allowed(args):
    if args == IOSTAT or args in (
            ['/usr/bin/vm_stat'],
            ['/usr/sbin/sysctl', '-n', 'hw.memsize'],
            ['/usr/sbin/sysctl', '-n', 'kern.memorystatus_vm_pressure_level'],
            ['/bin/ps', '-axo', 'pid=,ppid=,pcpu=,etime=,command='],
            ['/bin/ps', '-axo', 'pgid=,stat=']):
        return True
    if len(args) != 5 or args[0] != '/bin/ps':
        return False
    if args[1] == '-p' and args[3] == '-o':
        return (args[2].isdigit() and int(args[2]) > 0 and
                args[4] in ('lstart=', 'pid=,ppid=,pgid=,lstart=,stat='))
    return args[1:4] == ['-o', 'comm=', '-p'] and args[4].isdigit() and int(args[4]) > 0


def probe(args, **kwargs):
    """Use the dispatcher's live host bridge when supplied, otherwise the ordinary OS probe.

    Missing/unreachable bridges fail closed through the caller's existing probe-error path.
    No cached reading, shell, signal or arbitrary executable crosses this interface.
    """
    path = os.environ.get(ENV)
    if not path:
        return subprocess.run(args, **kwargs)
    if not allowed(args):
        raise OSError('capacity bridge rejected probe')
    with socket.socket(socket.AF_UNIX) as client:
        client.settimeout(8)
        client.connect(path)
        client.sendall(json.dumps(args).encode() + b'\n')
        with client.makefile('rb') as stream:
            try:
                result = json.loads(stream.readline(8 * 1024 * 1024))
                if (not isinstance(result, dict) or type(result.get('returncode')) is not int
                        or not isinstance(result.get('stdout'), str) or not isinstance(result.get('stderr'), str)):
                    raise ValueError('invalid probe response')
            except (ValueError, UnicodeError) as exc:
                raise OSError('capacity host probe unavailable') from exc
    return subprocess.CompletedProcess(args, result['returncode'], result['stdout'], result['stderr'])


@contextmanager
def bridge(root):
    """Expose only fresh CPU, memory and process reads, for the lifetime of one dispatcher."""
    Path(root).mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='probe-', dir=root) as directory:
        path = str(Path(directory) / 'host.sock')

        class Handler(socketserver.StreamRequestHandler):
            def handle(self):
                self.connection.settimeout(8)
                try:
                    args = json.loads(self.rfile.readline(4096))
                    if not isinstance(args, list) or not all(isinstance(arg, str) for arg in args) or not allowed(args):
                        raise ValueError('unapproved probe')
                    result = subprocess.run(args, capture_output=True, text=True, timeout=5, check=False)
                    payload = dict(returncode=result.returncode, stdout=result.stdout, stderr=result.stderr)
                except (ValueError, OSError, subprocess.TimeoutExpired):
                    payload = dict(error='probe unavailable')
                self.wfile.write(json.dumps(payload).encode() + b'\n')

        with socketserver.ThreadingUnixStreamServer(path, Handler) as server:
            server.daemon_threads = True
            os.chmod(path, 0o600)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                yield path
            finally:
                server.shutdown()
                thread.join(timeout=2)
