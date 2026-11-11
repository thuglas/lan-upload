#!/usr/bin/env python3
"""
LAN Upload - a tiny drop-in file upload server for your local network.

Run this on the RECEIVING computer. From any other computer on the same
network, open the URL it prints in a web browser, pick a file, and upload it.
Files are saved into the current folder (or the folder given with --dir).

  * Nothing to install: uses only Python's standard library.
  * Only accepts connections from your local subnet by default.
  * Exits on its own after 10 minutes with no connections or transfers.
  * Stop it any time with Ctrl+C.

There is NO password / encryption. Only run it on networks you trust.
"""

import argparse
import http.server
import ipaddress
import os
import re
import socket
import socketserver
import sys
import threading
import time

__version__ = "1.0.0"

DEFAULT_PORT = 8000
DEFAULT_IDLE_MINUTES = 10
CHUNK = 1024 * 1024  # 1 MiB

PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><title>LAN Upload</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
 body{{font-family:system-ui,sans-serif;max-width:640px;margin:60px auto;padding:0 20px}}
 h1{{font-size:20px}} .box{{border:2px dashed #888;border-radius:10px;padding:30px;text-align:center}}
 button{{font-size:16px;padding:10px 22px;margin-top:14px;cursor:pointer}}
 #bar{{height:14px;background:#2d7;width:0;border-radius:7px;transition:width .2s}}
 #wrap{{background:#eee;border-radius:7px;margin-top:18px;display:none}}
 #msg{{margin-top:14px;font-size:15px}}
 .note{{color:#777;font-size:13px;margin-top:20px}}
</style></head>
<body>
<h1>Upload a file to {host}</h1>
<div class="box">
  <input type="file" id="f">
  <br><button id="btn" onclick="go()">Upload</button>
  <div id="wrap"><div id="bar"></div></div>
  <div id="msg"></div>
</div>
<p class="note">Keep this page open until the upload says "Saved".</p>
<script>
function go(){{
  var f=document.getElementById('f').files[0];
  if(!f){{alert('Pick a file first');return;}}
  var btn=document.getElementById('btn'); btn.disabled=true;
  var fd=new FormData(); fd.append('file',f);
  var x=new XMLHttpRequest(); x.open('POST','/',true);
  document.getElementById('wrap').style.display='block';
  x.upload.onprogress=function(e){{
    if(e.lengthComputable){{
      var p=Math.round(e.loaded/e.total*100);
      document.getElementById('bar').style.width=p+'%';
      document.getElementById('msg').textContent=p+'%  ('+
        (e.loaded/1073741824).toFixed(2)+' / '+(e.total/1073741824).toFixed(2)+' GB)';
    }}
  }};
  x.onload=function(){{document.getElementById('msg').textContent=x.responseText;btn.disabled=false;}};
  x.onerror=function(){{document.getElementById('msg').textContent='Upload failed.';btn.disabled=false;}};
  x.send(fd);
}}
</script>
</body></html>"""


# --------------------------------------------------------------------------
# Activity tracking (for the idle auto-exit)
# --------------------------------------------------------------------------
class Activity:
    """Thread-safe record of the last time anything happened."""

    def __init__(self):
        self._lock = threading.Lock()
        self._last = time.monotonic()
        self._active = 0

    def touch(self):
        with self._lock:
            self._last = time.monotonic()

    def start_transfer(self):
        with self._lock:
            self._active += 1
            self._last = time.monotonic()

    def end_transfer(self):
        with self._lock:
            self._active -= 1
            self._last = time.monotonic()

    def idle_seconds(self):
        """Seconds since last activity, or 0 while a transfer is running."""
        with self._lock:
            if self._active > 0:
                return 0.0
            return time.monotonic() - self._last


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
_BAD_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def safe_filename(name):
    """Strip any path and characters Windows doesn't allow in filenames."""
    name = name.replace("\\", "/").rsplit("/", 1)[-1]
    name = _BAD_CHARS.sub("_", name).strip(" .")
    return name or "upload.bin"


def unique_path(folder, filename):
    """Return a path in folder that doesn't clobber an existing file."""
    dest = os.path.join(folder, filename)
    base, ext = os.path.splitext(dest)
    n = 1
    while os.path.exists(dest) or os.path.exists(dest + ".part"):
        dest = f"{base}({n}){ext}"
        n += 1
    return dest


def lan_ip():
    """Best guess at this machine's LAN IPv4 address (no traffic is sent)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


def local_ipv4s():
    """All IPv4 addresses on this machine's network adapters (excl. loopback)."""
    ips = set()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ips.add(info[4][0])
    except OSError:
        pass
    ips.add(lan_ip())
    result = []
    for ip in ips:
        addr = ipaddress.ip_address(ip)
        if not (addr.is_loopback or addr.is_link_local or addr.is_unspecified):
            result.append(addr)
    return sorted(result)


def fmt_size(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.2f} {unit}" if unit != "B" else f"{n} B"
        n /= 1024


# --------------------------------------------------------------------------
# HTTP handler
# --------------------------------------------------------------------------
class Handler(http.server.BaseHTTPRequestHandler):
    server_version = f"LANUpload/{__version__}"

    # ---- access control -------------------------------------------------
    def _allowed(self):
        self.server.activity.touch()
        nets = self.server.allowed_nets
        if nets is None:
            return True
        try:
            ip = ipaddress.ip_address(self.client_address[0])
        except ValueError:
            ip = None
        if ip is not None and (ip.is_loopback or any(ip in n for n in nets)):
            return True
        print(f"  Blocked connection from {self.client_address[0]} (not on the allowed subnet)")
        self.send_error(403, "Uploads are only allowed from the local network")
        return False

    # ---- GET: the upload page ------------------------------------------
    def do_GET(self):
        if not self._allowed():
            return
        if self.path not in ("/", "/index.html"):
            self.send_error(404)
            return
        html = PAGE.format(host=socket.gethostname()).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(html)))
        self.end_headers()
        self.wfile.write(html)

    # ---- POST: receive one file ----------------------------------------
    def do_POST(self):
        if not self._allowed():
            return
        activity = self.server.activity
        activity.start_transfer()
        try:
            self._receive_upload(activity)
        finally:
            activity.end_transfer()

    def _receive_upload(self, activity):
        raw = self.headers.get("Content-Type", "")
        parts = [p.strip() for p in raw.split(";")]
        if not parts or parts[0] != "multipart/form-data":
            self.send_error(400, "Expected multipart/form-data")
            return
        boundary_val = None
        for seg in parts[1:]:
            if seg.startswith("boundary="):
                boundary_val = seg.split("=", 1)[1].strip().strip('"')
        if not boundary_val:
            self.send_error(400, "No multipart boundary")
            return
        boundary = b"--" + boundary_val.encode("utf-8")
        try:
            remaining = int(self.headers.get("Content-Length", 0))
        except ValueError:
            self.send_error(411, "Content-Length required")
            return

        # Read the first part's headers (we only handle one file field).
        line = self.rfile.readline(65536)
        remaining -= len(line)  # opening boundary
        filename = "upload.bin"
        while True:
            line = self.rfile.readline(65536)
            remaining -= len(line)
            if line in (b"\r\n", b"\n", b""):
                break
            decoded = line.decode("utf-8", "ignore")
            if decoded.lower().startswith("content-disposition"):
                for seg in decoded.split(";"):
                    seg = seg.strip()
                    if seg.startswith("filename="):
                        filename = safe_filename(seg.split("=", 1)[1].strip().strip('"'))

        dest = unique_path(self.server.save_dir, filename)
        tmp = dest + ".part"
        client = self.client_address[0]
        print(f"  Receiving {os.path.basename(dest)} from {client} ...")

        # Stream body to disk in chunks, watching for the closing boundary.
        delim = b"\r\n" + boundary
        buf = b""
        complete = False
        try:
            with open(tmp, "wb") as out:
                while remaining > 0:
                    data = self.rfile.read(min(CHUNK, remaining))
                    if not data:
                        break  # client disconnected
                    remaining -= len(data)
                    activity.touch()
                    buf += data
                    idx = buf.find(delim)
                    if idx != -1:
                        out.write(buf[:idx])
                        complete = True
                        break
                    # keep a tail in case the boundary straddles two chunks
                    if len(buf) > len(delim):
                        out.write(buf[:-len(delim)])
                        buf = buf[-len(delim):]
        except (ConnectionError, OSError) as e:
            print(f"  Upload of {os.path.basename(dest)} failed: {e}")

        if not complete:
            try:
                os.remove(tmp)
            except OSError:
                pass
            print(f"  Upload of {os.path.basename(dest)} was incomplete - partial file removed.")
            try:
                self.send_error(400, "Upload incomplete")
            except OSError:
                pass
            return

        # Drain whatever is left (closing boundary) so the browser gets a clean reply.
        while remaining > 0:
            data = self.rfile.read(min(CHUNK, remaining))
            if not data:
                break
            remaining -= len(data)

        os.replace(tmp, dest)
        msg = f"Saved as {os.path.basename(dest)} ({fmt_size(os.path.getsize(dest))})"
        print(f"  {msg}  <- {client}")
        body = msg.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


class Server(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = False  # don't silently share a port on Windows


# --------------------------------------------------------------------------
# Idle watchdog
# --------------------------------------------------------------------------
def start_idle_watchdog(server, idle_limit, minutes):
    def watch():
        while True:
            time.sleep(5)
            if server.activity.idle_seconds() >= idle_limit:
                print(f"\nNo connections or transfers for {minutes:g} minute(s) - shutting down.")
                server.timed_out = True
                server.shutdown()
                return

    threading.Thread(target=watch, daemon=True).start()


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------
def parse_args(argv=None):
    p = argparse.ArgumentParser(
        prog="lan-upload",
        description="Tiny LAN file upload server. Open the printed URL in a "
                    "browser on another computer to send a file here.")
    p.add_argument("-p", "--port", type=int, default=DEFAULT_PORT,
                   help=f"port to listen on (default {DEFAULT_PORT})")
    p.add_argument("-d", "--dir", default=None,
                   help="folder to save uploads into (default: current folder)")
    p.add_argument("-t", "--timeout", type=float, default=DEFAULT_IDLE_MINUTES,
                   metavar="MINUTES",
                   help=f"exit after this many idle minutes; 0 = never "
                        f"(default {DEFAULT_IDLE_MINUTES})")
    p.add_argument("-s", "--subnet", action="append", default=None, metavar="CIDR",
                   help="allowed client network, e.g. 192.168.1.0/24 "
                        "(repeatable; default: the /24 of each of this machine's adapters)")
    p.add_argument("--allow-any", action="store_true",
                   help="accept connections from ANY address (not just the local subnet)")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return p.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)

    save_dir = os.path.abspath(args.dir or os.getcwd())
    if not os.path.isdir(save_dir):
        print(f"Save folder does not exist: {save_dir}")
        return 2

    ip = lan_ip()
    if args.allow_any:
        allowed_nets = None
        allowed_desc = "ANY address (--allow-any)"
    else:
        try:
            if args.subnet:
                allowed_nets = [ipaddress.ip_network(s, strict=False) for s in args.subnet]
            else:
                # The /24 around every adapter on this machine (LAN, Wi-Fi, VM nets...)
                allowed_nets = sorted({ipaddress.ip_network(f"{a}/24", strict=False)
                                       for a in local_ipv4s()})
        except ValueError as e:
            print(f"Bad --subnet value: {e}")
            return 2
        allowed_desc = ", ".join(str(n) for n in allowed_nets) + " (plus this computer)"

    try:
        server = Server(("0.0.0.0", args.port), Handler)
    except OSError as e:
        print(f"Could not start on port {args.port}: {e}")
        print("Is another copy already running? Try a different port with --port 8080")
        return 1

    server.save_dir = save_dir
    server.allowed_nets = allowed_nets
    server.activity = Activity()
    server.timed_out = False

    idle_limit = int(args.timeout * 60)
    if idle_limit > 0:
        start_idle_watchdog(server, idle_limit, args.timeout)
        idle_desc = f"after {args.timeout:g} idle minute(s)"
    else:
        idle_desc = "never (--timeout 0)"

    print("=" * 60)
    print(f"  LAN Upload {__version__} is running.")
    print(f"  Saving uploads into: {save_dir}")
    print()
    print("  On the OTHER computer, open this in a web browser:")
    print(f"      http://{ip}:{args.port}")
    print()
    print(f"  Allowed clients : {allowed_desc}")
    print(f"  Auto-exit       : {idle_desc}")
    print("  Press Ctrl+C here to stop.")
    print("=" * 60)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
