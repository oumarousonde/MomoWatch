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

            code          = (data.get("code") or "").strip().upper()
            nom_boutique  = (data.get("nom_boutique") or "").strip()
            nom_dg        = (data.get("nom_dg") or "").strip()
            telephone     = (data.get("telephone") or "").strip()
            ville         = (data.get("ville") or "").strip()

            if not code or not nom_boutique or not nom_dg:
                self._rep(400, {
                    "succes": False,
                    "message": "Le code, le nom de la boutique et le nom du DG sont obligatoires"
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
                "ville": ville
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

    def do_GET(self):
        self._rep(200, {"statut": "Activation MomoWatch ✅"})

    def _rep(self, code, data):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode())
