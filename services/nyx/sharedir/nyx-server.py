import base64
import http.server
import json
import mimetypes
from urllib.parse import urlparse

PORT = 8080
dynamic_routes: dict[str, tuple[bytes, str]] = {}

NYX_HTML = b"""<html>
<head>
  <script>
    function log(msg) {
      Nyx.log(`[Domino] (${new Date().toISOString()}) ${msg}`)
    }

    setTimeout(async () => {
      try {
        if (!Nyx.isStarted()) {
          log("Creating snapshot")
          Nyx.start()

          log("Fetching buffer")
          const buffer = Nyx.getRawData()
          const decoder = new TextDecoder('utf-8')
          const { entryPoints, resources } = JSON.parse(decoder.decode(buffer))

          const resp = await fetch("/serve", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(resources)
          })

          if (!resp.ok) {
            throw new Error(`Web service returned ${resp.status}`)
          }

          const { fuzzer, objects, timeout } = entryPoints
          for (url of [fuzzer, objects, timeout]) {
            const script = document.createElement("script")
            script.src = `/${url}`
            script.defer = true
            log(`Attaching resource: ${url}`)
            document.body.appendChild(script)
          }
        }
      } catch (e) {
        log(`Error: ${e.message}`)
        Nyx.release()
      }
    }, 60000)
  </script>
</head>
</html>
"""


class NyxHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        path = urlparse(self.path).path

        if path == "/nyx_landing.html":
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(NYX_HTML)))
            self.end_headers()
            self.wfile.write(NYX_HTML)
            return

        if path in dynamic_routes:
            content, content_type = dynamic_routes[path]
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path != "/serve":
            self.send_response(404)
            self.end_headers()
            return

        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length)

        try:
            data = json.loads(body.decode("utf-8"))
            for filename, b64content in data.items():
                decoded = base64.b64decode(b64content)
                mime_type, _ = mimetypes.guess_type(filename)
                if not mime_type:
                    mime_type = "application/octet-stream"
                dynamic_routes[f"/{filename}"] = (decoded, mime_type)

            response = {"registered": list(data.keys())}
            encoded = json.dumps(response).encode("utf-8")

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        except Exception as e:
            error = {"error": str(e)}
            encoded = json.dumps(error).encode("utf-8")
            self.send_response(500)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)


if __name__ == "__main__":
    server = http.server.ThreadingHTTPServer(("0.0.0.0", PORT), NyxHandler)
    print(f"[*] Listening on http://localhost:{PORT}")
    server.serve_forever()
