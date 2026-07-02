from flask import Flask, request, jsonify
import os
import urllib.request
import json

app = Flask(__name__)

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")

def sauvegarder_transaction(client, montant, type_op, operateur):
    """Envoie la transaction à Supabase."""
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

@app.route('/api/transactions', methods=['POST'])
def post_transaction():
    """Reçoit une transaction depuis l'app Android et la sauvegarde."""
    try:
        data = request.get_json()
        if not data:
            return jsonify({"statut": "erreur", "message": "Données JSON invalides"}), 400

        client = data.get("client", "Inconnu")
        montant = data.get("montant", "0")
        type_op = data.get("type", "operation")
        operateur = data.get("operateur", "")

        sauvegarder_transaction(client, montant, type_op, operateur)
        return jsonify({"statut": "ok"}), 200

    except Exception as e:
        return jsonify({"statut": "erreur", "message": str(e)}), 500

@app.route('/api/transactions', methods=['GET'])
def get_status():
    """Répond simplement pour vérifier que l'API est active."""
    return jsonify({"statut": "MomoWatch actif"}), 200