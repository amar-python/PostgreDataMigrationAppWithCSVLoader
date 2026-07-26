
ALTER TABLE public.csv_files DROP CONSTRAINT IF EXISTS csv_files_file_hash_key;
ALTER TABLE public.csv_files DROP CONSTRAINT IF EXISTS csv_files_file_name_key;
ALTER TABLE public.csv_files ADD CONSTRAINT csv_files_owner_file_hash_key UNIQUE (owner_id, file_hash);
ALTER TABLE public.csv_files ADD CONSTRAINT csv_files_owner_file_name_key UNIQUE (owner_id, file_name);
