CREATE OR REPLACE FUNCTION public.drop_csv_table(p_table_name text)
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
  IF p_table_name !~ '^csv_[a-z0-9_]{1,60}$' THEN
    RAISE EXCEPTION 'Invalid table name: %', p_table_name;
  END IF;
  EXECUTE format('DROP TABLE IF EXISTS public.%I', p_table_name);
END;
$$;

REVOKE ALL ON FUNCTION public.drop_csv_table(text) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.drop_csv_table(text) TO service_role;