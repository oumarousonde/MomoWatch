from http.server import BaseHTTPRequestHandler
import json
import os
import urllib.request
import urllib.parse
from urllib.parse import urlparse, parse_qs

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")

def recuperer_transactions(operateur=None, type_op=None, date=None, client=None):
    url = f"{SUPABASE_URL}/rest/v1/transactions?select=*&order=date_heure.desc"
    if operateur:
        url += f"&operateur=eq.{urllib.parse.quote(operateur)}"
    if type_op:
        url += f"&type=eq.{urllib.parse.quote(type_op)}"
    if date:
        url += f"&date_heure=gte.{date}T00:00:00&date_heure=lte.{date}T23:59:59"
    if client:
        url += f"&client=ilike.*{urllib.parse.quote(client)}*"

    req = urllib.request.Request(
        url,
        headers={"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"},
        method="GET"
    )
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read().decode("utf-8"))

class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            params = parse_qs(urlparse(self.path).query)
            operateur = params.get("operateur", [None])[0]
            type_op = params.get("type", [None])[0]
            date = params.get("date", [None])[0]
            client = params.get("client", [None])[0]

            transactions = recuperer_transactions(operateur, type_op, date, client)
            total = sum(t.get("montant", 0) or 0 for t in transactions)

            self._rep(200, {
                "statut": "ok",
                "total_montant": total,
                "nombre_transactions": len(transactions),
                "transactions": transactions
            })
        except Exception as e:
            self._rep(500, {"statut": "erreur", "message": str(e)})

    def _rep(self, code, data):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode("utf-8"))
