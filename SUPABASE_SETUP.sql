create table if not exists public.creatorlift_state (
    id text primary key,
    data jsonb not null default '{}'::jsonb,
    updated_at timestamptz not null default now()
);

create or replace function public.set_creatorlift_state_updated_at()
returns trigger as $$
begin
    new.updated_at = now();
    return new;
end;
$$ language plpgsql;

drop trigger if exists creatorlift_state_updated_at on public.creatorlift_state;

create trigger creatorlift_state_updated_at
before update on public.creatorlift_state
for each row
execute function public.set_creatorlift_state_updated_at();

alter table public.creatorlift_state enable row level security;

drop policy if exists "CreatorLift service role only" on public.creatorlift_state;

create policy "CreatorLift service role only"
on public.creatorlift_state
for all
using (auth.role() = 'service_role')
with check (auth.role() = 'service_role');
