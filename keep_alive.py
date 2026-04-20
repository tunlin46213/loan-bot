import socket
import threading
import os

def run():
    port = int(os.environ.get("PORT", 8080))
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    # Allows bypassing port-in-use errors during quick restarts
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(('0.0.0.0', port))
    s.listen(5)
    print(f"Raw socket server running on port {port}")
    
    while True:
        try:
            conn, addr = s.accept()
            # Read first chunk so we don't break pipe
            conn.recv(1024)
            # Send valid barebones HTTP response
            response = b"HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\nContent-Length: 2\r\n\r\nOK"
            conn.sendall(response)
            conn.close()
        except Exception as e:
            print(f"Socket error: {e}")

def keep_alive():
    t = threading.Thread(target=run, daemon=True)
    t.start()
