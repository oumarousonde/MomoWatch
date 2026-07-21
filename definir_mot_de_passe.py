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

            boutique_id        = (data.get("boutique_id") or "").strip()
            nouveau_mdp        = (data.get("nouveau_mot_de_passe") or "").strip()
            ancien_mdp         = (data.get("ancien_mot_de_passe") or "").strip()

            if not boutique_id or not nouveau_mdp:
                self._rep(400, {"succes": False, "message": "Nouveau mot de passe requis"})
                return
            if len(nouveau_mdp) < 4:
                self._rep(400, {"succes": False, "message": "Le mot de passe doit faire au moins 4 caractères"})
                return

            supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
            boutique = supabase.table("boutiques").select("*").eq("id", boutique_id).execute().data

            if not boutique:
                self._rep(404, {"succes": False, "message": "Boutique introuvable"})
                return

            b = boutique[0]
            mdp_actuel = b.get("mot_de_passe")

            # Si un mot de passe existe déjà, l'ancien doit être fourni et correspondre
            # avant de pouvoir le changer — sinon n'importe qui pourrait le réinitialiser.
            if mdp_actuel:
                if not ancien_mdp or ancien_mdp != mdp_actuel:
                    self._rep(401, {"succes": False, "message": "Ancien mot de passe incorrect"})
                    return

            supabase.table("boutiques").update({"mot_de_passe": nouveau_mdp}).eq("id", boutique_id).execute()

            self._rep(200, {"succes": True, "message": "Mot de passe enregistré"})
        except Exception as e:
            self._rep(500, {"succes": False, "message": str(e)})

    def do_GET(self):
        self._rep(200, {"statut": "Définition mot de passe MomoWatch ✅"})

    def _rep(self, code, data):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode())
