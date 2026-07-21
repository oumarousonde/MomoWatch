import os, json
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from supabase import create_client

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            params = parse_qs(urlparse(self.path).query)
            boutique_id = params.get("boutique_id", [None])[0]

            if not boutique_id:
                self._rep(400, {"actif": False, "message": "boutique_id manquant"})
                return

            supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

            actif = bool(supabase.rpc("abonnement_actif", {
                "p_boutique_id": boutique_id
            }).execute().data)

            abo = supabase.table("abonnements").select("date_expiration") \
                .eq("boutique_id", boutique_id) \
                .eq("statut", "actif") \
                .order("date_expiration", desc=True) \
                .limit(1).execute()

            expire_le = abo.data[0]["date_expiration"] if abo.data else None

            self._rep(200, {"actif": actif, "expire_le": expire_le})
        except Exception as e:
            self._rep(500, {"actif": False, "message": str(e)})

    def _rep(self, code, data):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode())
