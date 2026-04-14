from supabase import create_client, Client
from app.core.config import settings
from functools import lru_cache


@lru_cache
def get_supabase() -> Client:
    """
    Cliente Supabase com a anon key — para operações normais
    respeitando as políticas de RLS.
    """
    return create_client(settings.supabase_url, settings.supabase_anon_key)


@lru_cache
def get_supabase_admin() -> Client:
    """
    Cliente Supabase com a service role key — ignora RLS.
    Usar APENAS em operações administrativas internas (ex: criar usuário,
    gerar magic link, tarefas Celery). NUNCA expor ao frontend.
    """
    return create_client(settings.supabase_url, settings.supabase_service_role_key)


supabase: Client = get_supabase()
supabase_admin: Client = get_supabase_admin()
