import os, json, hmac, hashlib, time
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from supabase import create_client

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")

TOLERANCE_SECONDES = 300  # anti-rejeu, comme recommandé par Wave


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self._rep(200, {"statut": "Wave webhook MomoWatch ✅"})

    def do_POST(self):
        # Chaque boutique a sa PROPRE URL de webhook, avec son boutique_id
        # dedans — ex: /api/wave-webhook?boutique_id=abc-123.
        # C'est ce qui permet de savoir quel secret utiliser pour vérifier
        # la signature, et où enregistrer la transaction, SANS dépendre de
        # quoi que ce soit dans les données envoyées par Wave lui-même
        # (qui ne connaît rien de MomoWatch).
        params = parse_qs(urlparse(self.path).query)
        boutique_id = params.get("boutique_id", [None])[0]

        if not boutique_id:
            self._rep(400, {"succes": False, "message": "boutique_id manquant dans l'URL du webhook"})
            return

        try:
            n = int(self.headers.get("Content-Length", 0))
            corps_brut = self.rfile.read(n)
        except Exception as e:
            self._rep(400, {"succes": False, "message": str(e)})
            return

        signature_recue = self.headers.get("Wave-Signature", "")

        try:
            supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
            config = supabase.table("wave_config").select("*") \
                .eq("boutique_id", boutique_id).eq("actif", True).execute().data
        except Exception as e:
            self._rep(500, {"succes": False, "message": str(e)})
            return

        if not config:
            self._rep(404, {"succes": False, "message": "Configuration Wave introuvable pour cette boutique"})
            return

        secret = config[0]["secret_webhook"]

        if not self._signature_valide(corps_brut, signature_recue, secret):
            self._rep(401, {"succes": False, "message": "Signature invalide"})
            return

        try:
            evenement = json.loads(corps_brut.decode("utf-8"))
        except Exception:
            self._rep(400, {"succes": False, "message": "JSON invalide"})
            return

        type_evenement = evenement.get("type", "")
        data = evenement.get("data", {})

        if type_evenement in ("merchant.payment_received", "b2b.payment_received"):
            self._enregistrer_paiement(supabase, boutique_id, data)
        # Les autres types (test.test_event, checkout.*, *.payment_failed)
        # sont accusés reception sans action.

        self._rep(200, {"succes": True})

    def _signature_valide(self, corps_brut, signature_recue, secret):
        if not secret or not signature_recue:
            return False
        try:
            morceaux = signature_recue.split(",")
            timestamp = None
            signatures_recues = []
            for m in morceaux:
                cle, _, valeur = m.partition("=")
                if cle == "t":
                    timestamp = valeur
                elif cle == "v1":
                    signatures_recues.append(valeur)

            if not timestamp or not signatures_recues:
                return False
            if abs(time.time() - int(timestamp)) > TOLERANCE_SECONDES:
                return False

            payload = timestamp.encode("utf-8") + corps_brut
            signature_calculee = hmac.new(
                secret.encode("utf-8"), payload, hashlib.sha256
            ).hexdigest()

            return any(
                hmac.compare_digest(signature_calculee, s) for s in signatures_recues
            )
        except Exception:
            return False

    def _enregistrer_paiement(self, supabase, boutique_id, data):
        try:
            montant = float(data.get("amount", 0) or 0)
            numero_client = data.get("sender_mobile") or data.get("sender_id") or None

            supabase.table("transactions").insert({
                "boutique_id": boutique_id,
                "client": "Inconnu",
                "telephone_client": numero_client,
                "montant": montant,
                "type": "Dépôt",
                "operateur": "Wave",
                "solde_apres": None
            }).execute()
        except Exception:
            pass

    def _rep(self, code, data):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode())
