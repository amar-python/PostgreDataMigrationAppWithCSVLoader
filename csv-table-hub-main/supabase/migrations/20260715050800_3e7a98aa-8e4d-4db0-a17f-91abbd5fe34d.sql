
create extension if not exists pgcrypto;

create table public.csv_files (
  id uuid primary key default gen_random_uuid(),
  file_name text not null,
  file_hash text not null unique,
  table_name text not null unique,
  row_count integer not null default 0,
  column_names text[] not null default '{}',
  created_at timestamptz not null default now()
);

grant select on public.csv_files to anon, authenticated;
grant all on public.csv_files to service_role;

alter table public.csv_files enable row level security;

create policy "Anyone can view csv_files"
  on public.csv_files for select
  using (true);

create or replace function public.create_csv_table(p_table_name text, p_columns text[])
returns void
language plpgsql
security definer
set search_path = public
as $$
declare
  col_defs text;
begin
  if p_table_name !~ '^csv_[a-z0-9_]{1,60}$' then
    raise exception 'Invalid table name: %', p_table_name;
  end if;

  if array_length(p_columns, 1) is null then
    raise exception 'At least one column is required';
  end if;

  select string_agg(format('%I text', c), ', ')
  into col_defs
  from unnest(p_columns) as c;

  execute format(
    'create table if not exists public.%I (_id bigserial primary key, %s, _row_hash text not null unique, _created_at timestamptz not null default now())',
    p_table_name, col_defs
  );

  execute format('grant select on public.%I to anon, authenticated', p_table_name);
  execute format('grant all on public.%I to service_role', p_table_name);
  execute format('alter table public.%I enable row level security', p_table_name);
  execute format(
    'create policy %I on public.%I for select using (true)',
    'read_' || p_table_name, p_table_name
  );
end;
$$;

revoke all on function public.create_csv_table(text, text[]) from public;
grant execute on function public.create_csv_table(text, text[]) to service_role;
