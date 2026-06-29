import os
from http.server import BaseHTTPRequestHandler
import json
import urllib.request

TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

def envoyer_telegram(texte):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload = json.dumps({"chat_id": CHAT_ID, "text": texte}).encode("utf-8")
    req = urllib.request.Request(
        url, data=payload,
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read().decode("utf-8"))

class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        try:
            longueur = int(self.headers.get("Content-Length", 0))
            data = json.loads(self.rfile.read(longueur).decode("utf-8"))

            client = data.get("client", "Inconnu")
            montant = data.get("montant", "0")
            type_op = data.get("type", "operation")
            operateur = data.get("operateur", "")

            message = (
                f"MomoWatch - {operateur}\n"
                f"{client} - {type_op} de {montant} FCFA"
            )

            envoyer_telegram(message)
            self._rep(200, {"statut": "ok"})

        except Exception as e:
            self._rep(500, {"statut": "erreur", "message": str(e)})

    def do_GET(self):
        self._rep(200, {"statut": "MomoWatch actif"})

    def _rep(self, code, data):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode("utf-8"))