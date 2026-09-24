-- ============================================================
-- MOMOWATCH — Base de données complète
-- A exécuter dans Supabase → SQL Editor → Run
-- ============================================================

-- ── 1. BOUTIQUES (chaque client/DG a une boutique) ──────────
create table if not exists boutiques (
    id uuid default gen_random_uuid() primary key,
    nom_boutique text not null,
    nom_dg text not null,
    telephone text,
    ville text,
    created_at timestamp with time zone default now(),
    actif boolean default true,
    -- Champs alimentés par ping.py (BattementCoeurWorker côté Android)
    dernier_ping timestamp with time zone,
    file_attente integer,
    batterie integer,
    mode_avion boolean default false,
    sim_changee boolean default false
);

-- Si la table existait déjà avant l'ajout du ping :
alter table boutiques add column if not exists dernier_ping timestamp with time zone;
alter table boutiques add column if not exists file_attente integer;
alter table boutiques add column if not exists batterie integer;
alter table boutiques add column if not exists mode_avion boolean default false;
alter table boutiques add column if not exists sim_changee boolean default false;

-- ── 2. ABONNEMENTS (codes d'activation) ─────────────────────
create table if not exists abonnements (
    id uuid default gen_random_uuid() primary key,
    code text unique not null,
    boutique_id uuid references boutiques(id) on delete set null,
    duree_jours integer not null, -- 30, 90 ou 365
    date_activation timestamp with time zone,
    date_expiration timestamp with time zone,
    statut text default 'disponible', -- disponible / actif / expiré
    created_at timestamp with time zone default now()
);

-- ── 3. TRANSACTIONS (toutes les transactions détectées) ──────
create table if not exists transactions (
    id bigint generated always as identity primary key,
    boutique_id uuid references boutiques(id) on delete cascade,
    client text,
    telephone_client text, -- numéro du client extrait du SMS, si disponible
    montant numeric,
    type text,        -- 'Retrait' ou 'Dépôt' (ou 'Service' pour les unités/factures)
    operateur text,   -- 'Orange Money', 'Moov Money', 'Wave'...
    solde_apres numeric, -- solde après transaction si disponible
    categorie text default 'caisse', -- 'caisse' (client) ou 'service' (unités/factures)
    type_service text, -- 'unites', 'facture_sonabel', 'facture_onea' — null si categorie = 'caisse'
    date_heure timestamp with time zone default now()
);

-- Si la table existait déjà avant l'ajout des Services :
alter table transactions add column if not exists categorie text default 'caisse';
alter table transactions add column if not exists type_service text;

-- Si la table existait déjà avant l'ajout du numéro de téléphone :
alter table transactions add column if not exists telephone_client text;

-- ── 4. TELEPHONES_BOUTIQUE (plusieurs puces par boutique) ────
create table if not exists telephones_boutique (
    id uuid default gen_random_uuid() primary key,
    boutique_id uuid references boutiques(id) on delete cascade,
    operateur text not null,
    numero_sim text,
    actif boolean default true,
    created_at timestamp with time zone default now()
);

-- Config Wave par boutique : chaque boutique qui active Wave a SON PROPRE
-- compte Wave Business, donc SON PROPRE secret de webhook (Wave ne fournit
-- pas un secret partagé pour tout le monde). L'URL du webhook enregistrée
-- sur Wave inclut le boutique_id, ce qui permet de savoir quel secret
-- utiliser pour vérifier la signature de chaque notification reçue.
create table if not exists wave_config (
    boutique_id uuid references boutiques(id) on delete cascade primary key,
    secret_webhook text not null,
    actif boolean default true,
    created_at timestamp with time zone default now()
);

-- ── 5. INDEX pour performances ───────────────────────────────
create index if not exists idx_transactions_boutique on transactions (boutique_id);
create index if not exists idx_transactions_date on transactions (date_heure);
create index if not exists idx_transactions_operateur on transactions (operateur);
create index if not exists idx_transactions_type on transactions (type);
create index if not exists idx_abonnements_code on abonnements (code);
create index if not exists idx_abonnements_boutique on abonnements (boutique_id);
create index if not exists idx_abonnements_statut on abonnements (statut);

-- ── 6. POLITIQUE DE SÉCURITÉ (Row Level Security) ───────────
alter table boutiques enable row level security;
alter table abonnements enable row level security;
alter table transactions enable row level security;
alter table telephones_boutique enable row level security;

-- Accès complet via la clé service_role (backend Vercel)
create policy "service_role_boutiques" on boutiques for all using (true);
create policy "service_role_abonnements" on abonnements for all using (true);
create policy "service_role_transactions" on transactions for all using (true);
create policy "service_role_telephones" on telephones_boutique for all using (true);

-- ── 7. FONCTION : vérifier et activer un code ────────────────
create or replace function activer_code(
    p_code text,
    p_boutique_id uuid
) returns json as $$
declare
    v_abonnement abonnements%rowtype;
    v_date_expiration timestamp with time zone;
    v_date_depart timestamp with time zone;
    v_expiration_en_cours timestamp with time zone;
begin
    -- Chercher le code
    select * into v_abonnement
    from abonnements
    where code = p_code and statut = 'disponible';

    if not found then
        return json_build_object('succes', false, 'message', 'Code invalide ou déjà utilisé');
    end if;

    -- Si cette boutique a déjà un abonnement actif ET pas encore expiré, les
    -- jours restants s'ajoutent au lieu d'être perdus : on part de la date
    -- d'expiration existante plutôt que de maintenant. Un renouvellement
    -- anticipé ne doit jamais pénaliser le boutiquier par rapport à s'il
    -- avait attendu la dernière minute.
    select date_expiration into v_expiration_en_cours
    from abonnements
    where boutique_id = p_boutique_id
      and statut = 'actif'
      and date_expiration > now()
    order by date_expiration desc
    limit 1;

    v_date_depart := coalesce(v_expiration_en_cours, now());
    v_date_expiration := v_date_depart + (v_abonnement.duree_jours || ' days')::interval;

    -- Activer le code
    update abonnements set
        boutique_id = p_boutique_id,
        date_activation = now(),
        date_expiration = v_date_expiration,
        statut = 'actif'
    where id = v_abonnement.id;

    return json_build_object(
        'succes', true,
        'message', 'Code activé avec succès',
        'expire_le', v_date_expiration
    );
end;
$$ language plpgsql security definer;

-- ── 8. FONCTION : vérifier si abonnement actif ───────────────
create or replace function abonnement_actif(p_boutique_id uuid)
returns boolean as $$
begin
    return exists (
        select 1 from abonnements
        where boutique_id = p_boutique_id
        and statut = 'actif'
        and date_expiration > now()
    );
end;
$$ language plpgsql security definer;

-- ── 9. DONNÉES DE TEST (optionnel) ───────────────────────────
-- Insérer quelques codes prédéfinis
insert into abonnements (code, duree_jours, statut) values
    ('MOMO-1M-O34N', 30, 'disponible'),
    ('MOMO-1M-N2V3', 30, 'disponible'),
    ('MOMO-1M-YB6D', 30, 'disponible'),
    ('MOMO-1M-5P6I', 30, 'disponible'),
    ('MOMO-1M-4PTD', 30, 'disponible'),
    ('MOMO-3M-LD6A', 90, 'disponible'),
    ('MOMO-3M-EE47', 90, 'disponible'),
    ('MOMO-3M-IF16', 90, 'disponible'),
    ('MOMO-3M-PUKI', 90, 'disponible'),
    ('MOMO-3M-7CYN', 90, 'disponible'),
    ('MOMO-12M-JCLK', 365, 'disponible'),
    ('MOMO-12M-GO2D', 365, 'disponible'),
    ('MOMO-12M-9NOI', 365, 'disponible'),
    ('MOMO-12M-3EXC', 365, 'disponible'),
    ('MOMO-12M-TW07', 365, 'disponible')
on conflict (code) do nothing;

-- ============================================================
-- TERMINÉ ✅
-- Tables créées : boutiques, abonnements, transactions, telephones_boutique
-- Fonctions créées : activer_code, abonnement_actif
-- 15 codes prédéfinis insérés
-- ============================================================

-- ── AJOUT (17/07/2026) : mot de passe par boutique ──────────────
-- Chaque boutique a désormais son propre mot de passe pour accéder à son
-- dashboard, afin qu'une personne non autorisée ne puisse pas fouiller dans
-- les transactions d'une boutique juste en ayant accès au téléphone.
alter table boutiques add column if not exists mot_de_passe text;

-- ── AJOUT : alertes "SMS supprimé" (bannière rouge du DG) ────────
-- Le téléphone détecte qu'un SMS de dépôt/retrait a été supprimé et le
-- signale ici. Le DG le voit sur son dashboard jusqu'à "J'ai vu".
create table if not exists alertes_suppression (
    id bigint generated always as identity primary key,
    boutique_id uuid references boutiques(id) on delete cascade,
    transaction_id text,
    type text,
    montant numeric,
    operateur text,
    date_sms timestamp with time zone,
    vue boolean default false,
    created_at timestamp with time zone default now()
);
create index if not exists idx_alertes_boutique on alertes_suppression (boutique_id, vue);
alter table alertes_suppression enable row level security;
create policy "service_role_alertes" on alertes_suppression for all using (true);

-- ── AJOUT : notifications push du DG (téléphones abonnés) ────────
create table if not exists push_abonnements (
    id bigint generated always as identity primary key,
    boutique_id uuid references boutiques(id) on delete cascade,
    endpoint text unique not null,
    p256dh text not null,
    auth text not null,
    created_at timestamp with time zone default now()
);
create index if not exists idx_push_boutique on push_abonnements (boutique_id);
alter table push_abonnements enable row level security;
create policy "service_role_push" on push_abonnements for all using (true);

-- ── AJOUT : préférences de notifications du DG + état des alertes ────────
-- notif_prefs : ce que le DG veut recevoir (chaque transaction, gros montant, batterie...)
-- notif_etat  : mémoire du serveur pour ne pas répéter la même alerte en boucle
alter table boutiques add column if not exists notif_prefs jsonb default '{}'::jsonb;
alter table boutiques add column if not exists notif_etat jsonb default '{}'::jsonb;
