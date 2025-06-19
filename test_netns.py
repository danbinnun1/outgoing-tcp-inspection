import os
import subprocess
import textwrap
import tempfile


def _run_unshare(script: str):
    cmd = [
        'unshare',
        '--user', '--map-root-user',
        '--net', '--mount', '--pid', '--fork',
        'python3', '-c', script
    ]
    subprocess.check_call(cmd)


def test_router_topology(tmp_path):
    subprocess.check_call(['gcc', '-O2', '-Wall', '-o', 'tcp_proxy_oneway', 'tcp_proxy_oneway.c'])

    script = textwrap.dedent(f"""
    import os, subprocess, socket, time
    base = '{tmp_path}'
    ns_dir = os.path.join(base, 'netns')
    os.makedirs(ns_dir, exist_ok=True)
    os.makedirs('/run/netns', exist_ok=True)
    subprocess.run(['mount', '--bind', ns_dir, '/run/netns'], check=True)
    subprocess.run(['mount', '--make-private', '/run/netns'], check=True)
    subprocess.run(['ip', 'netns', 'add', 'server'], check=True)
    subprocess.run(['ip', 'netns', 'add', 'router'], check=True)
    subprocess.run(['ip', 'netns', 'add', 'client'], check=True)
    subprocess.run(['ip', 'link', 'add', 'veth_c', 'type', 'veth', 'peer', 'name', 'veth_r1'], check=True)
    subprocess.run(['ip', 'link', 'add', 'veth_r2', 'type', 'veth', 'peer', 'name', 'veth_s'], check=True)
    subprocess.run(['ip', 'link', 'set', 'veth_c', 'netns', 'client'], check=True)
    subprocess.run(['ip', 'link', 'set', 'veth_r1', 'netns', 'router'], check=True)
    subprocess.run(['ip', 'link', 'set', 'veth_r2', 'netns', 'router'], check=True)
    subprocess.run(['ip', 'link', 'set', 'veth_s', 'netns', 'server'], check=True)
    subprocess.run(['ip', '-n', 'client', 'addr', 'add', '10.0.0.2/24', 'dev', 'veth_c'], check=True)
    subprocess.run(['ip', '-n', 'client', 'link', 'set', 'veth_c', 'up'], check=True)
    subprocess.run(['ip', '-n', 'client', 'link', 'set', 'lo', 'up'], check=True)
    subprocess.run(['ip', '-n', 'client', 'route', 'add', 'default', 'via', '10.0.0.1'], check=True)
    subprocess.run(['ip', '-n', 'router', 'addr', 'add', '10.0.0.1/24', 'dev', 'veth_r1'], check=True)
    subprocess.run(['ip', '-n', 'router', 'addr', 'add', '10.0.1.1/24', 'dev', 'veth_r2'], check=True)
    subprocess.run(['ip', '-n', 'router', 'link', 'set', 'veth_r1', 'up'], check=True)
    subprocess.run(['ip', '-n', 'router', 'link', 'set', 'veth_r2', 'up'], check=True)
    subprocess.run(['ip', '-n', 'router', 'link', 'set', 'lo', 'up'], check=True)
    subprocess.run(['ip', '-n', 'server', 'addr', 'add', '10.0.1.2/24', 'dev', 'veth_s'], check=True)
    subprocess.run(['ip', '-n', 'server', 'link', 'set', 'veth_s', 'up'], check=True)
    subprocess.run(['ip', '-n', 'server', 'link', 'set', 'lo', 'up'], check=True)
    subprocess.run(['ip', '-n', 'server', 'route', 'add', 'default', 'via', '10.0.1.1'], check=True)

    srv_log = os.path.join(base, 'srv.log')
    server = subprocess.Popen([
        'ip', 'netns', 'exec', 'server', 'python3', '-u', '-c',
        f"import socket,sys;s=socket.socket();s.bind(('10.0.1.2',12345));s.listen(1);c,_=s.accept();data=c.recv(1024);open('{tmp_path}/srv.log','wb').write(data);c.sendall(b'ok');c.close();s.close()"
    ])
    proxy = subprocess.Popen([
        'ip', 'netns', 'exec', 'router', '/workspace/outgoing-tcp-inspection/tcp_proxy_oneway',
        '10.0.1.2', '12345'
    ], stdout=subprocess.PIPE)
    time.sleep(0.5)
    subprocess.run([
        'ip', 'netns', 'exec', 'client', 'python3', '-u', '-c',
        "import socket;s=socket.create_connection(('10.0.0.1',5000));s.sendall(b'hello');s.close()"
    ], check=True)
    time.sleep(0.5)
    proxy.terminate(); server.terminate()
    proxy_out = proxy.stdout.read()
    with open(srv_log, 'rb') as f:
        server_out = f.read()
    subprocess.run(['ip', 'netns', 'del', 'server'])
    subprocess.run(['ip', 'netns', 'del', 'router'])
    subprocess.run(['ip', 'netns', 'del', 'client'])
    subprocess.run(['umount', '/run/netns'])
    assert b'hello' in proxy_out
    assert b'hello' in server_out
    """)

    _run_unshare(script)
