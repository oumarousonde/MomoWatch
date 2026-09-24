import os, json
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from supabase import create_client

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")

# Regroupe activer.py, renouveler.py, verifier.py, recuperer_acces.py et
# compte_boutique.py — dispatch par URL (self.path) pour les 4 premiers
# (les URLs d'origine restent inchangées, donc rien à modifier côté APK
# Android déjà distribué), et par "action" pour compte_boutique (déjà ainsi
# avant la fusion, on garde ce fonctionnement tel quel).


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        chemin = urlparse(self.path).path
        try:
            n = int(self.headers.get("Content-Length", 0))
            data = json.loads(self.rfile.read(n).decode())
        except Exception as e:
            self._rep(500, {"succes": False, "message": str(e)})
            return

        if chemin.endswith("/activer"):
            self._activer(data)
        elif chemin.endswith("/renouveler"):
            self._renouveler(data)
        elif chemin.endswith("/recuperer_acces"):
            self._recuperer_acces(data)
        elif chemin.endswith("/compte_boutique"):
            self._compte_boutique(data)
        else:
            self._rep(404, {"succes": False, "message": "Endpoint inconnu"})

    def do_GET(self):
        chemin = urlparse(self.path).path
        if chemin.endswith("/verifier"):
            self._verifier()
        else:
            self._rep(200, {"statut": "Boutique MomoWatch ✅"})

    # ---------- activer.py ----------
    def _activer(self, data):
        try:
            code          = (data.get("code") or "").strip().upper()
            nom_boutique  = (data.get("nom_boutique") or "").strip()
            nom_dg        = (data.get("nom_dg") or "").strip()
            telephone     = (data.get("telephone") or "").strip()
            ville         = (data.get("ville") or "").strip()
            mot_de_passe  = (data.get("mot_de_passe") or "").strip()

            if not code or not nom_boutique or not nom_dg or not mot_de_passe:
                self._rep(400, {
                    "succes": False,
                    "message": "Le code, le nom de la boutique, le nom du DG et le mot de passe sont obligatoires"
                })
                return

            supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

            abonnement_existant = supabase.table("abonnements").select("*").eq("code", code).execute().data

            if abonnement_existant:
                a = abonnement_existant[0]
                if a["statut"] == "actif" and a.get("boutique_id"):
                    boutique_existante = supabase.table("boutiques").select("*").eq("id", a["boutique_id"]).execute().data
                    if boutique_existante:
                        if boutique_existante[0].get("mot_de_passe") != mot_de_passe:
                            self._rep(401, {"succes": False, "message": "Mot de passe incorrect"})
                            return
                        self._rep(200, {
                            "succes": True,
                            "message": "Connecté à la boutique existante",
                            "boutique_id": a["boutique_id"],
                            "nom_boutique": boutique_existante[0]["nom_boutique"],
                            "expire_le": a.get("date_expiration")
                        })
                        return
                elif a["statut"] != "disponible":
                    self._rep(400, {"succes": False, "message": "Ce code n'est plus disponible"})
                    return

            boutique = supabase.table("boutiques").insert({
                "nom_boutique": nom_boutique,
                "nom_dg": nom_dg,
                "telephone": telephone,
                "ville": ville,
                "mot_de_passe": mot_de_passe
            }).execute()

            boutique_id = boutique.data[0]["id"]

            resultat = supabase.rpc("activer_code", {
                "p_code": code,
                "p_boutique_id": boutique_id
            }).execute().data

            if not resultat or not resultat.get("succes"):
                supabase.table("boutiques").delete().eq("id", boutique_id).execute()
                self._rep(400, resultat or {"succes": False, "message": "Code invalide"})
                return

            self._rep(200, {
                "succes": True,
                "message": "Boutique activée avec succès",
                "boutique_id": boutique_id,
                "nom_boutique": nom_boutique,
                "expire_le": resultat.get("expire_le")
            })
        except Exception as e:
            self._rep(500, {"succes": False, "message": str(e)})

    # ---------- renouveler.py ----------
    def _renouveler(self, data):
        try:
            code        = (data.get("code") or "").strip().upper()
            boutique_id = (data.get("boutique_id") or "").strip()

            if not code or not boutique_id:
                self._rep(400, {
                    "succes": False,
                    "message": "Le code et l'identifiant de la boutique sont obligatoires"
                })
                return

            supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

            boutique = supabase.table("boutiques").select("*").eq("id", boutique_id).execute().data
            if not boutique:
                self._rep(404, {"succes": False, "message": "Boutique introuvable"})
                return

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

    # ---------- verifier.py ----------
    def _verifier(self):
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

    # ---------- recuperer_acces.py ----------
    def _recuperer_acces(self, data):
        try:
            telephone    = (data.get("telephone") or "").strip()
            mot_de_passe = (data.get("mot_de_passe") or "").strip()

            if not telephone or not mot_de_passe:
                self._rep(400, {"succes": False, "message": "Téléphone et mot de passe requis"})
                return

            supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

            telephone_nettoye = "".join(c for c in telephone if c.isdigit())

            boutiques = supabase.table("boutiques").select("*").execute().data
            trouvees = [
                b for b in boutiques
                if b.get("telephone")
                and "".join(c for c in b["telephone"] if c.isdigit()).endswith(telephone_nettoye[-8:])
                and b.get("mot_de_passe") == mot_de_passe
            ]

            if not trouvees:
                self._rep(401, {"succes": False, "message": "Téléphone ou mot de passe incorrect"})
                return

            if len(trouvees) > 1:
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

    # ---------- compte_boutique.py ----------
    def _compte_boutique(self, data):
        try:
            action = (data.get("action") or "connexion").strip()
            supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

            if action == "connexion":
                self._cb_connexion(supabase, data)
            elif action == "changer_mot_de_passe":
                self._cb_changer_mot_de_passe(supabase, data)
            elif action == "modifier_infos":
                self._cb_modifier_infos(supabase, data)
            else:
                self._rep(400, {"succes": False, "message": "Action inconnue"})
        except Exception as e:
            self._rep(500, {"succes": False, "message": str(e)})

    def _cb_connexion(self, supabase, data):
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

    def _cb_changer_mot_de_passe(self, supabase, data):
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

        if mdp_actuel:
            if not ancien_mdp or ancien_mdp != mdp_actuel:
                self._rep(401, {"succes": False, "message": "Ancien mot de passe incorrect"})
                return

        supabase.table("boutiques").update({"mot_de_passe": nouveau_mdp}).eq("id", boutique_id).execute()
        self._rep(200, {"succes": True, "message": "Mot de passe enregistré"})

    def _cb_modifier_infos(self, supabase, data):
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

    def _rep(self, code, data):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode())
