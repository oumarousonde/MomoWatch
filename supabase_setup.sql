create table transactions (
    id bigint generated always as identity primary key,
    client text,
    montant numeric,
    type text,
    operateur text,
    date_heure timestamp with time zone default now()
);
create index idx_transactions_date on transactions (date_heure);
create index idx_transactions_operateur on transactions (operateur);
