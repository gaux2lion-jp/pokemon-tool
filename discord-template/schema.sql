-- SUMdex shared workspace. Apply once using the Supabase SQL editor.
begin;
create schema if not exists sumdex_private;
revoke all on schema sumdex_private from public;
grant usage on schema sumdex_private to authenticated;
create table public.sumdex_members (
 email text primary key check (email = lower(trim(email))),
 role text not null check (role in ('admin','editor')),
 active boolean not null default true
);
alter table public.sumdex_members enable row level security;
revoke all on public.sumdex_members from anon, authenticated;
create function sumdex_private.member_role() returns text
language sql stable security definer set search_path = '' as $$
 select m.role from public.sumdex_members m
 join auth.users u on lower(u.email) = m.email
 where u.id = (select auth.uid()) and u.email_confirmed_at is not null
 and m.active and exists (select 1 from auth.identities i where i.user_id=u.id and i.provider='google')
$$;
revoke all on function sumdex_private.member_role() from public;
grant execute on function sumdex_private.member_role() to authenticated;
create policy member_read on public.sumdex_members for select to authenticated
 using ((select sumdex_private.member_role()) is not null);
create policy member_add on public.sumdex_members for insert to authenticated
 with check ((select sumdex_private.member_role()) = 'admin');
create policy member_edit on public.sumdex_members for update to authenticated
 using ((select sumdex_private.member_role()) = 'admin' and email <> lower((select auth.jwt()->>'email')))
 with check ((select sumdex_private.member_role()) = 'admin' and email <> lower((select auth.jwt()->>'email')));
grant select, insert, update on public.sumdex_members to authenticated;
create table public.sumdex_documents (
 id text primary key,
 kind text not null check (kind in ('catalog','settings','draft')),
 data jsonb not null check (jsonb_typeof(data)='object'),
 version integer not null default 1 check(version>0),
 updated_at timestamptz not null default now(),
 updated_by uuid default auth.uid()
);
alter table public.sumdex_documents enable row level security;
revoke all on public.sumdex_documents from anon, authenticated;
grant select, insert, update on public.sumdex_documents to authenticated;
create policy document_read on public.sumdex_documents for select to authenticated
 using ((select sumdex_private.member_role()) is not null);
create policy document_insert on public.sumdex_documents for insert to authenticated
 with check ((select sumdex_private.member_role()) is not null and version=1 and updated_by=(select auth.uid()));
create policy document_update on public.sumdex_documents for update to authenticated
 using ((select sumdex_private.member_role()) is not null)
 with check ((select sumdex_private.member_role()) is not null and updated_by=(select auth.uid()));
create function sumdex_private.document_version() returns trigger
language plpgsql set search_path = '' as $$
begin
 if new.id<>old.id or new.kind<>old.kind then raise exception 'Identity cannot change'; end if;
 if new.version <> old.version + 1 then raise exception 'Version conflict'; end if;
 new.updated_at=now(); new.updated_by=auth.uid(); return new;
end;
$$;
revoke all on function sumdex_private.document_version() from public;
create trigger version_guard before update on public.sumdex_documents
 for each row execute function sumdex_private.document_version();
create index sumdex_documents_kind on public.sumdex_documents(kind);
commit;
