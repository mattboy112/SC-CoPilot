"""The app's real AI code (sc_brain) against the real service running locally.

Needs Node, the server's npm packages and Wrangler. Run from the repo root: python server/test/app_e2e.py
"""
import json
import os
import shutil
import signal
import ssl
import subprocess
import sys
import tempfile
import threading
import time
import types
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SERVER = ROOT / "server"
sys.path.insert(0, str(ROOT / "App"))
os.environ.setdefault("SC_COPILOT_HOME", tempfile.mkdtemp())

KEYS = {"PILOT-KEY": "ben-pilot", "CAPTAIN-KEY": "ben-captain"}
seen = {}


class Fake(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        raw = self.rfile.read(int(self.headers.get("content-length", 0)))
        if self.path == "/v1/customer-portal/license-keys/validate":
            key = json.loads(raw)["key"]
            if key not in KEYS:
                self.send_response(404)
                self.end_headers()
                return
            out = json.dumps({"status": "granted", "benefit_id": KEYS[key], "customer": {"email": "me@example.com"}}).encode()
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.end_headers()
            self.wfile.write(out)
            return
        body = json.loads(raw)
        seen["body"] = body
        said = json.dumps(body["messages"])
        web = 1 if any(str(t.get("type", "")).startswith("web_search") for t in body.get("tools", [])) and "search" in said else 0
        events = [
            {"type": "message_start", "message": {"id": "m", "model": body["model"], "usage": {"input_tokens": 900, "cache_read_input_tokens": 4100, "output_tokens": 1}}},
            {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}},
            {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "Copy that. Gear's down."}},
            {"type": "content_block_stop", "index": 0},
            {"type": "message_delta", "delta": {"stop_reason": "end_turn"}, "usage": {"output_tokens": 12, "server_tool_use": {"web_search_requests": web}}},
            {"type": "message_stop"},
        ]
        self.send_response(200)
        self.send_header("content-type", "text/event-stream")
        self.end_headers()
        for e in events:
            self.wfile.write(f"event: {e['type']}\ndata: {json.dumps(e)}\n\n".encode())


def main():
    fake = ThreadingHTTPServer(("127.0.0.1", 8788), Fake)
    threading.Thread(target=fake.serve_forever, daemon=True).start()
    state = tempfile.mkdtemp()
    (SERVER / ".dev.vars").write_text("\n".join([
        "ANTHROPIC_API_KEY=sk-test", "ANTHROPIC_URL=http://127.0.0.1:8788", "POLAR_API_URL=http://127.0.0.1:8788",
        "POLAR_ORG_ID=org", 'TIER_MAP={"ben-pilot":"pilot","ben-captain":"captain"}',
        'TIERS_JSON={"pilot":{"replies":3,"web":1,"perMinute":50},"captain":{"perMinute":50}}',
        "MANAGE_URL=https://example.com/portal", "KEY_PEPPER=test-pepper",
    ]))
    env = dict(os.environ, NO_PROXY="127.0.0.1,localhost", WRANGLER_SEND_METRICS="false")
    subprocess.run(["npx", "wrangler", "d1", "execute", "sc-copilot", "--local", "--persist-to", state, "--file=schema.sql"],
                   cwd=SERVER, env=env, check=True, capture_output=True)
    dev = subprocess.Popen(["npx", "wrangler", "dev", "--local", "--local-protocol", "https", "--port", "8787", "--ip", "127.0.0.1",
                            "--persist-to", state, "--show-interactive-dev-session=false"],
                           cwd=SERVER, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    insecure = ssl._create_unverified_context()
    try:
        for _ in range(120):
            try:
                urllib.request.urlopen("https://127.0.0.1:8787/health", context=insecure, timeout=2)
                break
            except Exception:
                time.sleep(0.5)

        import sc_brain as BR
        import sc_version as VER
        VER.SERVICE_URL = "https://127.0.0.1:8787"
        BR.ssl.create_default_context = lambda *a, **k: ssl._create_unverified_context()
        st = types.SimpleNamespace(lock=threading.RLock(), handle="Pilot", snapshot_text=lambda: "Zone: Stanton")
        app = types.SimpleNamespace(settings={"ai_mode": "service", "license_key": "PILOT-KEY", "web_lookups": True},
                                    state=st, note_system=lambda *a: None)
        b = BR.Brain(app)
        b.conn.ctx = insecure
        b.web_ok = True
        checks = []

        def check(name, cond):
            checks.append(("PASS" if cond else "FAIL", name))
            print(*checks[-1], sep="  ")

        reply = b.ask("gear down")
        body = seen["body"]
        check("answer comes back through the service", reply == "Copy that. Gear's down.")
        check("standard model, thinking off", body["model"] == "claude-haiku-5-5" and body.get("thinking") == {"type": "disabled"})
        check("instructions are cached", body["system"][0].get("cache_control") == {"type": "ephemeral"})
        check("conversation end is cached", body["messages"][-1]["content"][-1].get("cache_control") == {"type": "ephemeral"})
        sent = [t.get("name") for t in b._tools()]
        got = [t.get("name") for t in body.get("tools", [])]
        check(f"all {len(sent)} of the app's tools get through the safety filter", got == sent and len(sent) > 5)
        time.sleep(0.4)
        acct = b.account()
        line = BR.format_account(acct)
        check("account reads plan and usage", acct["plan"] == "pilot" and acct["usage"]["replies"] == 1 and acct["manage_url"])
        check(f"account line: {line}", line.startswith("Pilot · 1 of 3 replies this month · 0 of 1 web lookups · resets "))
        b.ask("search the web for the patch notes")
        time.sleep(0.4)
        b.ask("search again")
        check("web limit notice reaches the app", any("Web lookups are used up" in n for n in b.take_notices()))
        time.sleep(0.4)
        try:
            b.ask("one more")
            check("monthly limit is reported", False)
        except BR.ApiError as ex:
            check(f"monthly limit is reported: {ex}", ex.status == 429 and "Instant commands" in str(ex))
        app.settings.update(license_key="CAPTAIN-KEY", smart_mode=True)
        b.ask("tricky question")
        check("captain smart mode sends the smart model", seen["body"]["model"] == "claude-sonnet-5-5")
        app.settings.update(license_key="NOPE")
        try:
            b.ask("hello")
            check("bad key is reported", False)
        except BR.ApiError as ex:
            check(f"bad key is reported: {ex}", ex.status == 401)
        failed = [c for c in checks if c[0] == "FAIL"]
        print(f"\n{len(checks) - len(failed)} of {len(checks)} passed")
        return 1 if failed else 0
    finally:
        try:
            os.killpg(dev.pid, signal.SIGTERM)
        except Exception:
            pass
        fake.shutdown()
        (SERVER / ".dev.vars").unlink(missing_ok=True)
        shutil.rmtree(state, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
