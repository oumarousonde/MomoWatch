import os, json
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from supabase import create_client

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")

# Ce fichier regroupe 4 anciens endpoints (activer.py, renouveler.py,
# modifier_boutique.py, verifier.py) en un seul, pour rester sous la limite
# de 12 Serverless Functions du plan Hobby de Vercel. Le routage vers la
# bonne logique se fait via l'URL demandée (self.path), pas via un nouveau
# paramètre — donc les URLs /api/activer, /api/renouveler,
# /api/modifier_boutique et /api/verifier restent inchangées et
# fonctionnent exactement comme avant (important : l'APK Android déjà
# installé chez les boutiquiers appelle ces URLs telles quelles).


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
        elif chemin.endswith("/modifier_boutique"):
            self._modifier(data)
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

            # Vérifie d'abord si ce code existe déjà et est actif (reconnexion à une boutique existante,
            # par ex. depuis le dashboard web alors que l'APK l'a déjà activé)
            abonnement_existant = supabase.table("abonnements").select("*").eq("code", code).execute().data

            if abonnement_existant:
                a = abonnement_existant[0]
                if a["statut"] == "actif" and a.get("boutique_id"):
                    boutique_existante = supabase.table("boutiques").select("*").eq("id", a["boutique_id"]).execute().data
                    if boutique_existante:
                        # Même en reconnexion, le mot de passe doit correspondre —
                        # sinon n'importe qui connaissant un code déjà utilisé
                        # pourrait accéder à une boutique sans son mot de passe.
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

            # 1. Créer la boutique (première activation de ce code)
            boutique = supabase.table("boutiques").insert({
                "nom_boutique": nom_boutique,
                "nom_dg": nom_dg,
                "telephone": telephone,
                "ville": ville,
                "mot_de_passe": mot_de_passe
            }).execute()

            boutique_id = boutique.data[0]["id"]

            # 2. Activer le code d'abonnement pour cette boutique
            resultat = supabase.rpc("activer_code", {
                "p_code": code,
                "p_boutique_id": boutique_id
            }).execute().data

            if not resultat or not resultat.get("succes"):
                # Code invalide : on annule la boutique créée pour rien
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

    # ---------- modifier_boutique.py ----------
    def _modifier(self, data):
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

    def _rep(self, code, data):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode())
