
-- 1. Add owner_id to csv_files
ALTER TABLE public.csv_files ADD COLUMN IF NOT EXISTS owner_id uuid REFERENCES auth.users(id) ON DELETE CASCADE;
CREATE INDEX IF NOT EXISTS csv_files_owner_id_idx ON public.csv_files(owner_id);

-- 2. Drop existing permissive policies on csv_files
DROP POLICY IF EXISTS "Anyone can view csv_files" ON public.csv_files;
DROP POLICY IF EXISTS "Anyone can insert csv_files" ON public.csv_files;
DROP POLICY IF EXISTS "Anyone can update csv_files" ON public.csv_files;
DROP POLICY IF EXISTS "Anyone can delete csv_files" ON public.csv_files;

-- 3. Revoke public/anon access on csv_files
REVOKE ALL ON public.csv_files FROM anon;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.csv_files TO authenticated;
GRANT ALL ON public.csv_files TO service_role;

-- 4. Owner-scoped policies on csv_files
CREATE POLICY "Owners can view their csv_files"
  ON public.csv_files FOR SELECT TO authenticated
  USING (auth.uid() = owner_id);
CREATE POLICY "Owners can insert their csv_files"
  ON public.csv_files FOR INSERT TO authenticated
  WITH CHECK (auth.uid() = owner_id);
CREATE POLICY "Owners can update their csv_files"
  ON public.csv_files FOR UPDATE TO authenticated
  USING (auth.uid() = owner_id) WITH CHECK (auth.uid() = owner_id);
CREATE POLICY "Owners can delete their csv_files"
  ON public.csv_files FOR DELETE TO authenticated
  USING (auth.uid() = owner_id);

-- 5. Drop permissive read policies + revoke anon on every existing csv_* data table
DO $$
DECLARE
  t record;
  pol record;
BEGIN
  FOR t IN
    SELECT c.relname AS tname
    FROM pg_class c
    JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = 'public'
      AND c.relkind = 'r'
      AND c.relname LIKE 'csv\_%' ESCAPE '\'
      AND c.relname <> 'csv_files'
  LOOP
    FOR pol IN
      SELECT policyname FROM pg_policies
      WHERE schemaname = 'public' AND tablename = t.tname
    LOOP
      EXECUTE format('DROP POLICY IF EXISTS %I ON public.%I', pol.policyname, t.tname);
    END LOOP;
    EXECUTE format('REVOKE ALL ON public.%I FROM anon', t.tname);
    EXECUTE format('REVOKE ALL ON public.%I FROM authenticated', t.tname);
    EXECUTE format('GRANT ALL ON public.%I TO service_role', t.tname);
  END LOOP;
END $$;

-- 6. Update create_csv_table to no longer create public read policies or anon/authenticated grants
CREATE OR REPLACE FUNCTION public.create_csv_table(p_table_name text, p_columns text[], p_types text[])
 RETURNS void
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'public'
AS $function$
declare
  col_defs text;
  allowed_types text[] := array['int8','numeric','date','timestamptz','boolean','text'];
  idx int;
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

  for idx in 1..array_length(p_types, 1) loop
    t := p_types[idx];
    if not (t = any(allowed_types)) then
      raise exception 'Disallowed column type: %', t;
    end if;
  end loop;

  select string_agg(format('%I %s', p_columns[s], p_types[s]), ', ')
  into col_defs
  from generate_subscripts(p_columns, 1) as s;

  execute format(
    'create table if not exists public.%I (_id bigserial primary key, %s, _row_hash text not null unique, _created_at timestamptz not null default now())',
    p_table_name, col_defs
  );

  -- Private by default: only service_role can touch the raw table.
  -- Application access is mediated by server functions that verify ownership via csv_files.
  execute format('revoke all on public.%I from anon', p_table_name);
  execute format('revoke all on public.%I from authenticated', p_table_name);
  execute format('grant all on public.%I to service_role', p_table_name);
  execute format('alter table public.%I enable row level security', p_table_name);
end;
$function$;
