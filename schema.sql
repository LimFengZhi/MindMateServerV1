-- ===========================================================================
-- MindMate — Supabase schema (FULL RESET script)
--
-- ⚠️⚠️  DESTRUCTIVE — READ BEFORE RUNNING  ⚠️⚠️
-- Running this script WIPES THE ENTIRE APP DATABASE:
--   • drops every app table (all chats, messages, test attempts, resources…)
--   • DELETES EVERY USER ACCOUNT from Supabase Auth (auth.users)
-- and then recreates everything from scratch. This is the intended workflow:
-- every schema change = edit this file, rerun it, start with a clean slate.
--
-- Run it in the Supabase SQL Editor (Dashboard -> SQL -> New query).
--
-- After a reset:
--   1. python run.py            -> auto-reseeds agreement, prompts, self-tests
--   2. python scripts/scrape_resources.py  -> re-uploads the Resources content
--   3. Register your admin account in the app, verify the email, then promote
--      it (see the commented UPDATE at the bottom of this file).
-- ===========================================================================

-- ---------------------------------------------------------------------------
-- 0. Teardown: drop all app objects, then wipe every auth account.
-- ---------------------------------------------------------------------------
drop trigger if exists on_auth_user_created on auth.users;

-- Tables first: dropping them (cascade) also removes their RLS policies, which
-- depend on is_admin() — so the function drops below can't hit 2BP01.
drop table if exists
    public.bench_result,
    public.bench_session,
    public.test_created,
    public.test,
    public.resource_steps,
    public.resources,
    public.messages,
    public.sessions,
    public.agreement_acceptances,
    public.agreements,
    public.prompts,
    public.profiles
    cascade;

drop function if exists public.handle_new_user() cascade;
drop function if exists public.is_admin() cascade;

-- Delete every account. Cascades clean out the rest of the auth schema
-- (identities, sessions, refresh tokens, MFA factors).
delete from auth.users;

-- gen_random_uuid() lives in pgcrypto (already enabled on Supabase, but be safe)
create extension if not exists pgcrypto;

-- ---------------------------------------------------------------------------
-- 1. profiles: one row per auth user, holds role + email. Auto-created by a
--    trigger when a user signs up (handle_new_user below).
-- ---------------------------------------------------------------------------
-- display_name / phone / gender / date_of_birth are all REQUIRED at
-- registration (validated by the API in auth/routes.py) but nullable here, so
-- staff accounts created through the Supabase admin API don't break.
-- Age is NOT stored: it is derived from date_of_birth on read, so it can never
-- go stale (repo.profile_age).
create table public.profiles (
    id            uuid primary key references auth.users(id) on delete cascade,
    email         text,
    display_name  text,
    phone         text,
    gender        text check (gender is null or gender in
                  ('female', 'male', 'other', 'prefer_not_to_say')),
    date_of_birth date check (date_of_birth is null or
                  (date_of_birth > '1900-01-01' and date_of_birth < current_date)),
    role          text not null default 'user'
                  check (role in ('user', 'staff', 'admin')),
    created_at    timestamptz not null default now()
);

-- Auto-create a profile row whenever a new auth user is created. The details
-- collected at sign-up arrive via the signup metadata (register() passes
-- options.data), so they land here even before the email is verified.
-- nullif(...,'') keeps a blank string out of the date column (it would raise);
-- the API has already validated these, so a blank only happens for accounts
-- created outside the registration form.
create or replace function public.handle_new_user()
returns trigger
language plpgsql
security definer set search_path = public
as $$
begin
    insert into public.profiles (id, email, display_name, phone,
                                 gender, date_of_birth)
    values (new.id,
            new.email,
            nullif(new.raw_user_meta_data->>'display_name', ''),
            nullif(new.raw_user_meta_data->>'phone', ''),
            nullif(new.raw_user_meta_data->>'gender', ''),
            nullif(new.raw_user_meta_data->>'date_of_birth', '')::date)
    on conflict (id) do nothing;
    return new;
end;
$$;

create trigger on_auth_user_created
    after insert on auth.users
    for each row execute function public.handle_new_user();

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

-- ---------------------------------------------------------------------------
-- 2. agreements: the user agreement text, versioned and stored in the DB so it
--    can be shown before registration and edited without a code change.
-- ---------------------------------------------------------------------------
create table public.agreements (
    id         uuid primary key default gen_random_uuid(),
    version    text not null unique,
    title      text not null,
    content    text not null,
    is_active  boolean not null default true,
    created_at timestamptz not null default now()
);

-- agreement_acceptances: which user accepted which agreement version.
create table public.agreement_acceptances (
    id           uuid primary key default gen_random_uuid(),
    user_id      uuid not null references auth.users(id) on delete cascade,
    agreement_id uuid not null references public.agreements(id) on delete cascade,
    accepted_at  timestamptz not null default now(),
    unique (user_id, agreement_id)
);

create index idx_acceptances_agreement on public.agreement_acceptances(agreement_id);

-- ---------------------------------------------------------------------------
-- 3. prompts: the agents' system prompts, editable in the admin dashboard's
--    Prompts editor (or Supabase) without a code change. Seeded on first boot
--    from the bundled .txt files. `key` is the single identifier used by BOTH
--    the app's prompt loader and the admin editor ('composed', 'summarise').
-- ---------------------------------------------------------------------------
create table public.prompts (
    id          uuid primary key default gen_random_uuid(),
    key         text not null unique,
    content     text not null,
    description text,
    updated_at  timestamptz not null default now()
);

-- ---------------------------------------------------------------------------
-- 4. sessions: one chat thread per row.
--    mode: 'multi' = normal instant replies; 'experiment' = supervised
--    (every reply reviewed by staff on the Live Counselling page).
-- ---------------------------------------------------------------------------
create table public.sessions (
    id         uuid primary key default gen_random_uuid(),
    user_id    uuid not null references auth.users(id) on delete cascade,
    title      text not null default 'New chat',
    mode       text not null default 'multi'
               check (mode in ('multi', 'experiment')),
    created_at timestamptz not null default now()
);

create index idx_sessions_user on public.sessions(user_id, created_at desc);
-- The Live Counselling page polls the experiment-session list.
create index idx_sessions_experiment
    on public.sessions(created_at desc) where mode = 'experiment';

-- ---------------------------------------------------------------------------
-- 5. messages: one conversation turn per row.
--
--   draft_reply  what the multi-agent pipeline generated (in normal chats it
--                equals reply; in experiment chats it is the reviewed draft)
--   reply        what the USER sees; NULL while a turn awaits review
--   status       'delivered' normal chat, instant reply (terminal)
--                'pending'   experiment chat, awaiting staff review
--                'approved'  staff delivered the draft verbatim (terminal)
--                'rejected'  staff replaced the draft with their own reply;
--                            reply = staff text, draft_reply keeps the
--                            rejected original (terminal)
--   reviewed_by / reviewed_at  which staff member resolved it, and when
--   rating / feedback / feedback_by / feedback_at  staff review of the reply
-- ---------------------------------------------------------------------------
create table public.messages (
    id                 uuid primary key default gen_random_uuid(),
    session_id         uuid not null references public.sessions(id) on delete cascade,
    user_id            uuid not null references auth.users(id) on delete cascade,
    question           text not null,
    draft_reply        text,
    reply              text,
    status             text not null default 'delivered'
                       check (status in ('delivered', 'pending', 'approved', 'rejected')),
    reviewed_by        uuid references auth.users(id) on delete set null,
    reviewed_at        timestamptz,
    emotion            text,
    emotion_confidence real,
    escalated          boolean not null default false,
    summary            text,
    rating             smallint constraint messages_rating_range
                       check (rating is null or rating between 1 and 5),
    feedback           text,
    feedback_by        uuid references auth.users(id) on delete set null,
    feedback_at        timestamptz,
    created_at         timestamptz not null default now()
);

-- Transcript reads + the user chat's pending poll (both filter by session).
create index idx_messages_session on public.messages(session_id, created_at);
-- The staff review queue reads pending turns crisis-first, oldest-first.
create index idx_messages_pending
    on public.messages (escalated desc, created_at) where status = 'pending';
-- Per-user reads (admin review, all-user emotion analysis) + fast cascades.
create index idx_messages_user on public.messages(user_id, created_at);

-- ---------------------------------------------------------------------------
-- 6. resources: mental-health info cards, imported by scripts/scrape_resources.py
--    and editable in the admin dashboard (the script full-replaces the table).
--   kind:         'article' = in-house info + steps tabs
--                 'video'   = YouTube video (embedded in the detail view)
--                 'link'    = external article/guide (opens in a new tab)
--                 'test'    = external self-assessment (opens in a new tab)
--   external_url: target for video/link/test rows (null for articles)
--   source:       who hosts the content, e.g. 'helpguide.org' (shown on cards)
-- ---------------------------------------------------------------------------
create table public.resources (
    id           uuid primary key default gen_random_uuid(),
    slug         text not null unique,
    title        text not null,
    category     text,
    summary      text,
    info         text,
    kind         text not null default 'article'
                 check (kind in ('article', 'video', 'link', 'test')),
    external_url text,
    source       text,
    image_url    text,
    is_published boolean not null default true,
    sort_order   int not null default 0,
    created_at   timestamptz not null default now()
);

create table public.resource_steps (
    id          uuid primary key default gen_random_uuid(),
    resource_id uuid not null references public.resources(id) on delete cascade,
    step_order  int not null default 0,
    title       text,
    content     text not null
);

create index idx_steps_resource on public.resource_steps(resource_id, step_order);

-- ---------------------------------------------------------------------------
-- 7. Self-tests. `test` holds the screening instruments (questions + scoring
--    as JSON, seeded on boot from app/resources/self_test/definitions.py).
--    Every completed attempt lands in `test_created`.
-- ---------------------------------------------------------------------------
create table public.test (
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

create table public.test_created (
    id         uuid primary key default gen_random_uuid(),
    user_id    uuid not null references auth.users(id) on delete cascade,
    test_id    uuid not null references public.test(id) on delete cascade,
    answer     jsonb not null,    -- list of chosen option indexes
    score      int,
    band       text,
    created_at timestamptz not null default now()
);

create index idx_test_created_user on public.test_created(user_id, created_at desc);
-- Self-test analytics aggregates attempts per test; also speeds cascades.
create index idx_test_created_test on public.test_created(test_id);

-- ---------------------------------------------------------------------------
-- 8. bench_result: the staff "Test Chat" comparison bench. One row per model
--    VARIANT per run (run_id groups them): 3-model comparisons and
--    single-agent-vs-multi-agent runs, each ratable with feedback.
--    (Normal "chat as a user" testing keeps using sessions/messages + the
--    messages feedback columns — this table is only for comparison runs.)
-- ---------------------------------------------------------------------------
-- bench_session: a comparison CHAT (like a user session, but for the bench):
-- multiple runs (turns) grouped under a renamable/deletable title, scoped to
-- the staff member who created it. Each variant keeps its own conversation
-- history across the session's turns.
create table public.bench_session (
    id         uuid primary key default gen_random_uuid(),
    staff_id   uuid not null references auth.users(id) on delete cascade,
    mode       text not null check (mode in ('models3', 'single_vs_multi')),
    title      text not null default 'New comparison',
    created_at timestamptz not null default now()
);
create index idx_bench_session_staff on public.bench_session(staff_id, created_at desc);

create table public.bench_result (
    id         uuid primary key default gen_random_uuid(),
    staff_id   uuid not null references auth.users(id) on delete cascade,
    session_id uuid references public.bench_session(id) on delete cascade,
    run_id     uuid not null,            -- groups the variants of one run/turn
    mode       text not null check (mode in ('models3', 'single_vs_multi')),
    prompt     text not null,            -- the staff member's test message
    variant    text not null,            -- gemma2|llama32|qwen3|single|multi
    label      text,                     -- human-readable variant name
    reply      text,                     -- null when the variant errored
    error      text,                     -- load/inference failure, if any
    latency_ms int,
    rating     int check (rating between 1 and 5),
    feedback   text,
    created_at timestamptz not null default now()
);

create index idx_bench_result_created on public.bench_result(created_at desc);
create index idx_bench_result_run on public.bench_result(run_id);

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
alter table public.test                  enable row level security;
alter table public.test_created          enable row level security;
alter table public.bench_result          enable row level security;
alter table public.bench_session         enable row level security;

-- profiles: a user sees/edits their own row; staff/admins see all.
create policy profiles_select on public.profiles
    for select using (auth.uid() = id or public.is_admin());
create policy profiles_update on public.profiles
    for update using (auth.uid() = id);

-- agreements: anyone may read; only staff/admins may write.
create policy agreements_read on public.agreements for select using (true);
create policy agreements_admin on public.agreements
    for all using (public.is_admin()) with check (public.is_admin());

-- prompts: anyone may read; only staff/admins may edit.
create policy prompts_read on public.prompts for select using (true);
create policy prompts_admin on public.prompts
    for all using (public.is_admin()) with check (public.is_admin());

-- agreement_acceptances: a user manages only their own.
create policy acceptances_own on public.agreement_acceptances
    for all using (auth.uid() = user_id) with check (auth.uid() = user_id);

-- sessions / messages: owner-only.
create policy sessions_own on public.sessions
    for all using (auth.uid() = user_id) with check (auth.uid() = user_id);
create policy messages_own on public.messages
    for all using (auth.uid() = user_id) with check (auth.uid() = user_id);

-- resources / steps: published rows are world-readable; staff/admins manage.
create policy resources_read on public.resources
    for select using (is_published or public.is_admin());
create policy resources_admin on public.resources
    for all using (public.is_admin()) with check (public.is_admin());
create policy steps_read on public.resource_steps for select using (true);
create policy steps_admin on public.resource_steps
    for all using (public.is_admin()) with check (public.is_admin());

-- self-tests: published instruments are world-readable; attempts are owner-only.
create policy test_read on public.test
    for select using (is_published or public.is_admin());
create policy test_admin on public.test
    for all using (public.is_admin()) with check (public.is_admin());
create policy test_created_own on public.test_created
    for all using (auth.uid() = user_id) with check (auth.uid() = user_id);

-- bench results: staff/admin only (the backend enforces this via staff_required;
-- this is defense-in-depth like every other policy here).
create policy bench_result_staff on public.bench_result
    for all using (public.is_admin()) with check (public.is_admin());
create policy bench_session_staff on public.bench_session
    for all using (public.is_admin()) with check (public.is_admin());

-- ===========================================================================
-- Bootstrap the first admin (run AFTER registering + verifying the account
-- in the app — a reset deletes all accounts, so this is needed every time):
--
--   update public.profiles set role = 'admin' where email = 'you@example.com';
-- ===========================================================================
