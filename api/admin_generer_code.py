import os, json, random, string
from http.server import BaseHTTPRequestHandler
from supabase import create_client

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")

DUREES = {30: "1M", 90: "3M", 365: "12M"}


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        try:
            n = int(self.headers.get("Content-Length", 0))
            data = json.loads(self.rfile.read(n).decode())

            if not ADMIN_PASSWORD or data.get("mot_de_passe") != ADMIN_PASSWORD:
                self._rep(401, {"succes": False, "message": "Mot de passe incorrect"})
                return

            duree_jours = int(data.get("duree_jours", 30))
            if duree_jours not in DUREES:
                self._rep(400, {"succes": False, "message": "Durée invalide"})
                return

            supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

            # Génère un code unique (réessaie si collision, très improbable)
            for _ in range(5):
                suffixe = "".join(random.choices(string.ascii_uppercase + string.digits, k=4))
                code = f"MOMO-{DUREES[duree_jours]}-{suffixe}"
                existe = supabase.table("abonnements").select("id").eq("code", code).execute().data
                if not existe:
                    break

            supabase.table("abonnements").insert({
                "code": code,
                "duree_jours": duree_jours,
                "statut": "disponible"
            }).execute()

            self._rep(200, {"succes": True, "code": code})
        except Exception as e:
            self._rep(500, {"succes": False, "message": str(e)})

    def _rep(self, code, data):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode())
