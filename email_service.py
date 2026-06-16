import os
import requests

RESEND_API_URL = 'https://api.resend.com/emails'


def resend_config_status():
    required = {
        'RESEND_API_KEY': os.environ.get('RESEND_API_KEY', ''),
        'RESEND_FROM_EMAIL': os.environ.get('RESEND_FROM_EMAIL', ''),
        'ADMIN_EMAIL': os.environ.get('ADMIN_EMAIL', ''),
        'NEXT_PUBLIC_APP_URL': os.environ.get('NEXT_PUBLIC_APP_URL', ''),
    }
    missing = [key for key, value in required.items() if not value]
    return {
        'configured': not missing,
        'missing': missing,
        'from_email': required['RESEND_FROM_EMAIL'],
        'admin_email': required['ADMIN_EMAIL'],
        'app_url': required['NEXT_PUBLIC_APP_URL'].rstrip('/'),
    }


def send_creatorlift_email(to_email, subject, text_body, html_body=None, tags=None):
    config = resend_config_status()
    result = {
        'provider': 'resend',
        'to': to_email,
        'subject': subject,
        'sent': False,
        'provider_id': '',
        'error': '',
        'missing_config': config['missing'],
    }

    if not to_email:
        result['error'] = 'Recipient email is missing.'
        return result

    if not config['configured']:
        result['error'] = f"Missing Resend environment variables: {', '.join(config['missing'])}"
        return result

    payload = {
        'from': config['from_email'],
        'to': [to_email],
        'subject': subject,
        'text': text_body,
    }
    if html_body:
        payload['html'] = html_body
    if tags:
        payload['tags'] = tags

    try:
        response = requests.post(
            RESEND_API_URL,
            headers={
                'Authorization': f"Bearer {os.environ.get('RESEND_API_KEY')}",
                'Content-Type': 'application/json',
            },
            json=payload,
            timeout=20,
        )
        if response.status_code >= 400:
            result['error'] = f"Resend API error {response.status_code}: {response.text}"
            return result

        data = response.json()
        result['sent'] = True
        result['provider_id'] = data.get('id', '')
        return result
    except Exception as exc:
        result['error'] = str(exc)
        return result
