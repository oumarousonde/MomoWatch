import os
from http.server import BaseHTTPRequestHandler
import json
import urllib.request

TOKEN = "5001711820:AAHUPDnKRk9t-aNQlrjN3cCaVTTe8QGFLEQ"

def envoyer_message(chat_id, texte):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload = json.dumps({"chat_id": chat_id, "text": texte}).encode("utf-8")
    req = urllib.request.Request(
        url, data=payload,
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    urllib.request.urlopen(req)

def configurer_webhook(url_vercel):
    url = f"https://api.telegram.org/bot{TOKEN}/setWebhook"
    payload = json.dumps({"url": f"{url_vercel}/api/webhook"}).encode("utf-8")
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
            update = json.loads(self.rfile.read(longueur).decode("utf-8"))

            message = update.get("message", {})
            chat = message.get("chat", {})
            chat_id = chat.get("id")
            texte = message.get("text", "")
            prenom = chat.get("first_name", "DG")

            if chat_id and texte.strip() == "/start":
                envoyer_message(
                    chat_id,
                    f"Bienvenue sur MomoWatch, {prenom}!\n\n"
                    f"Votre compte est active. Vous recevrez les "
                    f"notifications de transactions ici.\n\n"
                    f"Votre ID Telegram : {chat_id}"
                )

            self._rep(200, {"ok": True})
        except Exception as e:
            self._rep(500, {"ok": False, "erreur": str(e)})

    def do_GET(self):
        try:
            host = self.headers.get("Host", "")
            resultat = configurer_webhook(f"https://{host}")
            self._rep(200, {"statut": "Webhook configure", "resultat": resultat})
        except Exception as e:
            self._rep(500, {"ok": False, "erreur": str(e)})

    def _rep(self, code, data):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode("utf-8"))