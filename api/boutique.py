import os, json, hashlib, hmac, base64, secrets
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from supabase import create_client

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")

# ── Mots de passe : hachage (aucune dépendance en plus, tout est dans Python) ──
# Un mot de passe stocké commence par "pbkdf2_sha256$" une fois haché.
# Les comptes créés avant ce changement ont encore leur mot de passe en clair :
# hacher_mot_de_passe/verifier_mot_de_passe restent compatibles avec l'ancien
# format, et chaque connexion réussie sur un ancien compte le fait basculer
# automatiquement vers le nouveau format (voir migrer_si_besoin ci-dessous).
_PBKDF2_ITERATIONS = 260000

def hacher_mot_de_passe(mdp):
    sel = secrets.token_bytes(16)
    h = hashlib.pbkdf2_hmac("sha256", mdp.encode("utf-8"), sel, _PBKDF2_ITERATIONS)
    return "pbkdf2_sha256$" + str(_PBKDF2_ITERATIONS) + "$" + \
           base64.b64encode(sel).decode() + "$" + base64.b64encode(h).decode()

def mdp_est_hache(valeur):
    return bool(valeur) and valeur.startswith("pbkdf2_sha256$")

def verifier_mot_de_passe(mdp_saisi, valeur_stockee):
    if not valeur_stockee or mdp_saisi is None:
        return False
    if mdp_est_hache(valeur_stockee):
        try:
            _, iterations, sel_b64, hash_b64 = valeur_stockee.split("$")
            sel = base64.b64decode(sel_b64)
            attendu = base64.b64decode(hash_b64)
            calcule = hashlib.pbkdf2_hmac("sha256", mdp_saisi.encode("utf-8"), sel, int(iterations))
            return hmac.compare_digest(calcule, attendu)
        except Exception:
            return False
    # Ancien compte : mot de passe encore stocké en clair
    return hmac.compare_digest(valeur_stockee.encode("utf-8"), mdp_saisi.encode("utf-8"))

def migrer_si_besoin(supabase, boutique_id, mdp_saisi, valeur_stockee):
    """À appeler après une connexion réussie : si le mot de passe de ce compte
    était encore en clair, le remplace par sa version hachée."""
    if not mdp_est_hache(valeur_stockee):
        try:
            supabase.table("boutiques").update(
                {"mot_de_passe": hacher_mot_de_passe(mdp_saisi)}
            ).eq("id", boutique_id).execute()
        except Exception:
            pass  # la connexion reste valide même si la migration échoue

# ── Protection contre le devinage de code d'abonnement ──
# On limite le nombre d'essais de code par adresse IP, pas par code : un
# code faux, quel qu'il soit, compte comme une tentative.
_LIMITE_TENTATIVES = 8
_FENETRE_SECONDES = 15 * 60
_DUREE_ESSAI_JOURS = 7

def _ip_appelant(handler):
    xff = handler.headers.get("x-forwarded-for", "")
    if xff:
        return xff.split(",")[0].strip()
    return handler.client_address[0] if handler.client_address else "inconnue"

def _ip_bloquee(supabase, ip):
    r = supabase.table("tentatives_activation").select("echecs,dernier_echec").eq("ip", ip).execute().data
    if not r:
        return False
    dernier = datetime.fromisoformat(r[0]["dernier_echec"].replace("Z", "+00:00"))
    if (datetime.now(timezone.utc) - dernier).total_seconds() > _FENETRE_SECONDES:
        return False
    return r[0]["echecs"] >= _LIMITE_TENTATIVES

def _enregistrer_echec_ip(supabase, ip):
    maintenant = datetime.now(timezone.utc)
    r = supabase.table("tentatives_activation").select("echecs,dernier_echec").eq("ip", ip).execute().data
    if r:
        dernier = datetime.fromisoformat(r[0]["dernier_echec"].replace("Z", "+00:00"))
        echecs = 1 if (maintenant - dernier).total_seconds() > _FENETRE_SECONDES else r[0]["echecs"] + 1
        supabase.table("tentatives_activation").update(
            {"echecs": echecs, "dernier_echec": maintenant.isoformat()}
        ).eq("ip", ip).execute()
    else:
        supabase.table("tentatives_activation").insert(
            {"ip": ip, "echecs": 1, "dernier_echec": maintenant.isoformat()}
        ).execute()

def _reinitialiser_echecs_ip(supabase, ip):
    try:
        supabase.table("tentatives_activation").delete().eq("ip", ip).execute()
    except Exception:
        pass

# Regroupe activer.py, renouveler.py, verifier.py, recuperer_acces.py et
# compte_boutique.py — dispatch par URL (self.path) pour les 4 premiers
# (les URLs d'origine restent inchangées, donc rien à modifier côté APK
# Android déjà distribué), et par "action" pour compte_boutique (déjà ainsi
# avant la fusion, on garde ce fonctionnement tel quel).


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        chemin = urlparse(self.path).path
        try:
            n = int(self.headers.get("Content-Length", 0))
            data = json.loads(self.rfile.read(n).decode())
        except Exception as e:
            self._rep(500, {"succes": False, "message": str(e)})
            return

        if chemin.endswith("/activer"):
            self._activer(data)
        elif chemin.endswith("/renouveler"):
            self._renouveler(data)
        elif chemin.endswith("/recuperer_acces"):
            self._recuperer_acces(data)
        elif chemin.endswith("/compte_boutique"):
            self._compte_boutique(data)
        else:
            self._rep(404, {"succes": False, "message": "Endpoint inconnu"})

    def do_GET(self):
        chemin = urlparse(self.path).path
        if chemin.endswith("/verifier"):
            self._verifier()
        else:
            self._rep(200, {"statut": "Boutique MomoWatch ✅"})

    # ---------- activer.py ----------
    def _activer(self, data):
        try:
            code          = (data.get("code") or "").strip().upper()
            nom_boutique  = (data.get("nom_boutique") or "").strip()
            nom_dg        = (data.get("nom_dg") or "").strip()
            telephone     = (data.get("telephone") or "").strip()
            ville         = (data.get("ville") or "").strip()
            mot_de_passe  = (data.get("mot_de_passe") or "").strip()
            essai         = bool(data.get("essai"))

            if not nom_boutique or not nom_dg or not mot_de_passe or (not essai and not code):
                self._rep(400, {
                    "succes": False,
                    "message": "Le code, le nom de la boutique, le nom du DG et le mot de passe sont obligatoires"
                })
                return

            supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
            ip = _ip_appelant(self)

            if _ip_bloquee(supabase, ip):
                self._rep(429, {"succes": False, "message": "Trop de tentatives. Réessaie dans quelques minutes."})
                return

            if essai:
                # Essai gratuit de 7 jours, sans code : un seul essai par numéro
                # de téléphone (on ne peut pas en relancer un une fois le
                # premier utilisé ou expiré, même sur une nouvelle boutique).
                if not telephone:
                    self._rep(400, {"succes": False, "message": "Le téléphone est obligatoire pour l'essai gratuit"})
                    return
                tel_norm = "".join(c for c in telephone if c.isdigit())[-8:]
                boutiques_tel = supabase.table("boutiques").select("id,telephone").execute().data or []
                ids_meme_tel = [b["id"] for b in boutiques_tel
                                 if b.get("telephone") and "".join(c for c in b["telephone"] if c.isdigit())[-8:] == tel_norm]
                if ids_meme_tel:
                    deja = supabase.table("abonnements").select("id").in_("boutique_id", ids_meme_tel) \
                        .like("code", "ESSAI-%").execute().data
                    if deja:
                        _enregistrer_echec_ip(supabase, ip)
                        self._rep(400, {"succes": False, "message": "Ce numéro a déjà utilisé l'essai gratuit."})
                        return
                code = "ESSAI-" + "".join(secrets.choice("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789") for _ in range(10))
                supabase.table("abonnements").insert(
                    {"code": code, "duree_jours": _DUREE_ESSAI_JOURS, "statut": "disponible"}
                ).execute()

            abonnement_existant = supabase.table("abonnements").select("*").eq("code", code).execute().data

            if abonnement_existant:
                a = abonnement_existant[0]
                if a["statut"] == "actif" and a.get("boutique_id"):
                    boutique_existante = supabase.table("boutiques").select("*").eq("id", a["boutique_id"]).execute().data
                    if boutique_existante:
                        mdp_stocke = boutique_existante[0].get("mot_de_passe")
                        if not verifier_mot_de_passe(mot_de_passe, mdp_stocke):
                            _enregistrer_echec_ip(supabase, ip)
                            self._rep(401, {"succes": False, "message": "Mot de passe incorrect"})
                            return
                        migrer_si_besoin(supabase, a["boutique_id"], mot_de_passe, mdp_stocke)
                        _reinitialiser_echecs_ip(supabase, ip)
                        self._rep(200, {
                            "succes": True,
                            "message": "Connecté à la boutique existante",
                            "boutique_id": a["boutique_id"],
                            "nom_boutique": boutique_existante[0]["nom_boutique"],
                            "expire_le": a.get("date_expiration")
                        })
                        return
                elif a["statut"] != "disponible":
                    _enregistrer_echec_ip(supabase, ip)
                    self._rep(400, {"succes": False, "message": "Ce code n'est plus disponible"})
                    return
            else:
                _enregistrer_echec_ip(supabase, ip)
                self._rep(400, {"succes": False, "message": "Code invalide"})
                return

            boutique = supabase.table("boutiques").insert({
                "nom_boutique": nom_boutique,
                "nom_dg": nom_dg,
                "telephone": telephone,
                "ville": ville,
                "mot_de_passe": hacher_mot_de_passe(mot_de_passe)
            }).execute()

            boutique_id = boutique.data[0]["id"]

            resultat = supabase.rpc("activer_code", {
                "p_code": code,
                "p_boutique_id": boutique_id
            }).execute().data

            if not resultat or not resultat.get("succes"):
                supabase.table("boutiques").delete().eq("id", boutique_id).execute()
                _enregistrer_echec_ip(supabase, ip)
                self._rep(400, resultat or {"succes": False, "message": "Code invalide"})
                return

            _reinitialiser_echecs_ip(supabase, ip)

            # Lier tout de suite cette nouvelle boutique à un compte DG,
            # si le DG a rempli ces champs (facultatif). Ne bloque jamais la
            # création de la boutique en cas de souci sur ce point.
            dg_telephone = (data.get("dg_telephone") or "").strip()
            dg_mot_de_passe = (data.get("dg_mot_de_passe") or "").strip()
            if dg_telephone and dg_mot_de_passe:
                try:
                    tel_norm = "".join(c for c in dg_telephone if c.isdigit())
                    comptes = supabase.table("comptes_dg").select("*").execute().data or []
                    compte = next((c for c in comptes
                                   if "".join(ch for ch in c["telephone"] if ch.isdigit()) == tel_norm), None)
                    if compte and verifier_mot_de_passe(dg_mot_de_passe, compte["mot_de_passe"]):
                        supabase.table("boutiques").update({"dg_id": compte["id"]}).eq("id", boutique_id).execute()
                    elif not compte:
                        nouveau = supabase.table("comptes_dg").insert(
                            {"telephone": dg_telephone, "mot_de_passe": hacher_mot_de_passe(dg_mot_de_passe)}
                        ).execute().data
                        supabase.table("boutiques").update({"dg_id": nouveau[0]["id"]}).eq("id", boutique_id).execute()
                    # si le compte existe mais mauvais mot de passe : on ne lie pas,
                    # la boutique reste utilisable seule, le DG pourra la lier plus tard
                except Exception:
                    pass

            self._rep(200, {
                "succes": True,
                "message": "Boutique activée avec succès",
                "boutique_id": boutique_id,
                "nom_boutique": nom_boutique,
                "expire_le": resultat.get("expire_le")
            })
        except Exception as e:
            self._rep(500, {"succes": False, "message": str(e)})

    # ---------- renouveler.py ----------
    def _renouveler(self, data):
        try:
            code        = (data.get("code") or "").strip().upper()
            boutique_id = (data.get("boutique_id") or "").strip()

            if not code or not boutique_id:
                self._rep(400, {
                    "succes": False,
                    "message": "Le code et l'identifiant de la boutique sont obligatoires"
                })
                return

            supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

            boutique = supabase.table("boutiques").select("*").eq("id", boutique_id).execute().data
            if not boutique:
                self._rep(404, {"succes": False, "message": "Boutique introuvable"})
                return

            resultat = supabase.rpc("activer_code", {
                "p_code": code,
                "p_boutique_id": boutique_id
            }).execute().data

            if not resultat or not resultat.get("succes"):
                self._rep(400, resultat or {"succes": False, "message": "Code invalide"})
                return

            self._rep(200, {
                "succes": True,
                "message": "Abonnement renouvelé avec succès",
                "boutique_id": boutique_id,
                "nom_boutique": boutique[0]["nom_boutique"],
                "expire_le": resultat.get("expire_le"),
                "duree_jours": resultat.get("duree_jours")
            })
        except Exception as e:
            self._rep(500, {"succes": False, "message": str(e)})

    # ---------- verifier.py ----------
    def _verifier(self):
        try:
            params = parse_qs(urlparse(self.path).query)
            boutique_id = params.get("boutique_id", [None])[0]

            if not boutique_id:
                self._rep(400, {"actif": False, "message": "boutique_id manquant"})
                return

            supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

            actif = bool(supabase.rpc("abonnement_actif", {
                "p_boutique_id": boutique_id
            }).execute().data)

            abo = supabase.table("abonnements").select("date_expiration") \
                .eq("boutique_id", boutique_id) \
                .eq("statut", "actif") \
                .order("date_expiration", desc=True) \
                .limit(1).execute()

            expire_le = abo.data[0]["date_expiration"] if abo.data else None

            self._rep(200, {"actif": actif, "expire_le": expire_le})
        except Exception as e:
            self._rep(500, {"actif": False, "message": str(e)})

    # ---------- recuperer_acces.py ----------
    def _recuperer_acces(self, data):
        try:
            telephone    = (data.get("telephone") or "").strip()
            mot_de_passe = (data.get("mot_de_passe") or "").strip()

            if not telephone or not mot_de_passe:
                self._rep(400, {"succes": False, "message": "Téléphone et mot de passe requis"})
                return

            supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

            telephone_nettoye = "".join(c for c in telephone if c.isdigit())

            boutiques = supabase.table("boutiques").select("*").execute().data
            trouvees = []
            for b in boutiques:
                tel = b.get("telephone")
                if not tel or not "".join(c for c in tel if c.isdigit()).endswith(telephone_nettoye[-8:]):
                    continue
                if verifier_mot_de_passe(mot_de_passe, b.get("mot_de_passe")):
                    migrer_si_besoin(supabase, b["id"], mot_de_passe, b.get("mot_de_passe"))
                    trouvees.append(b)

            if not trouvees:
                self._rep(401, {"succes": False, "message": "Téléphone ou mot de passe incorrect"})
                return

            if len(trouvees) > 1:
                self._rep(200, {
                    "succes": True,
                    "plusieurs": True,
                    "boutiques": [{"boutique_id": b["id"], "nom_boutique": b["nom_boutique"]} for b in trouvees]
                })
                return

            b = trouvees[0]
            self._rep(200, {
                "succes": True,
                "plusieurs": False,
                "boutique_id": b["id"],
                "nom_boutique": b["nom_boutique"],
                "nom_dg": b.get("nom_dg"),
                "telephone": b.get("telephone"),
                "ville": b.get("ville")
            })
        except Exception as e:
            self._rep(500, {"succes": False, "message": str(e)})

    # ---------- compte_boutique.py ----------
    def _compte_boutique(self, data):
        try:
            action = (data.get("action") or "connexion").strip()
            supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

            if action == "connexion":
                self._cb_connexion(supabase, data)
            elif action == "changer_mot_de_passe":
                self._cb_changer_mot_de_passe(supabase, data)
            elif action == "modifier_infos":
                self._cb_modifier_infos(supabase, data)
            elif action == "dg_connexion":
                self._cb_dg_connexion(supabase, data)
            elif action == "dg_lier_boutique":
                self._cb_dg_lier_boutique(supabase, data)
            else:
                self._rep(400, {"succes": False, "message": "Action inconnue"})
        except Exception as e:
            self._rep(500, {"succes": False, "message": str(e)})

    def _resume_boutiques_dg(self, supabase, dg_id):
        """Petite fiche par boutique liée à ce compte DG : de quoi les
        distinguer et voir en un coup d'œil laquelle a besoin d'attention."""
        boutiques = supabase.table("boutiques") \
            .select("id,nom_boutique,ville,dernier_ping,batterie") \
            .eq("dg_id", dg_id).execute().data or []
        resultat = []
        for b in boutiques:
            try:
                active = bool(supabase.rpc("abonnement_actif", {"p_boutique_id": b["id"]}).execute().data)
            except Exception:
                active = True  # en cas de doute, ne pas bloquer l'accès du DG
            resultat.append({
                "id": b["id"], "nom_boutique": b.get("nom_boutique") or "",
                "ville": b.get("ville") or "", "abonnement_actif": active,
                "dernier_ping": b.get("dernier_ping"), "batterie": b.get("batterie")
            })
        return resultat

    # ---------- compte DG : connexion + liste de ses boutiques ----------
    def _cb_dg_connexion(self, supabase, data):
        telephone = (data.get("telephone") or "").strip()
        mot_de_passe = (data.get("mot_de_passe") or "").strip()
        if not telephone or not mot_de_passe:
            self._rep(400, {"succes": False, "message": "Téléphone et mot de passe obligatoires"})
            return

        tel_norm = "".join(c for c in telephone if c.isdigit())
        comptes = supabase.table("comptes_dg").select("*").execute().data or []
        compte = next((c for c in comptes
                       if "".join(ch for ch in c["telephone"] if ch.isdigit()) == tel_norm), None)
        if not compte or not verifier_mot_de_passe(mot_de_passe, compte["mot_de_passe"]):
            self._rep(401, {"succes": False, "message": "Téléphone ou mot de passe incorrect"})
            return

        self._rep(200, {
            "succes": True, "dg_id": compte["id"],
            "boutiques": self._resume_boutiques_dg(supabase, compte["id"])
        })

    # ---------- compte DG : lier la boutique actuelle à un compte DG ----------
    # Le mot de passe demandé ici est celui DE LA BOUTIQUE (elle est déjà
    # ouverte dans le dashboard) : ça prouve qu'on en est bien le
    # propriétaire avant de l'ajouter à un compte DG. Si le compte DG
    # n'existe pas encore pour ce téléphone, il est créé à la volée.
    def _cb_dg_lier_boutique(self, supabase, data):
        boutique_id = data.get("boutique_id")
        mot_de_passe_boutique = (data.get("mot_de_passe_boutique") or "").strip()
        dg_telephone = (data.get("dg_telephone") or "").strip()
        dg_mot_de_passe = (data.get("dg_mot_de_passe") or "").strip()
        if not boutique_id or not mot_de_passe_boutique or not dg_telephone or not dg_mot_de_passe:
            self._rep(400, {"succes": False, "message": "Informations manquantes"})
            return

        b = supabase.table("boutiques").select("*").eq("id", boutique_id).execute().data
        if not b or not verifier_mot_de_passe(mot_de_passe_boutique, b[0].get("mot_de_passe")):
            self._rep(401, {"succes": False, "message": "Mot de passe de la boutique incorrect"})
            return
        migrer_si_besoin(supabase, boutique_id, mot_de_passe_boutique, b[0].get("mot_de_passe"))

        tel_norm = "".join(c for c in dg_telephone if c.isdigit())
        comptes = supabase.table("comptes_dg").select("*").execute().data or []
        compte = next((c for c in comptes
                       if "".join(ch for ch in c["telephone"] if ch.isdigit()) == tel_norm), None)
        if compte:
            if not verifier_mot_de_passe(dg_mot_de_passe, compte["mot_de_passe"]):
                self._rep(401, {"succes": False, "message": "Mot de passe du compte DG incorrect"})
                return
            dg_id = compte["id"]
        else:
            nouveau = supabase.table("comptes_dg").insert(
                {"telephone": dg_telephone, "mot_de_passe": hacher_mot_de_passe(dg_mot_de_passe)}
            ).execute().data
            dg_id = nouveau[0]["id"]

        supabase.table("boutiques").update({"dg_id": dg_id}).eq("id", boutique_id).execute()
        self._rep(200, {
            "succes": True, "dg_id": dg_id,
            "boutiques": self._resume_boutiques_dg(supabase, dg_id)
        })

    def _cb_connexion(self, supabase, data):
        boutique_id  = (data.get("boutique_id") or "").strip()
        mot_de_passe = (data.get("mot_de_passe") or "").strip()

        if not boutique_id or not mot_de_passe:
            self._rep(400, {"succes": False, "message": "Mot de passe requis"})
            return

        boutique = supabase.table("boutiques").select("*").eq("id", boutique_id).execute().data
        if not boutique:
            self._rep(404, {"succes": False, "message": "Boutique introuvable"})
            return

        b = boutique[0]

        if not b.get("mot_de_passe"):
            self._rep(200, {
                "succes": True,
                "mot_de_passe_a_definir": True,
                "nom_boutique": b["nom_boutique"],
                "nom_dg": b.get("nom_dg"),
                "telephone": b.get("telephone"),
                "ville": b.get("ville")
            })
            return

        if not verifier_mot_de_passe(mot_de_passe, b.get("mot_de_passe")):
            self._rep(401, {"succes": False, "message": "Mot de passe incorrect"})
            return

        migrer_si_besoin(supabase, boutique_id, mot_de_passe, b.get("mot_de_passe"))

        self._rep(200, {
            "succes": True,
            "mot_de_passe_a_definir": False,
            "nom_boutique": b["nom_boutique"],
            "nom_dg": b.get("nom_dg"),
            "telephone": b.get("telephone"),
            "ville": b.get("ville")
        })

    def _cb_changer_mot_de_passe(self, supabase, data):
        boutique_id = (data.get("boutique_id") or "").strip()
        nouveau_mdp = (data.get("nouveau_mot_de_passe") or "").strip()
        ancien_mdp  = (data.get("ancien_mot_de_passe") or "").strip()

        if not boutique_id or not nouveau_mdp:
            self._rep(400, {"succes": False, "message": "Nouveau mot de passe requis"})
            return
        if len(nouveau_mdp) < 4:
            self._rep(400, {"succes": False, "message": "Le mot de passe doit faire au moins 4 caractères"})
            return

        boutique = supabase.table("boutiques").select("*").eq("id", boutique_id).execute().data
        if not boutique:
            self._rep(404, {"succes": False, "message": "Boutique introuvable"})
            return

        b = boutique[0]
        mdp_actuel = b.get("mot_de_passe")

        if mdp_actuel:
            if not ancien_mdp or not verifier_mot_de_passe(ancien_mdp, mdp_actuel):
                self._rep(401, {"succes": False, "message": "Ancien mot de passe incorrect"})
                return

        supabase.table("boutiques").update({"mot_de_passe": hacher_mot_de_passe(nouveau_mdp)}).eq("id", boutique_id).execute()
        self._rep(200, {"succes": True, "message": "Mot de passe enregistré"})

    def _cb_modifier_infos(self, supabase, data):
        boutique_id  = (data.get("boutique_id") or "").strip()
        mot_de_passe = (data.get("mot_de_passe") or "").strip()

        if not boutique_id or not mot_de_passe:
            self._rep(400, {"succes": False, "message": "Mot de passe requis"})
            return

        boutique = supabase.table("boutiques").select("*").eq("id", boutique_id).execute().data
        if not boutique:
            self._rep(404, {"succes": False, "message": "Boutique introuvable"})
            return

        b = boutique[0]

        if b.get("mot_de_passe") and not verifier_mot_de_passe(mot_de_passe, b.get("mot_de_passe")):
            self._rep(401, {"succes": False, "message": "Mot de passe incorrect"})
            return
        if b.get("mot_de_passe"):
            migrer_si_besoin(supabase, boutique_id, mot_de_passe, b.get("mot_de_passe"))

        champs_modifiables = ["nom_boutique", "nom_dg", "telephone", "ville"]
        mise_a_jour = {}
        for champ in champs_modifiables:
            valeur = data.get(champ)
            if valeur is not None and str(valeur).strip():
                mise_a_jour[champ] = str(valeur).strip()

        if not mise_a_jour:
            self._rep(400, {"succes": False, "message": "Aucune information à modifier"})
            return

        supabase.table("boutiques").update(mise_a_jour).eq("id", boutique_id).execute()
        self._rep(200, {"succes": True, "message": "Informations mises à jour"})

    def _rep(self, code, data):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode())
