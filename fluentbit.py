from http.server import BaseHTTPRequestHandler, HTTPServer


class LogHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length)

        print("\n===== REQUEST =====")
        print(f"Path: {self.path}")
        print(f"Content-Type: {self.headers.get('Content-Type')}")
        print(body.decode("utf-8", errors="replace"))
        print("===================\n")

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"result":"ok"}')

    def log_message(self, format, *args):
        print(format % args)


if __name__ == "__main__":
    server = HTTPServer(("0.0.0.0", 8080), LogHandler)
    print("Test API listening on http://localhost:8080")
    server.serve_forever()
