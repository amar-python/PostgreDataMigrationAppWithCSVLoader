
revoke execute on function public.create_csv_table(text, text[]) from public, anon, authenticated;
grant execute on function public.create_csv_table(text, text[]) to service_role;
