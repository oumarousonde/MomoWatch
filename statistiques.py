import os, json
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from datetime import datetime, timedelta, timezone
import calendar
from supabase import create_client

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")


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
    def do_GET(self):
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
