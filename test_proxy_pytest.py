import os
import socket
import subprocess
import threading
import time

HOST = '127.0.0.1'
SERVER_PORT = 12345
PROXY_PORT = 5000


def run_server(collected):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind((HOST, SERVER_PORT))
        s.listen(1)
        conn, _ = s.accept()
        with conn:
            while True:
                data = conn.recv(1024)
                if not data:
                    break
                collected.append(data)


def start_proxy():
    subprocess.check_call(['gcc', '-O2', '-Wall', '-o', 'tcp_proxy_oneway', 'tcp_proxy_oneway.c'])
    return subprocess.Popen(['./tcp_proxy_oneway', HOST, str(SERVER_PORT)], stdout=subprocess.PIPE)


def test_proxy_forwarding(tmp_path):
    collected = []
    server_thread = threading.Thread(target=run_server, args=(collected,))
    server_thread.start()
    proxy = start_proxy()
    time.sleep(0.5)

    with socket.create_connection((HOST, PROXY_PORT)) as s:
        s.sendall(b'hello test')
    time.sleep(0.5)

    proxy.terminate()
    server_thread.join()

    assert b'hello test' in b''.join(collected)
    assert b'hello test' in proxy.stdout.read()
