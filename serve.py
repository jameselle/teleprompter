#!/usr/bin/env python3
"""Teleprompter: serves the prompter to the iPhone over HTTPS on the home Wi-Fi and saves each take to
~/Movies/Teleprompter.

Run:  python3 ~/teleprompter/serve.py   then open http://localhost:8792/setup on the Mac.

iOS Safari only opens the camera on a secure page, so the prompter is HTTPS (certs from make-cert.sh).
A second, plain-HTTP port hands the phone the CA profile, which can't be fetched over HTTPS before the
phone trusts it. Everything under /api needs the key from certs/token, so other devices on the Wi-Fi
can load the page but can't read the scripts or write files.
"""
import datetime
import json
import os
import plistlib
import re
import secrets
import shutil
import ssl
import subprocess
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent
SCRIPTS = ROOT / "scripts"
CERTS = ROOT / "certs"
OUT = Path(os.environ.get("TELEPROMPTER_OUT", str(Path.home() / "Movies" / "Teleprompter")))
PORT = int(os.environ.get("TELEPROMPTER_PORT", "8791"))
SETUP_PORT = PORT + 1
CHUNK = 1 << 20


def host():
    name = subprocess.run(["scutil", "--get", "LocalHostName"], capture_output=True, text=True).stdout.strip()
    return f"{name}.local" if name else "localhost"


def load_token():
    path = CERTS / "token"
    if not path.exists():
        path.write_text(secrets.token_urlsafe(18))
        path.chmod(0o600)
    return path.read_text().strip()


TOKEN = load_token()
HOST = host()
PROMPTER_URL = f"https://{HOST}:{PORT}/?k={TOKEN}"
CA_URL = f"http://{HOST}:{SETUP_PORT}/teleprompter.mobileconfig"

# Takes in progress: id -> {"part": Path, "dest": Path, "seq": next expected chunk}
takes = {}
takes_lock = threading.Lock()
SAFE = re.compile(r"[a-z0-9][a-z0-9-]{0,79}")
TAKE_NAME = re.compile(r"take-\d+\.(mp4|webm)")


def slug(text):
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:60] or "take"


def tool(name):
    found = shutil.which(name)
    if found:
        return found
    for folder in (Path.home() / ".local" / "bin", Path("/opt/homebrew/bin"), Path("/usr/local/bin")):
        if (folder / name).exists():
            return str(folder / name)
    return None


FFPROBE, FFMPEG = tool("ffprobe"), tool("ffmpeg")


def check_take(path):
    """Open the saved file the way an editor would, and report what's actually in it."""
    info = {"problems": []}
    if not FFPROBE:
        info["problems"].append("ffprobe isn't installed, so the file wasn't checked")
        return info
    try:
        out = subprocess.run(
            [FFPROBE, "-v", "error", "-show_entries",
             "format=duration:stream=codec_type,width,height:stream_side_data=rotation", "-of", "json", str(path)],
            capture_output=True, text=True, timeout=60)
        probe = json.loads(out.stdout or "{}")
    except (subprocess.TimeoutExpired, json.JSONDecodeError) as err:
        info["problems"].append(f"couldn't read the file ({err.__class__.__name__})")
        return info
    streams = probe.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    info["duration"] = round(float(probe.get("format", {}).get("duration") or 0), 1)
    if info["duration"] < 1:
        info["problems"].append("the file is empty or under a second long")
    if video:
        w, h = video.get("width"), video.get("height")
        rotation = next((d.get("rotation") for d in video.get("side_data_list", []) if "rotation" in d), 0)
        if rotation and abs(int(rotation)) % 180 == 90:
            w, h = h, w
        info["width"], info["height"] = w, h
    else:
        info["problems"].append("no picture in the file")
    if not audio:
        info["problems"].append("no sound in the file")
    elif FFMPEG:
        out = subprocess.run([FFMPEG, "-hide_banner", "-i", str(path), "-map", "0:a:0", "-af", "volumedetect",
                              "-f", "null", "-"], capture_output=True, text=True, timeout=180)
        m = re.search(r"max_volume:\s*(-?[\d.]+) dB", out.stderr)
        if m:
            info["audio_max_db"] = float(m.group(1))
            if info["audio_max_db"] < -35:
                info["problems"].append("the sound is very quiet: check the mic isn't covered")
    info["ok"] = not info["problems"]
    return info


def script_dir(script):
    return OUT / script


def read_choices(script):
    try:
        return json.loads((script_dir(script) / "choices.json").read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def write_choices(script, choices):
    path = script_dir(script) / "choices.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(choices, indent=2))


def list_takes(script):
    """Every section folder with its takes. The chosen take is the one you kept, else the newest."""
    base, choices, sections = script_dir(script), read_choices(script), {}
    if not base.exists():
        return sections
    for folder in sorted(p for p in base.iterdir() if p.is_dir() and not p.name.startswith("_")):
        items = []
        for f in sorted(folder.iterdir()):
            if TAKE_NAME.fullmatch(f.name):
                try:
                    meta = json.loads(f.with_suffix(".json").read_text())
                except (FileNotFoundError, json.JSONDecodeError):
                    meta = {}
                items.append({"name": f.name, **meta})
        if items:
            chosen = choices.get(folder.name)
            if chosen not in [i["name"] for i in items]:
                chosen = items[-1]["name"]
            sections[folder.name] = {"takes": items, "chosen": chosen, "kept": folder.name in choices}
    return sections


class Base(BaseHTTPRequestHandler):
    def send(self, code, body, ctype="application/json"):
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def body(self):
        remaining = int(self.headers.get("Content-Length", 0))
        while remaining > 0:
            block = self.rfile.read(min(CHUNK, remaining))
            if not block:
                raise ConnectionError("upload was cut short")
            remaining -= len(block)
            yield block

    def drain(self):
        # Read an upload we're refusing, so the phone gets the error instead of a dropped connection.
        for _ in self.body():
            pass

    def log_message(self, fmt, *args):
        if urlparse(self.path).path in ("/", "/index.html") or ("/api/takes" in self.path and "finish" in self.path):
            super().log_message(fmt, *args)


class Prompter(Base):
    def authed(self, key=None):
        if secrets.compare_digest(key if key is not None else self.headers.get("X-Key", ""), TOKEN):
            return True
        self.drain()
        self.send(403, {"error": "missing or wrong key: open the link from the setup page"})
        return False

    def take_path(self, query):
        """Resolve script/section/name from the query to a real take file, refusing anything else."""
        script, section, name = (query.get(k, [""])[0] for k in ("script", "section", "name"))
        if not (SAFE.fullmatch(script) and SAFE.fullmatch(section) and TAKE_NAME.fullmatch(name)):
            return None
        path = script_dir(script) / section / name
        return (script, section, path) if path.is_file() else None

    def send_file(self, path, ctype):
        # Byte ranges, because iOS Safari won't play a video without them.
        size = path.stat().st_size
        start, end, status = 0, size - 1, 200
        m = re.fullmatch(r"bytes=(\d*)-(\d*)", self.headers.get("Range", "").strip())
        if m and (m.group(1) or m.group(2)):
            if m.group(1):
                start = int(m.group(1))
                end = min(int(m.group(2)), size - 1) if m.group(2) else size - 1
            else:
                start = max(0, size - int(m.group(2)))
            if start > end:
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{size}")
                self.end_headers()
                return
            status = 206
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(end - start + 1))
        if status == 206:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()
        try:
            with open(path, "rb") as f:
                f.seek(start)
                remaining = end - start + 1
                while remaining > 0:
                    block = f.read(min(CHUNK, remaining))
                    if not block:
                        break
                    self.wfile.write(block)
                    remaining -= len(block)
        except (BrokenPipeError, ConnectionResetError, ssl.SSLError):
            pass  # the player moved on to another range; normal while scrubbing

    def do_GET(self):
        url = urlparse(self.path)
        query = parse_qs(url.query)
        if url.path in ("/", "/index.html"):
            return self.send(200, (ROOT / "index.html").read_bytes(), "text/html; charset=utf-8")
        if url.path == "/media":
            # A <video> tag can't send headers, so its key comes in the query string.
            if not self.authed(query.get("k", [""])[0]):
                return
            found = self.take_path(query)
            if not found:
                return self.send(404, {"error": "no such take"})
            return self.send_file(found[2], "video/webm" if found[2].suffix == ".webm" else "video/mp4")
        if not self.authed():
            return
        if url.path == "/api/scripts":
            items = [{"id": p.stem, "text": p.read_text()} for p in sorted(SCRIPTS.glob("*.txt"))]
            return self.send(200, {"scripts": items, "out": str(OUT)})
        if url.path == "/api/takes":
            script = query.get("script", [""])[0]
            if not SAFE.fullmatch(script):
                return self.send(400, {"error": "bad script"})
            return self.send(200, {"sections": list_takes(script), "folder": str(script_dir(script))})
        self.send(404, {"error": "not found"})

    def do_PUT(self):
        if not self.authed():
            return
        m = re.fullmatch(r"/api/scripts/([a-z0-9-]+)", urlparse(self.path).path)
        if not m:
            return self.send(404, {"error": "not found"})
        (SCRIPTS / f"{m.group(1)}.txt").write_bytes(b"".join(self.body()))
        self.send(200, {"ok": True})

    def do_POST(self):
        if not self.authed():
            return
        url = urlparse(self.path)
        query = parse_qs(url.query)

        if url.path == "/api/takes/start":
            script, section = query.get("script", [""])[0], query.get("section", [""])[0]
            if not (SAFE.fullmatch(script) and SAFE.fullmatch(section)):
                return self.send(400, {"error": "bad script or section"})
            ext = query.get("ext", ["mp4"])[0]
            ext = ext if ext in ("mp4", "webm") else "mp4"
            folder = script_dir(script) / section
            (folder / "_discarded").mkdir(parents=True, exist_ok=True)
            with takes_lock:
                used = [int(m.group(1)) for p in list(folder.iterdir()) + list((folder / "_discarded").iterdir())
                        if (m := re.match(r"take-(\d+)", p.name))]
                used += [int(re.match(r"take-(\d+)", t["dest"].name).group(1)) for t in takes.values()
                         if t["dest"].parent == folder]
                dest = folder / f"take-{max(used, default=0) + 1:02d}.{ext}"
                part = dest.with_name(dest.name + ".part")
                part.touch()
                take_id = uuid.uuid4().hex
                takes[take_id] = {"part": part, "dest": dest, "seq": 0}
            return self.send(200, {"id": take_id, "name": dest.name})

        if url.path in ("/api/takes/choose", "/api/takes/discard"):
            found = self.take_path(query)
            if not found:
                return self.send(404, {"error": "no such take"})
            script, section, path = found
            choices = read_choices(script)
            if url.path.endswith("choose"):
                choices[section] = path.name
            else:
                bin_ = path.parent / "_discarded"
                bin_.mkdir(exist_ok=True)
                path.rename(bin_ / path.name)
                if path.with_suffix(".json").exists():
                    path.with_suffix(".json").rename(bin_ / path.with_suffix(".json").name)
                if choices.get(section) == path.name:
                    choices.pop(section)
            write_choices(script, choices)
            return self.send(200, {"sections": list_takes(script)})

        m = re.fullmatch(r"/api/takes/([0-9a-f]{32})(/finish)?", url.path)
        take = takes.get(m.group(1)) if m else None
        if not take:
            self.drain()
            return self.send(404, {"error": "unknown take"})

        if m.group(2):  # finish: move into place, then check what actually landed on disk
            with takes_lock:
                takes.pop(m.group(1), None)
            take["part"].rename(take["dest"])
            meta = {"bytes": take["dest"].stat().st_size,
                    "saved": datetime.datetime.now().isoformat(timespec="seconds"), **check_take(take["dest"])}
            take["dest"].with_suffix(".json").write_text(json.dumps(meta, indent=2))
            return self.send(200, {"name": take["dest"].name, "path": str(take["dest"]), **meta})

        seq = int(query.get("seq", ["-1"])[0])
        if seq != take["seq"]:  # a chunk arriving out of order would corrupt the file
            self.drain()
            return self.send(409, {"error": f"expected chunk {take['seq']}, got {seq}"})
        data = b"".join(self.body())
        with open(take["part"], "ab") as f:
            f.write(data)
        take["seq"] += 1
        self.send(200, {"ok": True})


def mobileconfig():
    """The CA wrapped as an Apple configuration profile, the format iOS installs most reliably.
    UUIDs come from the certificate, so installing it again replaces the old one instead of adding a copy."""
    der = ssl.PEM_cert_to_DER_cert((CERTS / "ca.crt").read_text())
    seed = uuid.uuid5(uuid.NAMESPACE_URL, "teleprompter-ca:" + der.hex()[:64])
    cert = {
        "PayloadType": "com.apple.security.root", "PayloadVersion": 1,
        "PayloadIdentifier": "local.teleprompter.ca", "PayloadUUID": str(uuid.uuid5(seed, "cert")).upper(),
        "PayloadDisplayName": "Teleprompter Local CA", "PayloadCertificateFileName": "teleprompter-ca.cer",
        "PayloadContent": der,
    }
    profile = {
        "PayloadType": "Configuration", "PayloadVersion": 1,
        "PayloadIdentifier": "local.teleprompter", "PayloadUUID": str(uuid.uuid5(seed, "profile")).upper(),
        "PayloadDisplayName": f"Teleprompter ({HOST})",
        "PayloadDescription": "Lets this phone open the teleprompter on your Mac over a secure connection. "
                              "The certificate authority's key was deleted after signing the Mac's one certificate.",
        "PayloadRemovalDisallowed": False, "PayloadContent": [cert],
    }
    return plistlib.dumps(profile)


class Setup(Base):
    """Plain HTTP. The CA profile is public; the setup page carries the key, so only the Mac sees it."""

    def log_message(self, fmt, *args):
        BaseHTTPRequestHandler.log_message(self, fmt, *args)

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/teleprompter.mobileconfig":
            return self.send(200, mobileconfig(), "application/x-apple-aspen-config")
        if path == "/ca.crt":
            return self.send(200, (CERTS / "ca.crt").read_bytes(), "application/x-x509-ca-cert")
        if path in ("/", "/setup"):
            if self.client_address[0] not in ("127.0.0.1", "::1"):
                return self.send(403, b"Open the setup page on the Mac.", "text/plain")
            page = (ROOT / "setup.html").read_text()
            page = page.replace("__CA_URL__", CA_URL).replace("__PROMPTER_URL__", PROMPTER_URL)
            return self.send(200, page.encode(), "text/html; charset=utf-8")
        self.send(404, b"not found", "text/plain")


class QuietTLSServer(ThreadingHTTPServer):
    def handle_error(self, request, client_address):
        # One line instead of a traceback: a refused handshake here means the phone doesn't trust the cert yet.
        import sys
        err = sys.exc_info()[1]
        print(f"{client_address[0]} - TLS/connection error: {err.__class__.__name__}: {err}", flush=True)


def serve_https():
    httpd = QuietTLSServer(("0.0.0.0", PORT), Prompter)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(CERTS / "server.crt", CERTS / "server.key")
    # Handshake in the request thread, so one stalled client can't block every other connection.
    httpd.socket = ctx.wrap_socket(httpd.socket, server_side=True, do_handshake_on_connect=False)
    httpd.serve_forever()


if __name__ == "__main__":
    if not (CERTS / "server.crt").exists():
        raise SystemExit("No certificate yet. Run ./make-cert.sh first.")
    OUT.mkdir(parents=True, exist_ok=True)
    threading.Thread(target=serve_https, daemon=True).start()
    print(f"Setup page:  http://localhost:{SETUP_PORT}/setup   (open on the Mac)")
    print(f"Takes save to {OUT}")
    ThreadingHTTPServer(("0.0.0.0", SETUP_PORT), Setup).serve_forever()
