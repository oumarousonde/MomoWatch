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

            telephone    = (data.get("telephone") or "").strip()
            mot_de_passe = (data.get("mot_de_passe") or "").strip()

            if not telephone or not mot_de_passe:
                self._rep(400, {"succes": False, "message": "Téléphone et mot de passe requis"})
                return

            supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

            # On compare le téléphone en ne gardant que les chiffres des deux côtés,
            # pour éviter qu'un espace ou un indicatif en trop empêche la correspondance.
            telephone_nettoye = "".join(c for c in telephone if c.isdigit())

            boutiques = supabase.table("boutiques").select("*").execute().data
            trouvees = [
                b for b in boutiques
                if b.get("telephone")
                and "".join(c for c in b["telephone"] if c.isdigit()).endswith(telephone_nettoye[-8:])
                and b.get("mot_de_passe") == mot_de_passe
            ]

            if not trouvees:
                # Message volontairement vague : on ne précise pas si c'est le
                # téléphone ou le mot de passe qui ne correspond pas, pour ne pas
                # aider quelqu'un à deviner un numéro existant par élimination.
                self._rep(401, {"succes": False, "message": "Téléphone ou mot de passe incorrect"})
                return

            if len(trouvees) > 1:
                # Plusieurs boutiques partagent ce numéro et ce mot de passe : cas
                # rare mais possible (même gérant, plusieurs boutiques). On renvoie
                # la liste pour que le front laisse la personne choisir.
                self._rep(200, {
                    "succes": True,
                    "plusieurs": True,
                    "boutiques": [{"boutique_id": b["id"], "nom_boutique": b["nom_boutique"]} for b in trouvees]
                })
                return

            b = trouvees[0]
            self._rep(200, {
                "succes": True,
                "plusieurs": False,
                "boutique_id": b["id"],
                "nom_boutique": b["nom_boutique"],
                "nom_dg": b.get("nom_dg"),
                "telephone": b.get("telephone"),
                "ville": b.get("ville")
            })
        except Exception as e:
            self._rep(500, {"succes": False, "message": str(e)})

    def do_GET(self):
        self._rep(200, {"statut": "Récupération accès MomoWatch ✅"})

    def _rep(self, code, data):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode())
