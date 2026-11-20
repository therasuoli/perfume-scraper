-- Larsi Perfume Finder / Perfume Scraper schema (Supabase SQL Editor)
-- Run safely: existing table and records are preserved.
create table if not exists public.perfumes (
  id text primary key,
  payload jsonb not null default '{}'::jsonb
);

-- If the table already exists, ensure the payload field is present and JSONB.
-- (No existing rows are deleted or truncated.)
alter table public.perfumes
  add column if not exists payload jsonb not null default '{}'::jsonb;

create index if not exists perfumes_payload_name_idx
  on public.perfumes ((payload ->> 'name'));
create index if not exists perfumes_payload_brand_idx
  on public.perfumes ((payload ->> 'brand'));
create index if not exists perfumes_payload_country_idx
  on public.perfumes ((payload ->> 'country_of_origin'));
create index if not exists perfumes_payload_family_idx
  on public.perfumes ((payload ->> 'family'));
create index if not exists perfumes_payload_category_idx
  on public.perfumes ((payload ->> 'category'));

alter table public.perfumes enable row level security;
-- Public catalog reads for the PWA. Writes are performed by server-side scraper
-- using a service-role secret (never expose that secret in client code).
drop policy if exists "Public can read perfume catalogue" on public.perfumes;
create policy "Public can read perfume catalogue"
  on public.perfumes for select to anon, authenticated using (true);

grant select on public.perfumes to anon, authenticated;
-- Service-role key bypasses RLS; no public insert/update/delete policy is added.
