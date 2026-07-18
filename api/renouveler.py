import os, json
from http.server import BaseHTTPRequestHandler
from supabase import create_client

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        try:
            n = int(self.headers.get("Content-Length", 0))
            data = json.loads(self.rfile.read(n).decode())

            code        = (data.get("code") or "").strip().upper()
            boutique_id = (data.get("boutique_id") or "").strip()

            if not code or not boutique_id:
                self._rep(400, {
                    "succes": False,
                    "message": "Le code et l'identifiant de la boutique sont obligatoires"
                })
                return

            supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

            # On vérifie que la boutique existe déjà — le renouvellement ne crée
            # JAMAIS de nouvelle boutique, contrairement à l'activation initiale.
            boutique = supabase.table("boutiques").select("*").eq("id", boutique_id).execute().data
            if not boutique:
                self._rep(404, {"succes": False, "message": "Boutique introuvable"})
                return

            # On réutilise la même fonction que l'activation initiale, mais avec
            # le boutique_id EXISTANT au lieu d'en créer un nouveau : même
            # historique de transactions, même dashboard, rien n'est perdu.
            resultat = supabase.rpc("activer_code", {
                "p_code": code,
                "p_boutique_id": boutique_id
            }).execute().data

            if not resultat or not resultat.get("succes"):
                self._rep(400, resultat or {"succes": False, "message": "Code invalide"})
                return

            self._rep(200, {
                "succes": True,
                "message": "Abonnement renouvelé avec succès",
                "boutique_id": boutique_id,
                "nom_boutique": boutique[0]["nom_boutique"],
                "expire_le": resultat.get("expire_le")
            })
        except Exception as e:
            self._rep(500, {"succes": False, "message": str(e)})

    def do_GET(self):
        self._rep(200, {"statut": "Renouvellement MomoWatch ✅"})

    def _rep(self, code, data):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode())
