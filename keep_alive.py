from threading import Thread
from http.server import BaseHTTPRequestHandler, HTTPServer
import os

class RequestHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-Type', 'text/plain')
        self.end_headers()
        self.wfile.write(b"Bot is alive!")

def run():
    port = int(os.environ.get("PORT", 8080))
    server_address = ('', port)
    httpd = HTTPServer(server_address, RequestHandler)
    print(f"Starting web server on port {port}...")
    httpd.serve_forever()

def keep_alive():
    t = Thread(target=run)
    t.start()
