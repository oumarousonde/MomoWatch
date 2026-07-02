from flask import Flask, request, jsonify
import os
import urllib.request
import urllib.parse
import json

app = Flask(__name__)

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")

def recuperer_transactions(operateur=None, type_op=None, date=None, client=None):
    """Interroge Supabase avec les filtres donnés."""
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

@app.route('/api/transactions', methods=['GET'])
def get_transactions():
    """Endpoint principal : retourne la liste des transactions (avec filtres)."""
    try:
        operateur = request.args.get('operateur')
        type_op = request.args.get('type')
        date = request.args.get('date')
        client = request.args.get('client')

        transactions = recuperer_transactions(operateur, type_op, date, client)
        total = sum(t.get('montant', 0) or 0 for t in transactions)

        return jsonify({
            "statut": "ok",
            "total_montant": total,
            "nombre_transactions": len(transactions),
            "transactions": transactions
        })
    except Exception as e:
        return jsonify({"statut": "erreur", "message": str(e)}), 500

@app.route('/api/status', methods=['GET'])
def status():
    return jsonify({"status": "online", "message": "MomoWatch API est opérationnelle"})