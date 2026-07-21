import os, json
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from supabase import create_client

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            params = parse_qs(urlparse(self.path).query)
            mdp = params.get("mot_de_passe", [None])[0]

            if not ADMIN_PASSWORD or mdp != ADMIN_PASSWORD:
                self._rep(401, {"succes": False, "message": "Mot de passe incorrect"})
                return

            supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

            codes = supabase.table("abonnements") \
                .select("*, boutiques(nom_boutique, nom_dg, telephone, ville)") \
                .order("created_at", desc=True) \
                .execute().data

            self._rep(200, {"succes": True, "codes": codes})
        except Exception as e:
            self._rep(500, {"succes": False, "message": str(e)})

    def _rep(self, code, data):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False, default=str).encode())
