import os, json
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse
from supabase import create_client

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")

# Regroupe dashboard_connexion.py, definir_mot_de_passe.py et
# recuperer_acces.py — dispatch par URL (self.path), voir boutique.py
# pour le détail de pourquoi.


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        chemin = urlparse(self.path).path
        try:
            n = int(self.headers.get("Content-Length", 0))
            data = json.loads(self.rfile.read(n).decode())
        except Exception as e:
            self._rep(500, {"succes": False, "message": str(e)})
            return

        if chemin.endswith("/dashboard_connexion"):
            self._connexion(data)
        elif chemin.endswith("/definir_mot_de_passe"):
            self._definir_mot_de_passe(data)
        elif chemin.endswith("/recuperer_acces"):
            self._recuperer_acces(data)
        else:
            self._rep(404, {"succes": False, "message": "Endpoint inconnu"})

    def do_GET(self):
        self._rep(200, {"statut": "Auth MomoWatch ✅"})

    # ---------- dashboard_connexion.py ----------
    def _connexion(self, data):
        try:
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

            # Boutiques activées AVANT l'ajout de cette fonctionnalité : pas encore
            # de mot de passe enregistré. On laisse passer une seule fois mais on
            # signale au front qu'il doit en faire définir un immédiatement.
            if not b.get("mot_de_passe"):
                self._rep(200, {
                    "succes": True,
                    "mot_de_passe_a_definir": True,
                    "nom_boutique": b["nom_boutique"],
                    "nom_dg": b.get("nom_dg"),
                    "telephone": b.get("telephone"),
                    "ville": b.get("ville")
                })
                return

            if b.get("mot_de_passe") != mot_de_passe:
                self._rep(401, {"succes": False, "message": "Mot de passe incorrect"})
                return

            self._rep(200, {
                "succes": True,
                "mot_de_passe_a_definir": False,
                "nom_boutique": b["nom_boutique"],
                "nom_dg": b.get("nom_dg"),
                "telephone": b.get("telephone"),
                "ville": b.get("ville")
            })
        except Exception as e:
            self._rep(500, {"succes": False, "message": str(e)})

    # ---------- definir_mot_de_passe.py ----------
    def _definir_mot_de_passe(self, data):
        try:
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

    # ---------- recuperer_acces.py ----------
    def _recuperer_acces(self, data):
        try:
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

    def _rep(self, code, data):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode())
