-- ===========================================================================
-- MindMate — Supabase schema
--
-- Run this ONCE in the Supabase SQL Editor (Dashboard -> SQL -> New query).
-- It is idempotent: re-running it will not error or duplicate data.
--
-- After this, start the app (python run.py). On first boot it auto-seeds the
-- user agreement + sample resources (see db/seed.py).
-- ===========================================================================

-- gen_random_uuid() lives in pgcrypto (already enabled on Supabase, but be safe)
create extension if not exists pgcrypto;

-- ---------------------------------------------------------------------------
-- profiles: one row per auth user, holds role + email. Auto-created by a
-- trigger when a user signs up (see handle_new_user below).
-- ---------------------------------------------------------------------------
create table if not exists public.profiles (
    id           uuid primary key references auth.users(id) on delete cascade,
    email        text,
    display_name text,
    role         text not null default 'user' check (role in ('user', 'admin')),
    created_at   timestamptz not null default now()
);

-- Additive (idempotent): the admin site's 'staff' role. Promote someone with:
--   update public.profiles set role = 'staff' where email = 'person@example.com';
alter table public.profiles drop constraint if exists profiles_role_check;
alter table public.profiles add constraint profiles_role_check
    check (role in ('user', 'staff', 'admin'));

-- ---------------------------------------------------------------------------
-- agreements: the user agreement text, versioned and stored in the DB so it
-- can be shown before registration and edited without a code change.
-- ---------------------------------------------------------------------------
create table if not exists public.agreements (
    id         uuid primary key default gen_random_uuid(),
    version    text not null unique,
    title      text not null,
    content    text not null,
    is_active  boolean not null default true,
    created_at timestamptz not null default now()
);

-- agreement_acceptances: records which user accepted which agreement version.
create table if not exists public.agreement_acceptances (
    id           uuid primary key default gen_random_uuid(),
    user_id      uuid not null references auth.users(id) on delete cascade,
    agreement_id uuid not null references public.agreements(id) on delete cascade,
    accepted_at  timestamptz not null default now(),
    unique (user_id, agreement_id)
);

-- ---------------------------------------------------------------------------
-- prompts: the agents' system prompts, stored in the DB so they can be edited
-- in the Supabase dashboard without a code change. Seeded on first boot from
-- the bundled .txt files (app/prompt_builder/prompt/). Keys: 'composed',
-- 'summarise'. The app falls back to the bundled files if this table is empty.
-- ---------------------------------------------------------------------------
create table if not exists public.prompts (
    id          uuid primary key default gen_random_uuid(),
    key         text not null unique,
    content     text not null,
    description text,
    updated_at  timestamptz not null default now()
);

-- ---------------------------------------------------------------------------
-- sessions: one chat thread per row.
-- ---------------------------------------------------------------------------
create table if not exists public.sessions (
    id         uuid primary key default gen_random_uuid(),
    user_id    uuid not null references auth.users(id) on delete cascade,
    title      text not null default 'New chat',
    mode       text not null default 'multi',
    created_at timestamptz not null default now()
);

create index if not exists idx_sessions_user on public.sessions(user_id, created_at desc);

-- ---------------------------------------------------------------------------
-- messages: one conversation turn per row (the user's question + the
-- multi-agent reply + the diagnostic metadata). Flattened from the old
-- Firestore queries/responses subcollections for simplicity.
-- ---------------------------------------------------------------------------
create table if not exists public.messages (
    id                 uuid primary key default gen_random_uuid(),
    session_id         uuid not null references public.sessions(id) on delete cascade,
    user_id            uuid not null references auth.users(id) on delete cascade,
    question           text not null,
    reply              text,
    emotion            text,
    emotion_confidence real,
    escalated          boolean not null default false,
    summary            text,
    -- Feedback on the reply (rating 1-5 + free text + who gave it). Not used by
    -- this app yet; the columns are here for a future feedback feature.
    rating             smallint,
    feedback           text,
    feedback_by        uuid references auth.users(id) on delete set null,
    feedback_at        timestamptz,
    created_at         timestamptz not null default now()
);

create index if not exists idx_messages_session on public.messages(session_id, created_at);

-- Additive (idempotent) for databases created before the feedback columns existed.
alter table public.messages add column if not exists rating smallint;
alter table public.messages add column if not exists feedback text;
alter table public.messages add column if not exists feedback_by uuid references auth.users(id) on delete set null;
alter table public.messages add column if not exists feedback_at timestamptz;
do $$ begin
    if not exists (select 1 from pg_constraint where conname = 'messages_rating_range') then
        alter table public.messages
            add constraint messages_rating_range check (rating is null or rating between 1 and 5);
    end if;
end $$;

-- ---------------------------------------------------------------------------
-- resources: mental-health info cards. Each has an info body (one tab) and a
-- set of "steps to overcome it" (another tab, see resource_steps).
-- ---------------------------------------------------------------------------
create table if not exists public.resources (
    id           uuid primary key default gen_random_uuid(),
    slug         text not null unique,
    title        text not null,
    category     text,
    summary      text,
    info         text not null,
    image_url    text,
    is_published boolean not null default true,
    sort_order   int not null default 0,
    created_at   timestamptz not null default now()
);

create table if not exists public.resource_steps (
    id          uuid primary key default gen_random_uuid(),
    resource_id uuid not null references public.resources(id) on delete cascade,
    step_order  int not null default 0,
    title       text,
    content     text not null
);

create index if not exists idx_steps_resource on public.resource_steps(resource_id, step_order);

-- Additive (idempotent) for databases created before external resources existed.
-- Resources are imported from the TAR UMT counselling self-help page by
-- scripts/scrape_resources.py; most are external links / videos / self-tests.
--   kind:         'article' = in-house info + steps tabs
--                 'video'   = YouTube video (embedded in the detail view)
--                 'link'    = external article/guide (opens in a new tab)
--                 'test'    = external self-assessment (opens in a new tab)
--   external_url: target for video/link/test rows (null for articles)
--   source:       who hosts the content, e.g. 'helpguide.org' (shown on cards)
alter table public.resources add column if not exists kind text not null default 'article';
alter table public.resources add column if not exists external_url text;
alter table public.resources add column if not exists source text;
alter table public.resources alter column info drop not null;
do $$ begin
    if not exists (select 1 from pg_constraint where conname = 'resources_kind_check') then
        alter table public.resources
            add constraint resources_kind_check check (kind in ('article', 'video', 'link', 'test'));
    end if;
end $$;

-- ---------------------------------------------------------------------------
-- Auto-create a profile row whenever a new auth user is created.
-- ---------------------------------------------------------------------------
create or replace function public.handle_new_user()
returns trigger
language plpgsql
security definer set search_path = public
as $$
begin
    insert into public.profiles (id, email)
    values (new.id, new.email)
    on conflict (id) do nothing;
    return new;
end;
$$;

drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created
    after insert on auth.users
    for each row execute function public.handle_new_user();

-- ===========================================================================
-- Row Level Security.
-- The Flask backend uses the SERVICE key, which bypasses RLS, and enforces
-- ownership itself. These policies are defense-in-depth for any direct
-- (anon/publishable-key) access from a browser.
-- ===========================================================================
alter table public.profiles              enable row level security;
alter table public.agreements            enable row level security;
alter table public.agreement_acceptances enable row level security;
alter table public.prompts               enable row level security;
alter table public.sessions              enable row level security;
alter table public.messages              enable row level security;
alter table public.resources             enable row level security;
alter table public.resource_steps        enable row level security;

-- Helper: is the current user staff/admin? (used by the RLS policies)
create or replace function public.is_admin()
returns boolean
language sql
security definer set search_path = public
as $$
    select exists (
        select 1 from public.profiles
        where id = auth.uid() and role in ('staff', 'admin')
    );
$$;

-- profiles: a user sees/edits their own row; admins see all.
drop policy if exists profiles_select on public.profiles;
create policy profiles_select on public.profiles
    for select using (auth.uid() = id or public.is_admin());
drop policy if exists profiles_update on public.profiles;
create policy profiles_update on public.profiles
    for update using (auth.uid() = id);

-- agreements: anyone may read; only admins may write.
drop policy if exists agreements_read on public.agreements;
create policy agreements_read on public.agreements for select using (true);
drop policy if exists agreements_admin on public.agreements;
create policy agreements_admin on public.agreements
    for all using (public.is_admin()) with check (public.is_admin());

-- prompts: anyone may read; only admins may edit.
drop policy if exists prompts_read on public.prompts;
create policy prompts_read on public.prompts for select using (true);
drop policy if exists prompts_admin on public.prompts;
create policy prompts_admin on public.prompts
    for all using (public.is_admin()) with check (public.is_admin());

-- agreement_acceptances: a user manages only their own.
drop policy if exists acceptances_own on public.agreement_acceptances;
create policy acceptances_own on public.agreement_acceptances
    for all using (auth.uid() = user_id) with check (auth.uid() = user_id);

-- sessions / messages: owner-only.
drop policy if exists sessions_own on public.sessions;
create policy sessions_own on public.sessions
    for all using (auth.uid() = user_id) with check (auth.uid() = user_id);
drop policy if exists messages_own on public.messages;
create policy messages_own on public.messages
    for all using (auth.uid() = user_id) with check (auth.uid() = user_id);

-- resources / steps: published rows are world-readable; admins manage.
drop policy if exists resources_read on public.resources;
create policy resources_read on public.resources
    for select using (is_published or public.is_admin());
drop policy if exists resources_admin on public.resources;
create policy resources_admin on public.resources
    for all using (public.is_admin()) with check (public.is_admin());
drop policy if exists steps_read on public.resource_steps;
create policy steps_read on public.resource_steps for select using (true);
drop policy if exists steps_admin on public.resource_steps;
create policy steps_admin on public.resource_steps
    for all using (public.is_admin()) with check (public.is_admin());

-- ---------------------------------------------------------------------------
-- Self-tests. `test` holds the screening instruments (questions + scoring as
-- JSON, seeded on boot from app/resources/self_test/definitions.py). Every
-- completed attempt is stored in `test_created`: who took it, their answers,
-- the score, and when.
-- ---------------------------------------------------------------------------
create table if not exists public.test (
    id           uuid primary key default gen_random_uuid(),
    slug         text not null unique,
    title        text not null,
    description  text,
    questions    jsonb not null,   -- [{text, options: [{label, value}]}]
    scoring      jsonb not null,   -- {max, bands: [{min, max, label, advice}], ...}
    source       text,
    reference    text,
    sort_order   int not null default 0,
    is_published boolean not null default true,
    created_at   timestamptz not null default now()
);

create table if not exists public.test_created (
    id         uuid primary key default gen_random_uuid(),
    user_id    uuid not null references auth.users(id) on delete cascade,
    test_id    uuid not null references public.test(id) on delete cascade,
    answer     jsonb not null,    -- list of chosen option indexes
    score      int,
    band       text,
    created_at timestamptz not null default now()
);

create index if not exists idx_test_created_user on public.test_created(user_id, created_at desc);

alter table public.test         enable row level security;
alter table public.test_created enable row level security;

drop policy if exists test_read on public.test;
create policy test_read on public.test
    for select using (is_published or public.is_admin());
drop policy if exists test_admin on public.test;
create policy test_admin on public.test
    for all using (public.is_admin()) with check (public.is_admin());
drop policy if exists test_created_own on public.test_created;
create policy test_created_own on public.test_created
    for all using (auth.uid() = user_id) with check (auth.uid() = user_id);
