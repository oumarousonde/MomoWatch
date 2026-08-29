import os, json
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler
from supabase import create_client

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")

class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        try:
            n = int(self.headers.get("Content-Length", 0))
            data = json.loads(self.rfile.read(n).decode())
            boutique_id = data.get("boutique_id")
            if not boutique_id:
                self._rep(400, {"statut": "erreur", "message": "boutique_id manquant"})
                return

            supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
            supabase.table("boutiques").update({
                "dernier_ping": datetime.now(timezone.utc).isoformat(),
                "file_attente": int(data.get("file_attente", 0)),
                "batterie": data.get("batterie"),
                "mode_avion": bool(data.get("mode_avion", False)),
                "sim_changee": bool(data.get("sim_changee", False))
            }).eq("id", boutique_id).execute()

            print("[MomoWatch] 💓 Ping reçu de " + str(boutique_id))
            self._rep(200, {"statut": "ok"})
        except Exception as e:
            import traceback
            traceback.print_exc()
            self._rep(500, {"statut": "erreur", "message": str(e)})

    def do_GET(self):
        self._rep(200, {"statut": "ping actif ✅"})

    def _rep(self, code, data):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode())