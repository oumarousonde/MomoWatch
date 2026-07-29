import os, json, random, string
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from datetime import datetime, timezone, timedelta
from supabase import create_client

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")

DUREES = {30: "1M", 90: "3M", 365: "12M"}

# Regroupe admin_stats.py, admin_liste.py et admin_generer_code.py —
# dispatch par URL (self.path), voir boutique.py pour le détail.


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        chemin = urlparse(self.path).path
        if chemin.endswith("/admin_stats"):
            self._stats()
        elif chemin.endswith("/admin_liste"):
            self._liste()
        else:
            self._rep(200, {"statut": "Admin MomoWatch ✅"})

    def do_POST(self):
        chemin = urlparse(self.path).path
        try:
            n = int(self.headers.get("Content-Length", 0))
            data = json.loads(self.rfile.read(n).decode())
        except Exception as e:
            self._rep(500, {"succes": False, "message": str(e)})
            return

        if chemin.endswith("/admin_generer_code"):
            self._generer_code(data)
        else:
            self._rep(404, {"succes": False, "message": "Endpoint inconnu"})

    # ---------- admin_stats.py ----------
    def _stats(self):
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

    # ---------- admin_liste.py ----------
    def _liste(self):
        try:
            params = parse_qs(urlparse(self.path).query)
            mdp = params.get("mot_de_passe", [None])[0]

            if not ADMIN_PASSWORD or mdp != ADMIN_PASSWORD:
                self._rep(401, {"succes": False, "message": "Mot de passe incorrect"})
                return

            supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

            codes = supabase.table("abonnements") \
                .select("*, boutiques(nom_boutique, nom_dg, telephone, ville)") \
                .order("created_at", desc=True) \
                .execute().data

            self._rep(200, {"succes": True, "codes": codes}, defaut_str=True)
        except Exception as e:
            self._rep(500, {"succes": False, "message": str(e)})

    # ---------- admin_generer_code.py ----------
    def _generer_code(self, data):
        try:
            if not ADMIN_PASSWORD or data.get("mot_de_passe") != ADMIN_PASSWORD:
                self._rep(401, {"succes": False, "message": "Mot de passe incorrect"})
                return

            duree_jours = int(data.get("duree_jours", 30))
            if duree_jours not in DUREES:
                self._rep(400, {"succes": False, "message": "Durée invalide"})
                return

            supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

            # Génère un code unique (réessaie si collision, très improbable)
            for _ in range(5):
                suffixe = "".join(random.choices(string.ascii_uppercase + string.digits, k=4))
                code = f"MOMO-{DUREES[duree_jours]}-{suffixe}"
                existe = supabase.table("abonnements").select("id").eq("code", code).execute().data
                if not existe:
                    break

            supabase.table("abonnements").insert({
                "code": code,
                "duree_jours": duree_jours,
                "statut": "disponible"
            }).execute()

            self._rep(200, {"succes": True, "code": code})
        except Exception as e:
            self._rep(500, {"succes": False, "message": str(e)})

    def _rep(self, code, data, defaut_str=False):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        if defaut_str:
            self.wfile.write(json.dumps(data, ensure_ascii=False, default=str).encode())
        else:
            self.wfile.write(json.dumps(data, ensure_ascii=False).encode())
