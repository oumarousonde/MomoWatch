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
            action = (data.get("action") or "connexion").strip()

            supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

            if action == "connexion":
                self._connexion(supabase, data)
            elif action == "changer_mot_de_passe":
                self._changer_mot_de_passe(supabase, data)
            elif action == "modifier_infos":
                self._modifier_infos(supabase, data)
            else:
                self._rep(400, {"succes": False, "message": "Action inconnue"})
        except Exception as e:
            self._rep(500, {"succes": False, "message": str(e)})

    def _connexion(self, supabase, data):
        boutique_id  = (data.get("boutique_id") or "").strip()
        mot_de_passe = (data.get("mot_de_passe") or "").strip()

        if not boutique_id or not mot_de_passe:
            self._rep(400, {"succes": False, "message": "Mot de passe requis"})
            return

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

    def _changer_mot_de_passe(self, supabase, data):
        boutique_id = (data.get("boutique_id") or "").strip()
        nouveau_mdp = (data.get("nouveau_mot_de_passe") or "").strip()
        ancien_mdp  = (data.get("ancien_mot_de_passe") or "").strip()

        if not boutique_id or not nouveau_mdp:
            self._rep(400, {"succes": False, "message": "Nouveau mot de passe requis"})
            return
        if len(nouveau_mdp) < 4:
            self._rep(400, {"succes": False, "message": "Le mot de passe doit faire au moins 4 caractères"})
            return

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

    def _modifier_infos(self, supabase, data):
        boutique_id  = (data.get("boutique_id") or "").strip()
        mot_de_passe = (data.get("mot_de_passe") or "").strip()

        if not boutique_id or not mot_de_passe:
            self._rep(400, {"succes": False, "message": "Mot de passe requis"})
            return

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

    def do_GET(self):
        self._rep(200, {"statut": "Compte boutique MomoWatch ✅"})

    def _rep(self, code, data):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode())
