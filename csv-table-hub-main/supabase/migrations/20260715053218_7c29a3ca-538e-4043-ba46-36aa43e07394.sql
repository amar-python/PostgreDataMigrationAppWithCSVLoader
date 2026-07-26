
REVOKE EXECUTE ON FUNCTION public.create_csv_table(text, text[], text[]) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.create_csv_table(text, text[], text[]) FROM anon;
REVOKE EXECUTE ON FUNCTION public.create_csv_table(text, text[], text[]) FROM authenticated;
GRANT EXECUTE ON FUNCTION public.create_csv_table(text, text[], text[]) TO service_role;
