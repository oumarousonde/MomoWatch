import os, json
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from datetime import datetime, timezone
from collections import defaultdict
from supabase import create_client

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")

MOIS_FR = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet",
           "août", "septembre", "octobre", "novembre", "décembre"]


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            params = parse_qs(urlparse(self.path).query)
            boutique_id = params.get("boutique_id", [None])[0]
            if not boutique_id:
                self._rep(400, {"succes": False, "message": "boutique_id requis"})
                return

            supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
            txs = supabase.table("transactions") \
                .select("montant,type,date_heure") \
                .eq("boutique_id", boutique_id) \
                .execute().data

            # Regroupement par mois calendaire ("2026-07"), peu importe si le mois
            # est complet ou juste entamé — un demi-mois devient quand même une
            # entrée d'archive dès que le mois suivant commence.
            regroupement = defaultdict(lambda: {"total_depot": 0.0, "total_retrait": 0.0, "nb": 0})
            for t in txs:
                date_heure = t.get("date_heure") or ""
                if len(date_heure) < 7:
                    continue
                cle = date_heure[:7]
                g = regroupement[cle]
                g["nb"] += 1
                montant = float(t.get("montant") or 0)
                if t.get("type") == "Retrait":
                    g["total_retrait"] += montant
                else:
                    g["total_depot"] += montant

            mois_actuel = datetime.now(timezone.utc).strftime("%Y-%m")

            resultat = []
            for cle in sorted(regroupement.keys(), reverse=True):
                annee, mois = cle.split("-")
                libelle = f"{MOIS_FR[int(mois) - 1].capitalize()} {annee}"
                g = regroupement[cle]
                resultat.append({
                    "mois": cle,
                    "libelle": libelle,
                    "nb": g["nb"],
                    "total_depot": g["total_depot"],
                    "total_retrait": g["total_retrait"],
                    "en_cours": cle == mois_actuel
                })

            self._rep(200, {"succes": True, "mois": resultat})
        except Exception as e:
            self._rep(500, {"succes": False, "message": str(e)})

    def _rep(self, code, data):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode())
