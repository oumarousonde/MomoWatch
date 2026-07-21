import os, json
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from datetime import datetime, timezone, timedelta
from supabase import create_client

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            params = parse_qs(urlparse(self.path).query)
            mot_de_passe = params.get("mot_de_passe", [None])[0]

            if mot_de_passe != ADMIN_PASSWORD:
                self._rep(401, {"succes": False, "message": "Mot de passe incorrect"})
                return

            supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
            boutiques = supabase.table("boutiques").select("*").execute().data
            abonnements = supabase.table("abonnements").select("*").execute().data

            maintenant = datetime.now(timezone.utc)
            dans_7_jours = maintenant + timedelta(days=7)

            total_boutiques = len(boutiques)

            # Pour chaque boutique, on regarde son abonnement ACTIF le plus récent
            # (une boutique peut avoir plusieurs codes dans son historique : anciens
            # codes consommés + le code actif courant).
            actives, expirant_bientot, expirees = 0, 0, 0
            for b in boutiques:
                abos_boutique = [a for a in abonnements if a.get("boutique_id") == b["id"] and a.get("statut") == "actif"]
                if not abos_boutique:
                    expirees += 1
                    continue
                # Le plus tardif en cas de plusieurs (renouvellements successifs)
                plus_recent = max(abos_boutique, key=lambda a: a.get("date_expiration") or "")
                exp_str = plus_recent.get("date_expiration")
                if not exp_str:
                    expirees += 1
                    continue
                try:
                    exp_date = datetime.fromisoformat(exp_str.replace("Z", "+00:00"))
                except Exception:
                    expirees += 1
                    continue

                if exp_date < maintenant:
                    expirees += 1
                elif exp_date <= dans_7_jours:
                    actives += 1
                    expirant_bientot += 1
                else:
                    actives += 1

            debut_mois = maintenant.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            nouvelles_ce_mois = 0
            for b in boutiques:
                ca = b.get("created_at")
                if not ca:
                    continue
                try:
                    d = datetime.fromisoformat(ca.replace("Z", "+00:00"))
                    if d >= debut_mois:
                        nouvelles_ce_mois += 1
                except Exception:
                    pass

            codes_disponibles = len([a for a in abonnements if a.get("statut") == "disponible"])

            self._rep(200, {
                "succes": True,
                "total_boutiques": total_boutiques,
                "actives": actives,
                "expirant_7_jours": expirant_bientot,
                "expirees": expirees,
                "nouvelles_ce_mois": nouvelles_ce_mois,
                "codes_disponibles_non_utilises": codes_disponibles
            })
        except Exception as e:
            self._rep(500, {"succes": False, "message": str(e)})

    def _rep(self, code, data):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode())
