import os, json, calendar
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from datetime import datetime, timedelta, timezone
from collections import defaultdict
from supabase import create_client

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")
# Notifications push (clés VAPID à définir dans Vercel → Settings → Environment Variables)
VAPID_PRIVATE_KEY = os.environ.get("VAPID_PRIVATE_KEY", "")
VAPID_SUBJECT = os.environ.get("VAPID_SUBJECT", "https://momo-watch.vercel.app")
# Clé secrète du contrôle automatique "téléphone sans signal" (appelé par cron-job.org)
CRON_SECRET = os.environ.get("CRON_SECRET", "")

# Réglages par défaut des notifications du DG (modifiables dans ⚙️ Paramètres)
PREFS_DEFAUT = {
    "suppression": True,    # message supprimé sur le téléphone
    "transactions": True,   # chaque dépôt / retrait
    "gros_montant": True,   # dépôt / retrait au-dessus du seuil
    "seuil": 100000,        # FCFA
    "batterie": True,       # batterie faible
    "sans_signal": True     # téléphone sans signal
}
SEUIL_BATTERIE = 20         # alerte à 20 % ou moins
REARME_BATTERIE = 35        # ré-armée quand la batterie remonte à 35 %
MINUTES_SANS_SIGNAL = 60    # "sans signal depuis 1 h"

MOIS_FR = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet",
           "août", "septembre", "octobre", "novembre", "décembre"]


def log(msg):
    print(f"[MomoWatch] {msg}")


def endpoint_autorise(url):
    """N'accepte que les vrais services push des navigateurs (Chrome/Android,
    Firefox, Safari/iPhone, Edge) — évite que quelqu'un fasse envoyer des
    requêtes du serveur vers n'importe quelle adresse."""
    try:
        from urllib.parse import urlparse as _up
        u = _up(url)
        h = (u.hostname or "").lower()
        if u.scheme != "https":
            return False
        return (h == "fcm.googleapis.com"
                or h.endswith(".push.services.mozilla.com")
                or h.endswith(".push.apple.com")
                or h.endswith(".notify.windows.com"))
    except Exception:
        return False


def envoyer_push(supabase, boutique_id, titre, corps, url="/dashboard.html", endpoint=None):
    """Envoie une notification aux appareils abonnés du DG de cette boutique.
    Ne lève JAMAIS d'exception : une notification ratée ne doit jamais faire
    échouer l'enregistrement d'une alerte. Retourne le nombre d'envois réussis."""
    if not VAPID_PRIVATE_KEY:
        log("⚠️ VAPID_PRIVATE_KEY absente : notification non envoyée")
        return 0
    try:
        from pywebpush import webpush, WebPushException
    except Exception as e:
        log("⚠️ pywebpush indisponible : " + str(e))
        return 0

    try:
        q = supabase.table("push_abonnements").select("endpoint,p256dh,auth") \
            .eq("boutique_id", boutique_id)
        if endpoint:
            q = q.eq("endpoint", endpoint)
        abonnes = q.execute().data or []
    except Exception as e:
        log("⚠️ lecture abonnés push : " + str(e))
        return 0

    charge = json.dumps({"titre": titre, "corps": corps, "url": url}, ensure_ascii=False)
    envoyes = 0
    for a in abonnes:
        try:
            webpush(
                subscription_info={"endpoint": a["endpoint"],
                                   "keys": {"p256dh": a["p256dh"], "auth": a["auth"]}},
                data=charge,
                vapid_private_key=VAPID_PRIVATE_KEY,
                vapid_claims={"sub": VAPID_SUBJECT},
                ttl=86400,                      # garde la notif 24 h si le téléphone est éteint
                headers={"Urgency": "high"},    # livraison immédiate même en veille
                timeout=3)
            envoyes += 1
        except WebPushException as e:
            statut = getattr(getattr(e, "response", None), "status_code", None)
            if statut in (404, 410):  # appareil désabonné : on nettoie
                try:
                    supabase.table("push_abonnements").delete().eq("endpoint", a["endpoint"]).execute()
                except Exception:
                    pass
            else:
                log("⚠️ push refusé (" + str(statut) + ") : " + str(e))
        except Exception as e:
            log("⚠️ push échoué : " + str(e))
    return envoyes


def fmt_fcfa(n):
    try:
        return f"{int(float(n)):,}".replace(",", " ") + " FCFA"
    except Exception:
        return str(n) + " FCFA"


def lire_boutique_notifs(supabase, boutique_id):
    """Retourne (nom_boutique, prefs, etat). Robuste : si les colonnes de
    notifications n'existent pas encore dans Supabase, on retombe sur les
    réglages par défaut au lieu de planter."""
    nom, prefs, etat = "", dict(PREFS_DEFAUT), {}
    try:
        r = supabase.table("boutiques").select("nom_boutique,notif_prefs,notif_etat") \
            .eq("id", boutique_id).execute().data
        if r:
            nom = r[0].get("nom_boutique") or ""
            if isinstance(r[0].get("notif_prefs"), dict):
                prefs.update(r[0]["notif_prefs"])
            if isinstance(r[0].get("notif_etat"), dict):
                etat = dict(r[0]["notif_etat"])
    except Exception:
        etat["_colonnes_absentes"] = True   # SQL de notifications pas encore exécuté
        try:
            r = supabase.table("boutiques").select("nom_boutique").eq("id", boutique_id).execute().data
            if r:
                nom = r[0].get("nom_boutique") or ""
        except Exception:
            pass
    return nom, prefs, etat


def duree_texte(minutes):
    minutes = int(minutes)
    if minutes < 60:
        return f"{minutes} min"
    h, m = divmod(minutes, 60)
    if h < 24:
        return f"{h} h" + (f" {m:02d}" if m else "")
    return f"{h // 24} j"


def borne_mois_precedent_equivalent(aujourdhui):
    premier_jour_mois_actuel = aujourdhui.replace(day=1)
    dernier_jour_mois_precedent = premier_jour_mois_actuel - timedelta(days=1)
    premier_jour_mois_precedent = dernier_jour_mois_precedent.replace(day=1)
    jours_dans_mois_precedent = calendar.monthrange(
        premier_jour_mois_precedent.year, premier_jour_mois_precedent.month)[1]
    jour_equivalent = min(aujourdhui.day, jours_dans_mois_precedent)
    fin_equivalente = premier_jour_mois_precedent.replace(day=jour_equivalent)
    return premier_jour_mois_precedent, fin_equivalente


def variation_pct(actuel, precedent):
    if precedent == 0:
        return None if actuel == 0 else 100.0
    return round(((actuel - precedent) / precedent) * 100, 1)


# Regroupe transaction.py, summary.py, statistiques.py, mois_disponibles.py
# et ping.py — dispatch par URL (self.path), les URLs d'origine restent
# inchangées (important pour l'APK Android déjà distribué).
#
# CORRECTIFS apportés pendant la fusion (trouvés en relisant chaque fichier) :
#   - mois_disponibles.py utilisait un "else" qui ajoutait tout ce qui n'est
#     pas "Retrait" au total des dépôts — un Service (unités, SONABEL) s'y
#     retrouvait compté à tort comme un dépôt client. Corrigé : on exclut
#     maintenant categorie='service' de l'archive mensuelle Caisse.
#   - statistiques.py comptait les Services dans "nombre de transactions"
#     alors qu'ils ne sont ni un Dépôt ni un Retrait. Corrigé pareil.
#   - summary.py accepte maintenant un filtre categorie optionnel, pour que
#     le dashboard puisse séparer Caisse et Services proprement.


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
        elif chemin.endswith("/ping"):
            self._ping(data)
        elif chemin.endswith("/alerte-suppression"):
            self._alerte_suppression(data)
        elif chemin.endswith("/alertes_vues"):
            self._alertes_vues(data)
        elif chemin.endswith("/push_abonner"):
            self._push_abonner(data)
        else:
            self._rep(404, {"statut": "erreur", "message": "Endpoint inconnu"})

    def do_GET(self):
        chemin = urlparse(self.path).path
        if chemin.endswith("/summary"):
            self._summary()
        elif chemin.endswith("/statistiques"):
            self._statistiques()
        elif chemin.endswith("/mois_disponibles"):
            self._mois_disponibles()
        elif chemin.endswith("/ping"):
            self._rep(200, {"statut": "ping actif ✅"})
        elif chemin.endswith("/alertes"):
            self._alertes()
        elif chemin.endswith("/verifier_telephones"):
            self._verifier_telephones()
        else:
            self._rep(200, {"statut": "MomoWatch actif ✅"})

    # ---------- transaction.py ----------
    def _transaction(self, data):
        try:
            log("📩 Données reçues : " + json.dumps(data))

            boutique_id = data.get("boutique_id")
            if not boutique_id:
                log("❌ boutique_id manquant")
                self._rep(400, {
                    "statut": "erreur",
                    "message": "boutique_id manquant — l'app n'est pas activée"
                })
                return

            supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

            actif = supabase.rpc("abonnement_actif", {
                "p_boutique_id": boutique_id
            }).execute().data

            if not actif:
                log("❌ Abonnement inactif pour " + boutique_id)
                self._rep(403, {"statut": "erreur", "message": "Abonnement inactif ou expiré"})
                return

            telephone = data.get("telephone") or data.get("telephone_client") or None
            log("🔍 Téléphone extrait : " + str(telephone))

            # Les Services (unités, factures) ne sont plus gérés. Une ancienne
            # version de l'app peut encore en envoyer : on répond "ok" pour
            # qu'elle arrête de réessayer, mais on ne les enregistre pas.
            if data.get("categorie", "caisse") == "service":
                log("⏭️ Service ignoré (fonction supprimée)")
                self._rep(200, {"statut": "ok", "message": "service ignoré"})
                return

            insert_data = {
                "boutique_id": boutique_id,
                "client":      data.get("client", "Inconnu"),
                "telephone_client": telephone,
                "montant":     float(str(data.get("montant", 0)).replace(" ", "")),
                "type":        data.get("type", ""),
                "operateur":   data.get("operateur", ""),
                "solde_apres": data.get("solde_apres")
            }
            log("📤 Insertion Supabase : " + json.dumps(insert_data))

            supabase.table("transactions").insert(insert_data).execute()
            log("✅ Transaction enregistrée avec succès")

            # Notification au DG (ne bloque et ne fait jamais échouer l'enregistrement)
            try:
                self._notifier_transaction(supabase, boutique_id, insert_data)
            except Exception as e:
                log("⚠️ notification transaction : " + str(e))

            self._rep(200, {"statut": "ok"})
        except Exception as e:
            log("❌ ERREUR : " + str(e))
            self._rep(500, {"statut": "erreur", "message": str(e)})

    # ---------- ping.py ----------
    def _ping(self, data):
        try:
            boutique_id = data.get("boutique_id")
            if not boutique_id:
                self._rep(400, {"statut": "erreur", "message": "boutique_id manquant"})
                return

            supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
            maj = {
                "dernier_ping": datetime.now(timezone.utc).isoformat(),
                "file_attente": int(data.get("file_attente", 0)),
                "batterie": data.get("batterie"),
                "mode_avion": bool(data.get("mode_avion", False))
            }
            # "SIM changée" reste affiché jusqu'à ce que le DG clique "J'ai vu" :
            # le téléphone ne le signale qu'une fois, un ping suivant ne doit pas l'effacer.
            if data.get("sim_changee"):
                maj["sim_changee"] = True
            supabase.table("boutiques").update(maj).eq("id", boutique_id).execute()

            log("💓 Ping reçu de " + str(boutique_id))

            try:
                self._notifs_ping(supabase, boutique_id, data)
            except Exception as e:
                log("⚠️ notifications ping : " + str(e))

            self._rep(200, {"statut": "ok"})
        except Exception as e:
            self._rep(500, {"statut": "erreur", "message": str(e)})

    # ---------- alerte-suppression : un SMS de transaction a été supprimé ----------
    # Envoyé par le téléphone (SurveillanceSuppressionWorker). Le DG le voit
    # en bannière rouge sur son dashboard jusqu'à ce qu'il clique "J'ai vu".
    def _alerte_suppression(self, data):
        try:
            boutique_id = data.get("boutique_id")
            if not boutique_id:
                self._rep(400, {"statut": "erreur", "message": "boutique_id manquant"})
                return

            transaction_id = data.get("transaction_id") or None
            date_sms = None
            try:
                if data.get("date_sms"):
                    date_sms = datetime.fromtimestamp(
                        int(data["date_sms"]) / 1000, tz=timezone.utc).isoformat()
            except Exception:
                date_sms = None

            supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

            # Anti-doublon : le téléphone réessaie tant qu'il n'a pas de réponse ok
            q = supabase.table("alertes_suppression").select("id").eq("boutique_id", boutique_id)
            if transaction_id:
                q = q.eq("transaction_id", transaction_id)
            elif date_sms:
                q = q.eq("date_sms", date_sms)
            if (transaction_id or date_sms) and q.execute().data:
                self._rep(200, {"statut": "ok", "message": "déjà enregistrée"})
                return

            supabase.table("alertes_suppression").insert({
                "boutique_id": boutique_id,
                "transaction_id": transaction_id,
                "type": data.get("type", ""),
                "montant": float(data.get("montant") or 0),
                "operateur": data.get("operateur", ""),
                "date_sms": date_sms
            }).execute()
            log("🚨 SMS supprimé signalé par " + str(boutique_id))

            # Notification sur le téléphone du DG (ne bloque jamais la réponse)
            try:
                nom, prefs, _ = lire_boutique_notifs(supabase, boutique_id)
                if prefs.get("suppression", True):
                    corps = (f"{data.get('type') or 'Transaction'} de {fmt_fcfa(data.get('montant') or 0)} "
                             f"({data.get('operateur') or 'opérateur inconnu'}) supprimé")
                    if nom:
                        corps += " — " + nom
                    envoyer_push(supabase, boutique_id, "🚨 Message supprimé", corps)
            except Exception as e:
                log("⚠️ notification non envoyée : " + str(e))

            self._rep(200, {"statut": "ok"})
        except Exception as e:
            log("❌ ERREUR alerte-suppression : " + str(e))
            self._rep(500, {"statut": "erreur", "message": str(e)})

    # ---------- notification : chaque dépôt / retrait (et gros montants) ----------
    def _notifier_transaction(self, supabase, boutique_id, tx):
        nom, prefs, _ = lire_boutique_notifs(supabase, boutique_id)
        montant = float(tx.get("montant") or 0)
        type_ = (tx.get("type") or "").lower().replace("ô", "o").replace("é", "e")
        est_depot = type_.startswith("depot")
        est_retrait = type_.startswith("retrait")
        if not (est_depot or est_retrait):
            return

        try:
            seuil = float(prefs.get("seuil") or 0)
        except Exception:
            seuil = float(PREFS_DEFAUT["seuil"])

        if prefs.get("gros_montant", True) and seuil > 0 and montant >= seuil:
            titre = "💰 GROS DÉPÔT" if est_depot else "💸 GROS RETRAIT"
        elif prefs.get("transactions", True):
            titre = "📥 Dépôt" if est_depot else "📤 Retrait"
        else:
            return

        corps = fmt_fcfa(montant)
        if tx.get("operateur"):
            corps += " · " + tx["operateur"]
        client = tx.get("client")
        if client and client != "Inconnu":
            corps += " · " + client
        if nom:
            corps += " — " + nom
        envoyer_push(supabase, boutique_id, titre, corps)

    # ---------- notification : batterie faible / téléphone de retour en ligne ----------
    def _notifs_ping(self, supabase, boutique_id, data):
        nom, prefs, etat = lire_boutique_notifs(supabase, boutique_id)
        if etat.get("_colonnes_absentes"):
            return  # sans mémoire d'état, on répéterait la même alerte à chaque ping
        nouvel_etat = dict(etat)
        suffixe = (" — " + nom) if nom else ""

        bat = data.get("batterie")
        if isinstance(bat, (int, float)) and bat >= 0:
            if bat <= SEUIL_BATTERIE and not etat.get("batterie") and prefs.get("batterie", True):
                n = envoyer_push(supabase, boutique_id, "🔋 Batterie faible",
                                 f"Le téléphone de la boutique est à {int(bat)} %. À brancher rapidement{suffixe}")
                if n > 0:
                    nouvel_etat["batterie"] = True
            elif bat >= REARME_BATTERIE and etat.get("batterie"):
                nouvel_etat["batterie"] = False

        if etat.get("sans_signal"):
            if prefs.get("sans_signal", True):
                envoyer_push(supabase, boutique_id, "✅ Téléphone de nouveau en ligne",
                             "Le téléphone de la boutique est reconnecté" + suffixe)
            nouvel_etat["sans_signal"] = False

        if nouvel_etat != etat:
            supabase.table("boutiques").update({"notif_etat": nouvel_etat}).eq("id", boutique_id).execute()

    # ---------- contrôle automatique : téléphone sans signal ----------
    # Appelé toutes les ~10 min par cron-job.org :
    #   https://momo-watch.vercel.app/api/verifier_telephones?cle=<CRON_SECRET>
    def _verifier_telephones(self):
        try:
            params = parse_qs(urlparse(self.path).query)
            cle = params.get("cle", [""])[0]
            if not CRON_SECRET or cle != CRON_SECRET:
                self._rep(403, {"statut": "erreur", "message": "clé invalide"})
                return

            supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
            maintenant = datetime.now(timezone.utc)
            limite = (maintenant - timedelta(minutes=MINUTES_SANS_SIGNAL)).isoformat()

            avec_abonnes = {r["boutique_id"] for r in
                            (supabase.table("push_abonnements").select("boutique_id").execute().data or [])}
            lignes = supabase.table("boutiques") \
                .select("id,nom_boutique,dernier_ping,notif_prefs,notif_etat") \
                .lt("dernier_ping", limite).execute().data or []

            alertes = 0
            for b in lignes:
                if b["id"] not in avec_abonnes:
                    continue
                prefs = dict(PREFS_DEFAUT)
                if isinstance(b.get("notif_prefs"), dict):
                    prefs.update(b["notif_prefs"])
                etat = dict(b["notif_etat"]) if isinstance(b.get("notif_etat"), dict) else {}
                if not prefs.get("sans_signal", True) or etat.get("sans_signal"):
                    continue
                if not supabase.rpc("abonnement_actif", {"p_boutique_id": b["id"]}).execute().data:
                    continue  # abonnement expiré : pas d'alerte

                dernier = datetime.fromisoformat(b["dernier_ping"].replace("Z", "+00:00"))
                minutes = (maintenant - dernier).total_seconds() / 60
                nom = b.get("nom_boutique") or ""
                n = envoyer_push(supabase, b["id"], "📵 Téléphone sans signal",
                                 f"Aucun signe de vie depuis {duree_texte(minutes)}"
                                 + (f" — {nom}" if nom else "")
                                 + ". Vérifie qu'il est allumé et connecté.")
                if n > 0:
                    etat["sans_signal"] = True
                    supabase.table("boutiques").update({"notif_etat": etat}).eq("id", b["id"]).execute()
                    alertes += 1

            self._rep(200, {"statut": "ok", "controles": len(lignes), "alertes": alertes})
        except Exception as e:
            log("❌ ERREUR verifier_telephones : " + str(e))
            self._rep(500, {"statut": "erreur", "message": str(e)})

    # ---------- push_abonner : le DG active / désactive les notifications ----------
    def _push_abonner(self, data):
        try:
            boutique_id = data.get("boutique_id")

            # Enregistrement des réglages de notifications (cases à cocher + seuil)
            if data.get("action") == "preferences" and boutique_id:
                brut = data.get("prefs") or {}
                prefs = {}
                for cle in ("suppression", "transactions", "gros_montant", "batterie", "sans_signal"):
                    prefs[cle] = bool(brut.get(cle, PREFS_DEFAUT[cle]))
                try:
                    prefs["seuil"] = max(0, int(float(brut.get("seuil", PREFS_DEFAUT["seuil"]))))
                except Exception:
                    self._rep(400, {"statut": "erreur", "message": "seuil invalide"})
                    return
                supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
                supabase.table("boutiques").update({"notif_prefs": prefs}).eq("id", boutique_id).execute()
                self._rep(200, {"statut": "ok", "prefs": prefs})
                return

            sub = data.get("subscription") or {}
            endpoint = sub.get("endpoint")
            cles = sub.get("keys") or {}
            if not boutique_id or not endpoint:
                self._rep(400, {"statut": "erreur", "message": "boutique_id ou abonnement manquant"})
                return

            supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

            if data.get("action") == "desabonner":
                supabase.table("push_abonnements").delete() \
                    .eq("endpoint", endpoint).eq("boutique_id", boutique_id).execute()
                self._rep(200, {"statut": "ok"})
                return

            if not endpoint_autorise(endpoint) or not cles.get("p256dh") or not cles.get("auth"):
                self._rep(400, {"statut": "erreur", "message": "abonnement non valide"})
                return

            supabase.table("push_abonnements").upsert({
                "boutique_id": boutique_id,
                "endpoint": endpoint,
                "p256dh": cles["p256dh"],
                "auth": cles["auth"]
            }, on_conflict="endpoint").execute()

            # Notification de bienvenue : confirme tout de suite que ça marche
            envoyer_push(supabase, boutique_id, "✅ Notifications activées",
                         "Tu recevras ici les alertes de ta boutique.",
                         endpoint=endpoint)
            self._rep(200, {"statut": "ok"})
        except Exception as e:
            log("❌ ERREUR push_abonner : " + str(e))
            self._rep(500, {"statut": "erreur", "message": str(e)})

    # ---------- alertes : bannière DG + statut du téléphone ----------
    def _alertes(self):
        try:
            params = parse_qs(urlparse(self.path).query)
            boutique_id = params.get("boutique_id", [None])[0]
            if not boutique_id:
                self._rep(400, {"statut": "erreur", "message": "boutique_id manquant"})
                return

            supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

            alertes = supabase.table("alertes_suppression") \
                .select("id,transaction_id,type,montant,operateur,date_sms,created_at") \
                .eq("boutique_id", boutique_id).eq("vue", False) \
                .order("created_at", desc=True).limit(50).execute().data

            tel = supabase.table("boutiques") \
                .select("dernier_ping,batterie,file_attente,mode_avion,sim_changee") \
                .eq("id", boutique_id).execute().data
            telephone = tel[0] if tel else {}
            # -1 = batterie illisible côté téléphone
            if telephone.get("batterie") is not None and telephone["batterie"] < 0:
                telephone["batterie"] = None

            _, prefs, _ = lire_boutique_notifs(supabase, boutique_id)
            self._rep(200, {"alertes": alertes, "telephone": telephone, "notif_prefs": prefs})
        except Exception as e:
            self._rep(500, {"statut": "erreur", "message": str(e)})

    def _alertes_vues(self, data):
        try:
            boutique_id = data.get("boutique_id")
            if not boutique_id:
                self._rep(400, {"statut": "erreur", "message": "boutique_id manquant"})
                return
            supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
            q = supabase.table("alertes_suppression").update({"vue": True}) \
                .eq("boutique_id", boutique_id).eq("vue", False)
            ids = data.get("ids")
            if isinstance(ids, list) and ids:
                q = q.in_("id", ids)
            q.execute()
            # Le DG a pris connaissance : on efface aussi l'alerte "SIM changée"
            supabase.table("boutiques").update({"sim_changee": False}).eq("id", boutique_id).execute()
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
            date_unique = params.get("date", [None])[0]
            depuis      = params.get("depuis", [None])[0]
            categorie   = params.get("categorie", [None])[0]

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
            if categorie:   q = q.eq("categorie", categorie)
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
                .select("montant,type,operateur,date_heure,categorie") \
                .eq("boutique_id", boutique_id) \
                .execute().data

            parsees = []
            for t in txs:
                if (t.get("categorie") or "caisse") != "caisse":
                    continue
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

            graphique = []
            for i in range(29, -1, -1):
                jour = aujourdhui - timedelta(days=i)
                du_jour = [t for t in parsees if t["date"] == jour]
                depot = sum(t["montant"] for t in du_jour if t["type"] == "Dépôt")
                retrait = sum(t["montant"] for t in du_jour if t["type"] == "Retrait")
                graphique.append({
                    "date": jour.isoformat(), "depot": depot, "retrait": retrait, "nb": len(du_jour)
                })

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

            semaine_actuelle = [t for t in parsees if (aujourdhui - t["date"]).days < 7]
            semaine_precedente = [t for t in parsees if 7 <= (aujourdhui - t["date"]).days < 14]
            a_sem = agreger(semaine_actuelle)
            p_sem = agreger(semaine_precedente)

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
                .select("montant,type,date_heure,categorie") \
                .eq("boutique_id", boutique_id) \
                .execute().data

            regroupement = defaultdict(lambda: {"total_depot": 0.0, "total_retrait": 0.0, "nb": 0})
            for t in txs:
                if (t.get("categorie") or "caisse") != "caisse":
                    continue

                date_heure = t.get("date_heure") or ""
                if len(date_heure) < 7:
                    continue
                cle = date_heure[:7]
                g = regroupement[cle]
                g["nb"] += 1
                montant = float(t.get("montant") or 0)
                if t.get("type") == "Retrait":
                    g["total_retrait"] += montant
                elif t.get("type") == "Dépôt":
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
