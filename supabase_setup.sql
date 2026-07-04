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
    actif boolean default true
);

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
    montant numeric,
    type text,        -- 'Retrait' ou 'Dépôt'
    operateur text,   -- 'Orange Money', 'Moov Money', 'Wave'...
    solde_apres numeric, -- solde après transaction si disponible
    date_heure timestamp with time zone default now()
);

-- ── 4. TELEPHONES_BOUTIQUE (plusieurs puces par boutique) ────
create table if not exists telephones_boutique (
    id uuid default gen_random_uuid() primary key,
    boutique_id uuid references boutiques(id) on delete cascade,
    operateur text not null,
    numero_sim text,
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
begin
    -- Chercher le code
    select * into v_abonnement
    from abonnements
    where code = p_code and statut = 'disponible';

    if not found then
        return json_build_object('succes', false, 'message', 'Code invalide ou déjà utilisé');
    end if;

    -- Calculer la date d'expiration
    v_date_expiration := now() + (v_abonnement.duree_jours || ' days')::interval;

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
