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

            print("[MomoWatch] Données reçues :", json.dumps(data))

            boutique_id = data.get("boutique_id")
            if not boutique_id:
                self._rep(400, {
                    "statut": "erreur",
                    "message": "boutique_id manquant — l'app n'est pas activée"
                })
                return

            supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

            # Vérifier que l'abonnement de la boutique est actif
            actif = supabase.rpc("abonnement_actif", {
                "p_boutique_id": boutique_id
            }).execute().data

            if not actif:
                self._rep(403, {"statut": "erreur", "message": "Abonnement inactif ou expiré"})
                return

            # ============================================================
            # ANTI-DOUBLON FIABLE : par ID de transaction (extrait du SMS)
            # ============================================================
            # L'ancien anti-doublon (client + montant + type + opérateur sur
            # 24h) est SUPPRIMÉ car il rejetait de VRAIES transactions :
            # un client qui retire 2 fois 5 000 FCFA le même jour, ou deux
            # clients homonymes, étaient ignorés à tort.
            #
            # Le nouvel anti-doublon se base sur l'identifiant unique présent
            # dans chaque SMS Orange Money / Moov Money ("Trans ID" / "tid").
            # Deux transactions légitimes n'ont JAMAIS le même ID.
            # ============================================================
            transaction_id = data.get("transaction_id")
            if transaction_id:
                verif = supabase.table("transactions").select("id")\
                    .eq("transaction_id", transaction_id)\
                    .execute()
                if verif.data:
                    print("[MomoWatch] Doublon confirmé (ID=" + str(transaction_id) + ") -> transaction déjà enregistrée, ignorée.")
                    # Code 200 : l'app Android retire ce SMS de sa file d'attente,
                    # tout est cohérent des deux côtés.
                    self._rep(200, {"statut": "doublon ignore"})
                    return

            # ============================================================
            # Insertion normale
            # ============================================================
            supabase.table("transactions").insert({
                "boutique_id": boutique_id,
                "client":      data.get("client", "Inconnu"),
                "telephone_client": data.get("telephone") or None,
                "montant":     float(str(data.get("montant", 0)).replace(" ", "")),
                "type":        data.get("type", ""),
                "operateur":   data.get("operateur", ""),
                "solde_apres": data.get("solde_apres"),
                "transaction_id": transaction_id  # peut être None (anciens formats), c'est OK
            }).execute()

            print("[MomoWatch] Transaction enregistrée avec succès (ID=" + str(transaction_id) + ")")
            self._rep(200, {"statut": "ok"})

        except Exception as e:
            import traceback
            traceback.print_exc()  # visible dans les logs Vercel pour le debug
            self._rep(500, {"statut": "erreur", "message": str(e)})

    def do_GET(self):
        self._rep(200, {"statut": "MomoWatch actif ✅"})

    def _rep(self, code, data):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode())