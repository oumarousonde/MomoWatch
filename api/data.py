import os, json, calendar
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from datetime import datetime, timedelta, timezone
from collections import defaultdict
from supabase import create_client

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")

MOIS_FR = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet",
           "août", "septembre", "octobre", "novembre", "décembre"]

# Regroupe transaction.py, summary.py, mois_disponibles.py et
# statistiques.py — dispatch par URL (self.path), voir boutique.py pour
# le détail. IMPORTANT : /api/transaction est appelé par l'APK Android
# déjà installé chez les boutiquiers — son comportement (POST, pas
# besoin de préciser d'action) reste identique.


def borne_mois_precedent_equivalent(aujourdhui):
    """(debut, fin) du mois précédent, limité au même jour du mois que
    aujourd'hui — comparaison 'à date équivalente' plutôt que mois complet."""
    premier_jour_mois_actuel = aujourdhui.replace(day=1)
    dernier_jour_mois_precedent = premier_jour_mois_actuel - timedelta(days=1)
    premier_jour_mois_precedent = dernier_jour_mois_precedent.replace(day=1)
    jours_dans_mois_precedent = calendar.monthrange(
        premier_jour_mois_precedent.year, premier_jour_mois_precedent.month)[1]
    jour_equivalent = min(aujourdhui.day, jours_dans_mois_precedent)
    fin_equivalente = premier_jour_mois_precedent.replace(day=jour_equivalent)
    return premier_jour_mois_precedent, fin_equivalente


def variation_pct(actuel, precedent):
    """Renvoie la variation en % (arrondie), ou None si pas de base de comparaison."""
    if precedent == 0:
        return None if actuel == 0 else 100.0
    return round(((actuel - precedent) / precedent) * 100, 1)


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        chemin = urlparse(self.path).path
        try:
            n = int(self.headers.get("Content-Length", 0))
            data = json.loads(self.rfile.read(n).decode())
        except Exception as e:
            self._rep(500, {"statut": "erreur", "message": str(e)})
            return

        if chemin.endswith("/transaction"):
            self._transaction(data)
        else:
            self._rep(404, {"statut": "erreur", "message": "Endpoint inconnu"})

    def do_GET(self):
        chemin = urlparse(self.path).path
        if chemin.endswith("/summary"):
            self._summary()
        elif chemin.endswith("/mois_disponibles"):
            self._mois_disponibles()
        elif chemin.endswith("/statistiques"):
            self._statistiques()
        else:
            self._rep(200, {"statut": "MomoWatch actif ✅"})

    # ---------- transaction.py ----------
    def _transaction(self, data):
        try:
            boutique_id = data.get("boutique_id")
            if not boutique_id:
                self._rep(400, {
                    "statut": "erreur",
                    "message": "boutique_id manquant — l'app n'est pas activée"
                })
                return

            supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

            # L'abonnement doit être actif pour accepter la transaction
            actif = supabase.rpc("abonnement_actif", {
                "p_boutique_id": boutique_id
            }).execute().data

            if not actif:
                self._rep(403, {"statut": "erreur", "message": "Abonnement inactif ou expiré"})
                return

            supabase.table("transactions").insert({
                "boutique_id": boutique_id,
                "client":      data.get("client", "Inconnu"),
                "montant":     float(str(data.get("montant", 0)).replace(" ", "")),
                "type":        data.get("type", ""),
                "operateur":   data.get("operateur", ""),
                "solde_apres": data.get("solde_apres")
            }).execute()

            self._rep(200, {"statut": "ok"})
        except Exception as e:
            self._rep(500, {"statut": "erreur", "message": str(e)})

    # ---------- summary.py ----------
    def _summary(self):
        try:
            params = parse_qs(urlparse(self.path).query)
            boutique_id = params.get("boutique_id", [None])[0]
            operateur   = params.get("operateur", [None])[0]
            type_op     = params.get("type", [None])[0]
            date_debut  = params.get("date_debut", [None])[0]
            date_fin    = params.get("date_fin", [None])[0]
            client      = params.get("client", [None])[0]
            date_unique = params.get("date", [None])[0]   # utilisé par "aujourd'hui" côté dashboard
            depuis      = params.get("depuis", [None])[0]  # utilisé par la cloche de notifications

            if not boutique_id:
                self._rep(400, {"statut": "erreur", "message": "boutique_id manquant"})
                return

            supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
            q = supabase.table("transactions").select("*") \
                .eq("boutique_id", boutique_id) \
                .order("date_heure", desc=True)

            if operateur:   q = q.eq("operateur", operateur)
            if type_op:     q = q.eq("type", type_op)
            if client:      q = q.ilike("client", f"%{client}%")
            if date_debut:  q = q.gte("date_heure", f"{date_debut}T00:00:00")
            if date_fin:    q = q.lte("date_heure", f"{date_fin}T23:59:59")
            if date_unique:
                q = q.gte("date_heure", f"{date_unique}T00:00:00") \
                     .lte("date_heure", f"{date_unique}T23:59:59")
            if depuis:
                q = q.gt("date_heure", depuis)

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

    # ---------- mois_disponibles.py ----------
    def _mois_disponibles(self):
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

    # ---------- statistiques.py ----------
    def _statistiques(self):
        try:
            params = parse_qs(urlparse(self.path).query)
            boutique_id = params.get("boutique_id", [None])[0]
            if not boutique_id:
                self._rep(400, {"succes": False, "message": "boutique_id requis"})
                return

            supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
            txs = supabase.table("transactions") \
                .select("montant,type,operateur,date_heure") \
                .eq("boutique_id", boutique_id) \
                .execute().data

            # Parse une seule fois toutes les transactions valides
            parsees = []
            for t in txs:
                dh = t.get("date_heure") or ""
                if len(dh) < 10:
                    continue
                try:
                    d = datetime.fromisoformat(dh.replace("Z", "+00:00")).date()
                except Exception:
                    continue
                parsees.append({
                    "date": d,
                    "montant": float(t.get("montant") or 0),
                    "type": t.get("type"),
                    "operateur": t.get("operateur")
                })

            aujourdhui = datetime.now(timezone.utc).date()

            # 1) Graphique : 30 derniers jours, jour par jour (avec les jours à 0)
            graphique = []
            for i in range(29, -1, -1):
                jour = aujourdhui - timedelta(days=i)
                du_jour = [t for t in parsees if t["date"] == jour]
                depot = sum(t["montant"] for t in du_jour if t["type"] == "Dépôt")
                retrait = sum(t["montant"] for t in du_jour if t["type"] == "Retrait")
                graphique.append({
                    "date": jour.isoformat(), "depot": depot, "retrait": retrait, "nb": len(du_jour)
                })

            # 2) Totaux + répartition Orange/Moov sur ces 30 jours
            fenetre_30j = [t for t in parsees if (aujourdhui - t["date"]).days < 30]

            def agreger(liste):
                return {
                    "nb": len(liste),
                    "total_depot": sum(t["montant"] for t in liste if t["type"] == "Dépôt"),
                    "total_retrait": sum(t["montant"] for t in liste if t["type"] == "Retrait")
                }

            totaux_30j = agreger(fenetre_30j)
            orange_30j = agreger([t for t in fenetre_30j if t["operateur"] == "Orange Money"])
            moov_30j = agreger([t for t in fenetre_30j if t["operateur"] == "Moov Money"])

            # 3) Semaine glissante (7 derniers jours) vs 7 jours précédents
            semaine_actuelle = [t for t in parsees if (aujourdhui - t["date"]).days < 7]
            semaine_precedente = [t for t in parsees if 7 <= (aujourdhui - t["date"]).days < 14]
            a_sem = agreger(semaine_actuelle)
            p_sem = agreger(semaine_precedente)

            # 4) Mois en cours (à date équivalente) vs mois précédent
            debut_mois_actuel = aujourdhui.replace(day=1)
            debut_mois_prec, fin_mois_prec = borne_mois_precedent_equivalent(aujourdhui)

            mois_actuel = [t for t in parsees if debut_mois_actuel <= t["date"] <= aujourdhui]
            mois_precedent = [t for t in parsees if debut_mois_prec <= t["date"] <= fin_mois_prec]
            a_mois = agreger(mois_actuel)
            p_mois = agreger(mois_precedent)

            self._rep(200, {
                "succes": True,
                "graphique_30j": graphique,
                "totaux_30j": totaux_30j,
                "orange_30j": orange_30j,
                "moov_30j": moov_30j,
                "comparaison_semaine": {
                    "actuelle": a_sem, "precedente": p_sem,
                    "variation_depot": variation_pct(a_sem["total_depot"], p_sem["total_depot"]),
                    "variation_retrait": variation_pct(a_sem["total_retrait"], p_sem["total_retrait"]),
                    "variation_nb": variation_pct(a_sem["nb"], p_sem["nb"])
                },
                "comparaison_mois": {
                    "actuel": a_mois, "precedent": p_mois,
                    "variation_depot": variation_pct(a_mois["total_depot"], p_mois["total_depot"]),
                    "variation_retrait": variation_pct(a_mois["total_retrait"], p_mois["total_retrait"]),
                    "variation_nb": variation_pct(a_mois["nb"], p_mois["nb"])
                }
            })
        except Exception as e:
            self._rep(500, {"succes": False, "message": str(e)})

    def _rep(self, code, data):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode())
