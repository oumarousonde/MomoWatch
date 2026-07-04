import os, json
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
import urllib.parse
from supabase import create_client

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")

class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            params = parse_qs(urlparse(self.path).query)
            operateur   = params.get("operateur", [None])[0]
            type_op     = params.get("type", [None])[0]
            date_debut  = params.get("date_debut", [None])[0]
            date_fin    = params.get("date_fin", [None])[0]
            client      = params.get("client", [None])[0]

            supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
            q = supabase.table("transactions").select("*").order("date_heure", desc=True)

            if operateur:   q = q.eq("operateur", operateur)
            if type_op:     q = q.eq("type", type_op)
            if client:      q = q.ilike("client", f"%{client}%")
            if date_debut:  q = q.gte("date_heure", f"{date_debut}T00:00:00")
            if date_fin:    q = q.lte("date_heure", f"{date_fin}T23:59:59")

            transactions = q.execute().data
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
        self.wfile.write(json.dumps(data).encode())
