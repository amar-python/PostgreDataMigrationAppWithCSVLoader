
-- Replace create_csv_table with a typed version. Old signature is dropped.
DROP FUNCTION IF EXISTS public.create_csv_table(text, text[]);
DROP FUNCTION IF EXISTS public.create_csv_table(text, text[], text[]);

CREATE OR REPLACE FUNCTION public.create_csv_table(
  p_table_name text,
  p_columns text[],
  p_types text[]
)
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path TO 'public'
AS $function$
declare
  col_defs text;
  allowed_types text[] := array['int8','numeric','date','timestamptz','boolean','text'];
  i int;
  t text;
begin
  if p_table_name !~ '^csv_[a-z0-9_]{1,60}$' then
    raise exception 'Invalid table name: %', p_table_name;
  end if;

  if array_length(p_columns, 1) is null then
    raise exception 'At least one column is required';
  end if;

  if array_length(p_columns, 1) <> array_length(p_types, 1) then
    raise exception 'columns and types length mismatch';
  end if;

  -- validate every type
  for i in 1..array_length(p_types, 1) loop
    t := p_types[i];
    if not (t = any(allowed_types)) then
      raise exception 'Disallowed column type: %', t;
    end if;
  end loop;

  select string_agg(format('%I %s', p_columns[i], p_types[i]), ', ')
  into col_defs
  from generate_subscripts(p_columns, 1) as i;

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
$function$;
