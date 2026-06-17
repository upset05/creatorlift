import os
import requests

STATE_ID = 'creatorlift'


def supabase_config_status():
    required = {
        'SUPABASE_URL': os.environ.get('SUPABASE_URL', '').rstrip('/'),
        'SUPABASE_SERVICE_ROLE_KEY': os.environ.get('SUPABASE_SERVICE_ROLE_KEY', ''),
    }
    missing = [key for key, value in required.items() if not value]
    return {
        'configured': not missing,
        'missing': missing,
        'url': required['SUPABASE_URL'],
    }


def _headers(config):
    key = os.environ.get('SUPABASE_SERVICE_ROLE_KEY', '')
    return {
        'apikey': key,
        'Authorization': f'Bearer {key}',
        'Content-Type': 'application/json',
        'Prefer': 'return=representation',
    }


def load_state_from_supabase():
    config = supabase_config_status()
    if not config['configured']:
        return None, 'Supabase is not configured.'

    url = f"{config['url']}/rest/v1/creatorlift_state?id=eq.{STATE_ID}&select=data"
    response = requests.get(url, headers=_headers(config), timeout=20)
    if response.status_code >= 400:
        return None, f"Supabase load error {response.status_code}: {response.text}"

    rows = response.json()
    if not rows:
        return None, ''
    return rows[0].get('data') or None, ''


def save_state_to_supabase(data):
    config = supabase_config_status()
    if not config['configured']:
        return False, 'Supabase is not configured.'

    url = f"{config['url']}/rest/v1/creatorlift_state"
    payload = {
        'id': STATE_ID,
        'data': data,
    }
    response = requests.post(
        url,
        headers={**_headers(config), 'Prefer': 'resolution=merge-duplicates,return=minimal'},
        json=payload,
        timeout=20,
    )
    if response.status_code >= 400:
        return False, f"Supabase save error {response.status_code}: {response.text}"
    return True, ''
