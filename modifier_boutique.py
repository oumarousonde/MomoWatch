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

            boutique_id  = (data.get("boutique_id") or "").strip()
            mot_de_passe = (data.get("mot_de_passe") or "").strip()

            if not boutique_id or not mot_de_passe:
                self._rep(400, {"succes": False, "message": "Mot de passe requis"})
                return

            supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
            boutique = supabase.table("boutiques").select("*").eq("id", boutique_id).execute().data

            if not boutique:
                self._rep(404, {"succes": False, "message": "Boutique introuvable"})
                return

            b = boutique[0]

            # Même vérification que pour l'accès au dashboard : on ne modifie rien
            # sans le bon mot de passe, même en connaissant le boutique_id.
            if b.get("mot_de_passe") and b.get("mot_de_passe") != mot_de_passe:
                self._rep(401, {"succes": False, "message": "Mot de passe incorrect"})
                return

            champs_modifiables = ["nom_boutique", "nom_dg", "telephone", "ville"]
            mise_a_jour = {}
            for champ in champs_modifiables:
                valeur = data.get(champ)
                if valeur is not None and str(valeur).strip():
                    mise_a_jour[champ] = str(valeur).strip()

            if not mise_a_jour:
                self._rep(400, {"succes": False, "message": "Aucune information à modifier"})
                return

            supabase.table("boutiques").update(mise_a_jour).eq("id", boutique_id).execute()

            self._rep(200, {"succes": True, "message": "Informations mises à jour"})
        except Exception as e:
            self._rep(500, {"succes": False, "message": str(e)})

    def do_GET(self):
        self._rep(200, {"statut": "Modification boutique MomoWatch ✅"})

    def _rep(self, code, data):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode())
