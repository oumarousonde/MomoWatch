from http.server import BaseHTTPRequestHandler
import json
import os
import urllib.request

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")

def sauvegarder_transaction(client, montant, type_op, operateur):
    url = f"{SUPABASE_URL}/rest/v1/transactions"
    payload = json.dumps({
        "client": client,
        "montant": float(str(montant).replace(" ", "")),
        "type": type_op,
        "operateur": operateur
    }).encode("utf-8")
    req = urllib.request.Request(
        url, data=payload,
        headers={
            "Content-Type": "application/json",
            "apikey": SUPABASE_KEY,
            "Authorization": f"Bearer {SUPABASE_KEY}",
            "Prefer": "return=minimal"
        },
        method="POST"
    )
    urllib.request.urlopen(req)

class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        try:
            longueur = int(self.headers.get("Content-Length", 0))
            data = json.loads(self.rfile.read(longueur).decode("utf-8"))

            client = data.get("client", "Inconnu")
            montant = data.get("montant", "0")
            type_op = data.get("type", "operation")
            operateur = data.get("operateur", "")

            sauvegarder_transaction(client, montant, type_op, operateur)
            self._rep(200, {"statut": "ok"})

        except Exception as e:
            self._rep(500, {"statut": "erreur", "message": str(e)})

    def do_GET(self):
        self._rep(200, {"statut": "MomoWatch actif"})

    def _rep(self, code, data):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode("utf-8"))
