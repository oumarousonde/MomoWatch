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

            boutique_id = data.get("boutique_id")
            if not boutique_id:
                self._rep(400, {
                    "statut": "erreur",
                    "message": "boutique_id manquant — l'app n'est pas activée"
                })
                return

            supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

            # L'abonnement doit être actif pour accepter la transaction
            actif = supabase.rpc("abonnement_actif", {
                "p_boutique_id": boutique_id
            }).execute().data

            if not actif:
                self._rep(403, {"statut": "erreur", "message": "Abonnement inactif ou expiré"})
                return

            supabase.table("transactions").insert({
                "boutique_id": boutique_id,
                "client":      data.get("client", "Inconnu"),
                "montant":     float(str(data.get("montant", 0)).replace(" ", "")),
                "type":        data.get("type", ""),
                "operateur":   data.get("operateur", ""),
                "solde_apres": data.get("solde_apres")
            }).execute()

            self._rep(200, {"statut": "ok"})
        except Exception as e:
            self._rep(500, {"statut": "erreur", "message": str(e)})

    def do_GET(self):
        self._rep(200, {"statut": "MomoWatch actif ✅"})

    def _rep(self, code, data):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode())
