-- Shared public reference images. Writes require an approved Google member.
insert into storage.buckets(id,name,public,file_size_limit,allowed_mime_types)
values ('sumdex-products','sumdex-products',true,2097152,array['image/webp'])
on conflict(id) do nothing;
create policy sumdex_product_image_insert on storage.objects for insert to authenticated
with check(bucket_id='sumdex-products' and (select sumdex_private.member_role()) is not null);
-- Immutable UUID filenames: replacing an image creates a new object, preserving posted links.
create table public.sumdex_post_config(id boolean primary key default true check(id), data jsonb not null);
create table public.sumdex_posts(id uuid primary key, owner uuid not null, state text not null default 'ready', data jsonb not null, created_at timestamptz not null default now());
alter table public.sumdex_post_config enable row level security;
alter table public.sumdex_posts enable row level security;
revoke all on public.sumdex_post_config,public.sumdex_posts from anon,authenticated;
grant all on public.sumdex_post_config,public.sumdex_posts to service_role;
-- Server-only tables intentionally have no client policies.
create policy server_manages_post_config on public.sumdex_post_config for all to service_role using(true) with check(true);
create policy server_manages_posts on public.sumdex_posts for all to service_role using(true) with check(true);

-- Posting validates the shared catalog/settings without modifying them.
grant select on public.sumdex_documents to service_role;
