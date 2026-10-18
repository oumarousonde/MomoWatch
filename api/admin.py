import os, json, secrets, string
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from datetime import datetime, timezone, timedelta
from supabase import create_client

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")

DUREES = {30: "1M", 90: "3M", 365: "12M"}

# Regroupe admin_generer_code.py et admin_liste.py — dispatch par URL.
# admin_liste.py gérait déjà lui-même la vue "stats" via ?vue=stats, ce
# fonctionnement est conservé tel quel.


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        chemin = urlparse(self.path).path
        if chemin.endswith("/admin_liste"):
            self._admin_liste()
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
            self._admin_generer_code(data)
        elif chemin.endswith("/admin_reset_mdp"):
            self._admin_reset_mdp(data)
        else:
            self._rep(404, {"succes": False, "message": "Endpoint inconnu"})

    # ---------- admin_reset_mdp.py ----------
    # Permet au DG principal (admin) de débloquer une boutique dont le mot de
    # passe du dashboard a été oublié : on vide simplement le mot de passe en
    # base. Au prochain accès, le site proposera d'en définir un nouveau, sans
    # demander l'ancien (même logique que pour une boutique jamais configurée).
    def _admin_reset_mdp(self, data):
        try:
            if not ADMIN_PASSWORD or data.get("mot_de_passe") != ADMIN_PASSWORD:
                self._rep(401, {"succes": False, "message": "Mot de passe incorrect"})
                return

            boutique_id = (data.get("boutique_id") or "").strip()
            if not boutique_id:
                self._rep(400, {"succes": False, "message": "boutique_id manquant"})
                return

            supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
            boutique = supabase.table("boutiques").select("id").eq("id", boutique_id).execute().data
            if not boutique:
                self._rep(404, {"succes": False, "message": "Boutique introuvable"})
                return

            supabase.table("boutiques").update({"mot_de_passe": None}).eq("id", boutique_id).execute()
            self._rep(200, {"succes": True, "message": "Mot de passe réinitialisé"})
        except Exception as e:
            self._rep(500, {"succes": False, "message": str(e)})

    # ---------- admin_generer_code.py ----------
    def _admin_generer_code(self, data):
        try:
            if not ADMIN_PASSWORD or data.get("mot_de_passe") != ADMIN_PASSWORD:
                self._rep(401, {"succes": False, "message": "Mot de passe incorrect"})
                return

            duree_jours = int(data.get("duree_jours", 30))
            if duree_jours not in DUREES:
                self._rep(400, {"succes": False, "message": "Durée invalide"})
                return

            supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

            for _ in range(5):
                # 7 caractères aléatoires (au lieu de 4) : rend le devinage du code
                # pratiquement impossible, même sans la limite de tentatives par IP.
                suffixe = "".join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(7))
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

    # ---------- admin_liste.py ----------
    def _admin_liste(self):
        try:
            params = parse_qs(urlparse(self.path).query)
            mdp = params.get("mot_de_passe", [None])[0]
            vue = params.get("vue", ["liste"])[0]

            if not ADMIN_PASSWORD or mdp != ADMIN_PASSWORD:
                self._rep(401, {"succes": False, "message": "Mot de passe incorrect"})
                return

            supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

            if vue == "stats":
                self._reponse_stats(supabase)
            else:
                self._reponse_liste(supabase)
        except Exception as e:
            self._rep(500, {"succes": False, "message": str(e)})

    def _reponse_liste(self, supabase):
        codes = supabase.table("abonnements") \
            .select("*, boutiques(nom_boutique, nom_dg, telephone, ville)") \
            .order("created_at", desc=True) \
            .execute().data

        self._rep(200, {"succes": True, "codes": codes}, defaut_str=True)

    def _reponse_stats(self, supabase):
        boutiques = supabase.table("boutiques").select("*").execute().data
        abonnements = supabase.table("abonnements").select("*").execute().data

        maintenant = datetime.now(timezone.utc)
        dans_7_jours = maintenant + timedelta(days=7)

        total_boutiques = len(boutiques)

        actives, expirant_bientot, expirees = 0, 0, 0
        for b in boutiques:
            abos_boutique = [a for a in abonnements if a.get("boutique_id") == b["id"] and a.get("statut") == "actif"]
            if not abos_boutique:
                expirees += 1
                continue
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

    def _rep(self, code, data, defaut_str=False):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        if defaut_str:
            self.wfile.write(json.dumps(data, ensure_ascii=False, default=str).encode())
        else:
            self.wfile.write(json.dumps(data, ensure_ascii=False).encode())
