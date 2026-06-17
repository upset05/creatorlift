from datetime import datetime, timedelta, timezone
from functools import wraps
from flask import Flask, request, jsonify, send_from_directory, session
from flask_cors import CORS
import html
import json
import os
import re
import uuid
import requests
from email_service import resend_config_status, send_creatorlift_email
from storage_service import load_state_from_supabase, save_state_to_supabase, supabase_config_status
from plans_config import PLANS

app = Flask(__name__, static_folder='.')
CORS(app)
app.secret_key = (
    os.environ.get('CREATORLIFT_SECRET_KEY')
    or os.environ.get('SECRET_KEY')
    or 'dev-only-change-this-secret'
)

# --- CONFIG ---
ADMIN_PASSWORD = os.environ.get('CREATORLIFT_ADMIN_PASSWORD') or os.environ.get('ADMIN_PASSWORD')
PAYSTACK_SECRET_KEY = os.environ.get('PAYSTACK_SECRET_KEY', '')
DB_FILE = 'db.json'

CAMPAIGN_STATUSES = [
    'pending_payment',
    'paid_pending_review',
    'approved_for_setup',
    'rejected_refunded',
    'campaign_active',
    'campaign_completed',
]

PLAN_AMOUNTS = {name: info['price'] for name, info in PLANS.items()}
PLAN_DURATIONS = {name: info['duration_days'] for name, info in PLANS.items()}


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def default_db():
    return {
        'campaigns': [],
        'orders': [],
        'active_target': 'None',
        'stats': {'revenue': 0, 'manual_metric': 0, 'hours': 0},
        'email_log': [],
        'resend_config': resend_config_status(),
        'supabase_config': supabase_config_status(),
    }


def load_db():
    supabase_status = supabase_config_status()
    if supabase_status['configured']:
        data, error = load_state_from_supabase()
        if data:
            changed = migrate_db(data)
            if changed:
                save_db(data)
            return data
        if not error:
            data = default_db()
            save_db(data)
            return data
        print(f"Supabase load warning: {error}")

    if not os.path.exists(DB_FILE):
        data = default_db()
        save_db(data)
        return data

    with open(DB_FILE, 'r', encoding='utf-8') as f:
        data = json.load(f)

    changed = migrate_db(data)
    if changed:
        save_db(data)
    return data


def save_db(data):
    data['resend_config'] = resend_config_status()
    data['supabase_config'] = supabase_config_status()
    if data['supabase_config']['configured']:
        ok, error = save_state_to_supabase(data)
        if ok:
            return
        print(f"Supabase save warning: {error}")

    with open(DB_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4)


def migrate_db(data):
    changed = False
    defaults = default_db()
    for key, value in defaults.items():
        if key not in data:
            data[key] = value
            changed = True

    data.setdefault('stats', {})
    if 'manual_metric' not in data['stats']:
        data['stats']['manual_metric'] = data['stats'].get('hours', 0)
        changed = True
    if 'revenue' not in data['stats']:
        data['stats']['revenue'] = 0
        changed = True

    if not data.get('campaigns') and data.get('orders'):
        campaigns = []
        for index, order in enumerate(data.get('orders', []), start=1):
            campaigns.append(campaign_from_legacy_order(order, index))
        data['campaigns'] = campaigns
        changed = True

    # Migrate old plans to new plan names / amounts to maintain consistency
    for c in data.get('campaigns', []):
        old_plan = c.get('plan')
        if old_plan == 'Starter Campaign' and (c.get('amount_paid') == 15000 or c.get('amount_expected') == 15000):
            c['plan'] = 'Growth Accelerator'
            c['amount_expected'] = 15000
            c['promotion_duration_days'] = 10
            changed = True
        elif old_plan == 'Growth Accelerator' and (c.get('amount_paid') == 45000 or c.get('amount_expected') == 45000):
            c['plan'] = 'Professional Campaign'
            c['amount_expected'] = 45000
            c['promotion_duration_days'] = 14
            changed = True

    for o in data.get('orders', []):
        old_plan = o.get('plan')
        if old_plan == 'Starter Campaign' and o.get('amount') == 15000:
            o['plan'] = 'Growth Accelerator'
            changed = True
        elif old_plan == 'Growth Accelerator' and o.get('amount') == 45000:
            o['plan'] = 'Professional Campaign'
            changed = True

    next_id = 1
    for campaign in data.get('campaigns', []):
        changed = ensure_campaign_shape(campaign, next_id) or changed
        next_id = max(next_id, int(campaign.get('id', 0)) + 1)

    return changed


def campaign_from_legacy_order(order, fallback_id):
    video_id = extract_youtube_video_id(order.get('video_url', ''))
    plan = normalize_plan(order.get('plan', 'Starter Campaign'))
    status_map = {
        'paid': 'paid_pending_review',
        'active': 'campaign_active',
        'unpaid': 'pending_payment',
    }
    created_at = order.get('created_at') or now_iso()
    return {
        'id': order.get('id') or fallback_id,
        'tracking_code': order.get('tracking_code') or make_tracking_code(),
        'created_at': created_at,
        'updated_at': created_at,
        'email': order.get('email', ''),
        'video_url': order.get('video_url', ''),
        'video_id': video_id,
        'thumbnail': youtube_thumbnail(video_id),
        'video_title': order.get('video_title') or (f'YouTube Video {video_id}' if video_id else 'Submitted YouTube Video'),
        'plan': plan,
        'amount_expected': plan_amount(plan),
        'amount_paid': order.get('amount', 0),
        'currency': 'NGN',
        'status': status_map.get(order.get('status'), 'paid_pending_review'),
        'paystack_reference': order.get('reference', ''),
        'payment_verified_at': order.get('payment_verified_at'),
        'views_before': int(order.get('views_before') or 0),
        'promotion_duration_days': int(order.get('promotion_duration_days') or plan_duration_days(plan)),
        'promotion_started_at': order.get('promotion_started_at'),
        'promotion_ends_at': order.get('promotion_ends_at'),
        'admin_notes': order.get('admin_notes', ''),
        'customer_updates': order.get('customer_updates', []),
        'curation_approved': order.get('curation_approved', False),
        'curation_category': order.get('curation_category', ''),
        'curation_approved_at': order.get('curation_approved_at'),
        'reject_reason': order.get('reject_reason', ''),
        'refund_status': order.get('refund_status', ''),
        'paystack_data': order.get('paystack_data', {}),
        'email_activity': order.get('email_activity', []),
        'email_warnings': order.get('email_warnings', []),
    }


def ensure_campaign_shape(campaign, fallback_id):
    changed = False
    video_id = extract_youtube_video_id(campaign.get('video_url', '')) or campaign.get('video_id', '')
    plan = normalize_plan(campaign.get('plan', 'Discovery Campaign'))
    plan_info = PLANS.get(plan, PLANS['Discovery Campaign'])
    
    defaults = {
        'id': fallback_id,
        'tracking_code': make_tracking_code(),
        'created_at': now_iso(),
        'updated_at': now_iso(),
        'email': '',
        'video_url': '',
        'video_id': video_id,
        'thumbnail': youtube_thumbnail(video_id),
        'video_title': f'YouTube Video {video_id}' if video_id else 'Submitted YouTube Video',
        'plan': plan,
        'amount_expected': plan_amount(plan),
        'amount_paid': 0,
        'currency': 'NGN',
        'status': 'pending_payment',
        'paystack_reference': '',
        'payment_verified_at': None,
        'views_before': 0,
        'promotion_duration_days': plan_duration_days(plan),
        'promotion_started_at': None,
        'promotion_ends_at': None,
        'admin_notes': '',
        'customer_updates': [],
        'curation_approved': False,
        'curation_category': '',
        'curation_approved_at': None,
        'reject_reason': '',
        'refund_status': '',
        'paystack_data': {},
        'email_activity': [],
        'email_warnings': [],
        'plan_name': plan,
        'plan_price': plan_info['price'],
        'plan_badge': plan_info['badge'],
        'plan_description': plan_info['description'],
        'plan_features': plan_info['features'],
        'campaign_duration': plan_info['duration'],
        'support_level': plan_info['support_level'],
        'curation_access_type': plan_info['curation_access_type'],
    }
    for key, value in defaults.items():
        if key not in campaign:
            campaign[key] = value
            changed = True
    if campaign.get('status') not in CAMPAIGN_STATUSES:
        campaign['status'] = 'paid_pending_review' if campaign.get('amount_paid') else 'pending_payment'
        changed = True
    if (campaign.get('plan') != plan or
        'plan_name' not in campaign or
        campaign.get('plan_price') != plan_info['price']):
        campaign['plan'] = plan
        campaign['amount_expected'] = plan_amount(plan)
        campaign['plan_name'] = plan
        campaign['plan_price'] = plan_info['price']
        campaign['plan_badge'] = plan_info['badge']
        campaign['plan_description'] = plan_info['description']
        campaign['plan_features'] = plan_info['features']
        campaign['campaign_duration'] = plan_info['duration']
        campaign['support_level'] = plan_info['support_level']
        campaign['curation_access_type'] = plan_info['curation_access_type']
        if not campaign.get('promotion_duration_days'):
            campaign['promotion_duration_days'] = plan_duration_days(plan)
        changed = True
    if video_id and campaign.get('video_id') != video_id:
        campaign['video_id'] = video_id
        campaign['thumbnail'] = youtube_thumbnail(video_id)
        changed = True
    return changed

def normalize_plan(plan):
    if not plan:
        return 'Discovery Campaign'
    plan_str = str(plan)
    if plan_str in PLAN_AMOUNTS:
        return plan_str
    if 'Discovery' in plan_str or '5000' in plan_str or '5,000' in plan_str:
        return 'Discovery Campaign'
    if 'Starter' in plan_str or '10000' in plan_str or '10,000' in plan_str:
        return 'Starter Campaign'
    if 'Growth' in plan_str or '15000' in plan_str or '15,000' in plan_str:
        return 'Growth Accelerator'
    if 'Professional' in plan_str or '45000' in plan_str or '45,000' in plan_str:
        return 'Professional Campaign'
    if 'Agency' in plan_str or '85000' in plan_str or '85,000' in plan_str:
        return 'Agency Partnership'
    return 'Discovery Campaign'


def plan_amount(plan):
    return PLAN_AMOUNTS.get(plan, PLAN_AMOUNTS['Discovery Campaign'])


def plan_duration_days(plan):
    return PLAN_DURATIONS.get(plan, PLAN_DURATIONS['Discovery Campaign'])
def make_tracking_code():
    return uuid.uuid4().hex[:10]


def extract_youtube_video_id(url):
    if not url:
        return None

    patterns = [
        r'(?:youtube\.com\/watch\?v=)([0-9A-Za-z_-]{11})',
        r'(?:youtu\.be\/)([0-9A-Za-z_-]{11})',
        r'(?:youtube\.com\/shorts\/)([0-9A-Za-z_-]{11})',
        r'(?:youtube\.com\/embed\/)([0-9A-Za-z_-]{11})',
        r'(?:youtube\.com\/live\/)([0-9A-Za-z_-]{11})',
        r'(?:^|[?&])v=([0-9A-Za-z_-]{11})',
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    if re.fullmatch(r'[0-9A-Za-z_-]{11}', url.strip()):
        return url.strip()
    return None


def youtube_thumbnail(video_id):
    if not video_id:
        return ''
    return f'https://img.youtube.com/vi/{video_id}/hqdefault.jpg'


def find_campaign(db, campaign_id):
    for campaign in db.get('campaigns', []):
        if int(campaign.get('id')) == int(campaign_id):
            return campaign
    return None


def find_campaign_by_tracking(db, tracking_code):
    for campaign in db.get('campaigns', []):
        if campaign.get('tracking_code') == tracking_code:
            return campaign
    return None


def find_campaign_by_reference(db, reference):
    for campaign in db.get('campaigns', []):
        if reference and campaign.get('paystack_reference') == reference:
            return campaign
    return None


def next_campaign_id(db):
    ids = [int(c.get('id', 0)) for c in db.get('campaigns', [])]
    return max(ids, default=0) + 1


def public_campaign(campaign):
    return {
        'id': campaign.get('id'),
        'tracking_code': campaign.get('tracking_code'),
        'created_at': campaign.get('created_at'),
        'updated_at': campaign.get('updated_at'),
        'video_url': campaign.get('video_url'),
        'video_id': campaign.get('video_id'),
        'thumbnail': campaign.get('thumbnail'),
        'video_title': campaign.get('video_title'),
        'plan': campaign.get('plan'),
        'amount_expected': campaign.get('amount_expected'),
        'amount_paid': campaign.get('amount_paid'),
        'currency': campaign.get('currency', 'NGN'),
        'status': campaign.get('status'),
        'views_before': campaign.get('views_before', 0),
        'promotion_duration_days': campaign.get('promotion_duration_days'),
        'promotion_started_at': campaign.get('promotion_started_at'),
        'promotion_ends_at': campaign.get('promotion_ends_at'),
        'customer_updates': campaign.get('customer_updates', []),
        'curation_approved': campaign.get('curation_approved', False),
        'curation_category': campaign.get('curation_category', ''),
        'tracking_url': tracking_url_for(campaign),
        'plan_name': campaign.get('plan_name'),
        'plan_price': campaign.get('plan_price'),
        'plan_badge': campaign.get('plan_badge'),
        'plan_description': campaign.get('plan_description'),
        'plan_features': campaign.get('plan_features', []),
        'campaign_duration': campaign.get('campaign_duration'),
        'support_level': campaign.get('support_level'),
        'curation_access_type': campaign.get('curation_access_type'),
    }


def admin_campaign(campaign):
    data = dict(campaign)
    data['tracking_url'] = f"{request.host_url.rstrip('/')}/track/{campaign.get('tracking_code')}"
    data['watch_url'] = f"watch.html?campaign={campaign.get('tracking_code')}"
    return data


def admin_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not session.get('logged_in'):
            return jsonify({'error': 'Unauthorized'}), 401
        return fn(*args, **kwargs)
    return wrapper


def verify_paystack_reference(reference):
    if not reference:
        return False, 'Missing Paystack reference', {}
    if not PAYSTACK_SECRET_KEY or PAYSTACK_SECRET_KEY == 'sk_test_placeholder_for_local_testing':
        return False, 'PAYSTACK_SECRET_KEY is not configured on the server', {}

    headers = {
        'Authorization': f'Bearer {PAYSTACK_SECRET_KEY}',
        'Content-Type': 'application/json',
    }
    verify_url = f'https://api.paystack.co/transaction/verify/{reference}'
    response = requests.get(verify_url, headers=headers, timeout=20)
    response.raise_for_status()
    payload = response.json()
    if not payload.get('status') or payload.get('data', {}).get('status') != 'success':
        return False, 'Payment verification failed', payload
    return True, 'Payment verified', payload


def app_base_url():
    return (os.environ.get('NEXT_PUBLIC_APP_URL') or request.host_url.rstrip('/')).rstrip('/')


def tracking_url_for(campaign):
    return f"{app_base_url()}/track/{campaign.get('tracking_code')}"


def safe_email_html(title, body_lines, action_url=None, action_label='Track Campaign'):
    safe_title = html.escape(title)
    paragraphs = ''.join(f"<p>{html.escape(str(line))}</p>" for line in body_lines)
    action = ''
    if action_url:
        safe_action_url = html.escape(action_url, quote=True)
        safe_action_label = html.escape(action_label)
        action = (
            f'<p><a href="{safe_action_url}" '
            'style="display:inline-block;padding:12px 18px;background:#8b5cf6;color:#ffffff;'
            'border-radius:8px;text-decoration:none;font-weight:700;">'
            f'{safe_action_label}</a></p>'
        )
    return f"""
    <div style="font-family:Inter,Arial,sans-serif;line-height:1.6;color:#111827;">
        <h2>{safe_title}</h2>
        {paragraphs}
        {action}
        <p style="color:#6b7280;font-size:13px;">
            Results vary based on content quality, niche, audience interest, campaign settings, and viewer response.
            Our campaigns are designed to help creators reach relevant viewers, built to increase exposure and discovery,
            and promote content to targeted audiences without promising specific subscriber counts, watch-hour outcomes,
            monetization approval, or revenue.
        </p>
        <p style="color:#9ca3af;font-size:11px;border-top:1px solid #e5e7eb;margin-top:1.5em;padding-top:1em;">
            Creatorlift By The Accountant
        </p>
    </div>
    """


def send_email_event(db, campaign, event, recipient, subject, body_lines, action_url=None, action_label='Track Campaign'):
    text_body = '\n\n'.join(body_lines + [
        '',
        'Results vary based on content quality, niche, audience interest, campaign settings, and viewer response. '
        'Our campaigns are designed to help creators reach relevant viewers, built to increase exposure and discovery, '
        'and promote content to targeted audiences without promising specific subscriber counts, watch-hour outcomes, '
        'monetization approval, or revenue.',
        '\n-- Creatorlift By The Accountant'
    ])
    if action_url:
        text_body = f"{text_body}\n\n{action_label}: {action_url}"

    result = send_creatorlift_email(
        recipient,
        subject,
        text_body,
        html_body=safe_email_html(subject, body_lines, action_url, action_label),
        tags=[
            {'name': 'campaign_event', 'value': event},
            {'name': 'campaign_id', 'value': str(campaign.get('id', ''))},
        ],
    )
    log = {
        **result,
        'event': event,
        'campaign_id': campaign.get('id'),
        'tracking_code': campaign.get('tracking_code'),
        'created_at': now_iso(),
    }
    db.setdefault('email_log', []).append(log)
    campaign.setdefault('email_activity', []).append(log)
    if not result.get('sent'):
        campaign.setdefault('email_warnings', []).append({
            'event': event,
            'error': result.get('error', 'Email not sent'),
            'created_at': log['created_at'],
        })
        print(f"Resend warning for campaign {campaign.get('id')} [{event}]: {result.get('error')}")
    return log


def campaign_email_copy(campaign, event, reason=''):
    track_url = tracking_url_for(campaign)
    plan_name = campaign.get('plan', 'Discovery Campaign')
    plan_info = PLANS.get(plan_name, PLANS['Discovery Campaign'])
    
    duration = plan_info.get('duration', '2 to 4 days')
    features = plan_info.get('features', [])
    features_list = ", ".join(features[:3]) + " (and more)" if len(features) > 3 else ", ".join(features)
    
    copies = {
        'campaign_submitted_for_review': {
            'subject': f'CreatorLift: {plan_name} received',
            'lines': [
                f"Your {plan_name} has been received and is pending payment or review.",
                f"Plan duration: {duration}.",
                f"Included benefits: {features_list}.",
                "Our team will review your submitted video and campaign details to help you reach relevant viewers, increase exposure, and promote content to targeted audiences.",
                f"Tracking link: {track_url}"
            ],
        },
        'payment_received': {
            'subject': f'Payment received - CreatorLift: {plan_name} review',
            'lines': [
                f"We received your payment for {plan_name}.",
                f"Plan duration: {duration}.",
                f"Included benefits: {features_list}.",
                "Your campaign is pending review. If eligible, our team will prepare the campaign setup to increase discovery and promote content to targeted audiences.",
                f"Tracking link: {track_url}"
            ],
        },
        'campaign_approved': {
            'subject': f'CreatorLift: {plan_name} approved for setup',
            'lines': [
                f"Your {plan_name} has been approved for setup.",
                f"Plan duration: {duration}.",
                f"Included benefits: {features_list}.",
                "Our team is setting up your campaign using compliant promotional methods designed to help you reach relevant viewers and increase exposure.",
                f"Tracking link: {track_url}"
            ],
        },
        'campaign_rejected': {
            'subject': f'CreatorLift: {plan_name} review update',
            'lines': [
                f"Your {plan_name} was not approved for launch after review.",
                f"Review note: {reason or campaign.get('reject_reason') or 'Campaign was not eligible for promotion.'}",
                "If payment was captured, the refund request will be reviewed based on campaign status.",
                f"Tracking link: {track_url}"
            ],
        },
        'campaign_active': {
            'subject': f'CreatorLift: {plan_name} is active',
            'lines': [
                f"Your {plan_name} is now active.",
                f"Plan duration: {duration}.",
                f"Included benefits: {features_list}.",
                "Your promotion is live! We are actively targeting relevant audiences to increase discovery and exposure for your video.",
                f"Tracking link: {track_url}"
            ],
        },
        'campaign_completed': {
            'subject': f'CreatorLift: {plan_name} completed',
            'lines': [
                f"Your {plan_name} has been completed.",
                f"Plan duration: {duration}.",
                "We hope this campaign helped increase discovery and reach targeted audiences for your video. Thank you for partnering with us!",
                f"Tracking link: {track_url}"
            ],
        },
    }
    copy = copies.get(event, {
        'subject': 'CreatorLift Campaign Update',
        'lines': [
            f"Update for your {plan_name}.",
            f"Tracking link: {track_url}"
        ]
    })
    return copy['subject'], copy['lines'], track_url


def send_campaign_email(db, campaign, event, reason=''):
    subject, lines, track_url = campaign_email_copy(campaign, event, reason)
    return send_email_event(db, campaign, event, campaign.get('email'), subject, lines, track_url)


def send_admin_new_campaign_email(db, campaign):
    admin_email = os.environ.get('ADMIN_EMAIL', '')
    admin_url = f"{app_base_url()}/admin.html"
    lines = [
        "A new CreatorLift campaign has been paid and is pending review.",
        f"Customer: {campaign.get('email')}",
        f"Plan: {campaign.get('plan')}",
        f"Video URL: {campaign.get('video_url')}",
        "Review the campaign in the admin dashboard before approving setup or curation.",
    ]
    return send_email_event(
        db,
        campaign,
        'admin_new_campaign',
        admin_email,
        'New CreatorLift campaign pending review',
        lines,
        admin_url,
        'Open Admin',
    )


def sync_legacy_orders(db):
    orders = []
    for campaign in db.get('campaigns', []):
        orders.append({
            'id': campaign.get('id'),
            'email': campaign.get('email'),
            'video_url': campaign.get('video_url'),
            'plan': campaign.get('plan'),
            'status': campaign.get('status'),
            'reference': campaign.get('paystack_reference'),
            'amount': campaign.get('amount_paid', 0),
            'views_before': campaign.get('views_before', 0),
            'promotion_duration_days': campaign.get('promotion_duration_days'),
            'promotion_started_at': campaign.get('promotion_started_at'),
            'promotion_ends_at': campaign.get('promotion_ends_at'),
        })
    db['orders'] = orders


def calculate_admin_stats(db):
    campaigns = db.get('campaigns', [])
    paid_campaigns = [c for c in campaigns if c.get('status') != 'pending_payment']
    revenue = sum(float(c.get('amount_paid') or 0) for c in paid_campaigns)
    db.setdefault('stats', {})['revenue'] = revenue
    return {
        'revenue': revenue,
        'total_campaigns': len(campaigns),
        'pending_review': len([c for c in campaigns if c.get('status') == 'paid_pending_review']),
        'active_campaigns': len([c for c in campaigns if c.get('status') == 'campaign_active']),
        'completed_campaigns': len([c for c in campaigns if c.get('status') == 'campaign_completed']),
        'curation_approved': len([c for c in campaigns if c.get('curation_approved')]),
    }


def create_campaign(data):
    email = (data.get('email') or '').strip()
    video_url = (data.get('video_url') or '').strip()
    plan = normalize_plan(data.get('plan') or 'Starter Campaign')
    video_id = extract_youtube_video_id(video_url)

    if not email or '@' not in email:
        return None, 'A valid billing email is required'
    if not video_id:
        return None, 'Enter a valid YouTube video, Shorts, live, or embed URL'

    created_at = now_iso()
    plan_info = PLANS.get(plan, PLANS['Discovery Campaign'])
    campaign = {
        'id': None,
        'tracking_code': make_tracking_code(),
        'created_at': created_at,
        'updated_at': created_at,
        'email': email,
        'video_url': video_url,
        'video_id': video_id,
        'thumbnail': youtube_thumbnail(video_id),
        'video_title': data.get('video_title') or f'YouTube Video {video_id}',
        'plan': plan,
        'amount_expected': plan_amount(plan),
        'amount_paid': 0,
        'currency': 'NGN',
        'status': 'pending_payment',
        'paystack_reference': '',
        'payment_verified_at': None,
        'views_before': int(data.get('views_before') or 0),
        'promotion_duration_days': int(data.get('promotion_duration_days') or plan_duration_days(plan)),
        'promotion_started_at': None,
        'promotion_ends_at': None,
        'admin_notes': '',
        'customer_updates': [],
        'curation_approved': False,
        'curation_category': '',
        'curation_approved_at': None,
        'reject_reason': '',
        'refund_status': '',
        'paystack_data': {},
        'email_activity': [],
        'email_warnings': [],
        'plan_name': plan,
        'plan_price': plan_info['price'],
        'plan_badge': plan_info['badge'],
        'plan_description': plan_info['description'],
        'plan_features': plan_info['features'],
        'campaign_duration': plan_info['duration'],
        'support_level': plan_info['support_level'],
        'curation_access_type': plan_info['curation_access_type'],
    }
    return campaign, ''


def update_campaign_status(db, campaign, status, reason=''):
    if status not in CAMPAIGN_STATUSES:
        return False, 'Invalid campaign status'

    previous_status = campaign.get('status')
    campaign['status'] = status
    campaign['updated_at'] = now_iso()

    if status == 'rejected_refunded':
        campaign['reject_reason'] = reason or campaign.get('reject_reason') or 'Campaign was not eligible for promotion.'
        campaign['refund_status'] = 'refund_review_required'
        campaign['curation_approved'] = False
    elif status == 'campaign_active' and not campaign.get('promotion_started_at'):
        started_at = datetime.now(timezone.utc)
        duration_days = int(campaign.get('promotion_duration_days') or plan_duration_days(campaign.get('plan')))
        campaign['promotion_started_at'] = started_at.isoformat(timespec='seconds')
        campaign['promotion_ends_at'] = (started_at + timedelta(days=duration_days)).isoformat(timespec='seconds')

    if previous_status != status:
        event_map = {
            'approved_for_setup': 'campaign_approved',
            'rejected_refunded': 'campaign_rejected',
            'campaign_active': 'campaign_active',
            'campaign_completed': 'campaign_completed',
        }
        event = event_map.get(status)
        if event:
            send_campaign_email(db, campaign, event, reason)

    return True, ''


@app.route('/')
def index_page():
    return send_from_directory('.', 'index.html')


@app.route('/watch')
@app.route('/watch.html')
def watch_page():
    return send_from_directory('.', 'watch.html')


@app.route('/track/<tracking_code>')
def tracking_page(tracking_code):
    return send_from_directory('.', 'track.html')


@app.route('/track.html')
def tracking_file():
    return send_from_directory('.', 'track.html')


@app.route('/dashboard')
@app.route('/dashboard.html')
def dashboard_page():
    return send_from_directory('.', 'dashboard.html')


@app.route('/admin')
@app.route('/admin.html')
def admin_page():
    return send_from_directory('.', 'admin.html')


@app.route('/terms')
def terms_page():
    return send_from_directory('.', 'terms.html')


@app.route('/privacy')
def privacy_page():
    return send_from_directory('.', 'privacy.html')


@app.route('/refund')
def refund_page():
    return send_from_directory('.', 'refund.html')


@app.route('/contact')
def contact_page():
    return send_from_directory('.', 'contact.html')


@app.route('/campaigns', methods=['POST'])
@app.route('/api/campaigns', methods=['POST'])
def submit_campaign():
    data = request.json or {}
    campaign, error = create_campaign(data)
    if error:
        return jsonify({'success': False, 'message': error}), 400

    db = load_db()
    campaign['id'] = next_campaign_id(db)
    db.setdefault('campaigns', []).append(campaign)
    send_campaign_email(db, campaign, 'campaign_submitted_for_review')
    sync_legacy_orders(db)
    save_db(db)

    return jsonify({
        'success': True,
        'campaign': public_campaign(campaign),
        'campaign_id': campaign['id'],
        'tracking_code': campaign['tracking_code'],
        'email_activity': campaign.get('email_activity', []),
    })


@app.route('/order', methods=['POST'])
@app.route('/api/order', methods=['POST'])
def place_order():
    data = request.json or {}
    reference = data.get('reference')
    tracking_code = data.get('tracking_code')
    campaign_id = data.get('campaign_id')

    db = load_db()
    campaign = None
    if campaign_id:
        campaign = find_campaign(db, campaign_id)
    if not campaign and tracking_code:
        campaign = find_campaign_by_tracking(db, tracking_code)
    if not campaign:
        campaign = find_campaign_by_reference(db, reference)
    if not campaign:
        campaign, error = create_campaign(data)
        if error:
            return jsonify({'success': False, 'message': error}), 400
        campaign['id'] = next_campaign_id(db)
        db.setdefault('campaigns', []).append(campaign)

    try:
        verified, message, paystack_payload = verify_paystack_reference(reference)
    except Exception as exc:
        return jsonify({'success': False, 'message': f'Payment verification error: {exc}'}), 500

    if not verified:
        campaign['paystack_reference'] = reference or campaign.get('paystack_reference', '')
        campaign['paystack_data'] = paystack_payload
        campaign['updated_at'] = now_iso()
        sync_legacy_orders(db)
        save_db(db)
        return jsonify({'success': False, 'message': message}), 400

    paystack_data = paystack_payload.get('data', {})
    amount_paid = float(paystack_data.get('amount', 0)) / 100
    if amount_paid < float(campaign.get('amount_expected', 0)):
        campaign['paystack_reference'] = reference
        campaign['paystack_data'] = paystack_data
        campaign['updated_at'] = now_iso()
        sync_legacy_orders(db)
        save_db(db)
        return jsonify({'success': False, 'message': 'Verified payment amount is lower than the selected plan amount'}), 400

    campaign['amount_paid'] = amount_paid
    campaign['paystack_reference'] = reference
    campaign['payment_verified_at'] = now_iso()
    campaign['paystack_data'] = {
        'id': paystack_data.get('id'),
        'status': paystack_data.get('status'),
        'channel': paystack_data.get('channel'),
        'paid_at': paystack_data.get('paid_at'),
    }
    campaign['status'] = 'paid_pending_review'
    campaign['updated_at'] = now_iso()

    tracking_url = tracking_url_for(campaign)
    send_campaign_email(db, campaign, 'payment_received')
    send_admin_new_campaign_email(db, campaign)

    calculate_admin_stats(db)
    sync_legacy_orders(db)
    save_db(db)

    return jsonify({
        'success': True,
        'campaign': public_campaign(campaign),
        'tracking_url': tracking_url,
        'email_activity': campaign.get('email_activity', []),
    })


@app.route('/campaigns/track/<tracking_code>')
@app.route('/api/campaigns/track/<tracking_code>')
def track_campaign(tracking_code):
    db = load_db()
    campaign = find_campaign_by_tracking(db, tracking_code)
    if not campaign:
        return jsonify({'success': False, 'message': 'Campaign not found'}), 404
    return jsonify({'success': True, 'campaign': public_campaign(campaign)})


@app.route('/plans')
@app.route('/api/plans')
def get_plans():
    return jsonify({
        'success': True,
        'plans': [
            {
                'name': name,
                'amount': info['price'],
                'duration_days': info['duration_days'],
                'badge': info['badge'],
                'description': info['description'],
                'duration': info['duration'],
                'support_level': info['support_level'],
                'curation_access_type': info['curation_access_type'],
                'features': info['features']
            }
            for name, info in PLANS.items()
        ],
    })


@app.route('/customer/campaigns')
@app.route('/api/customer/campaigns')
def get_customer_campaigns():
    email = (request.args.get('email') or '').strip().lower()
    if not email or '@' not in email:
        return jsonify({'success': False, 'message': 'Enter the email used for your campaign.'}), 400

    db = load_db()
    campaigns = [
        public_campaign(c)
        for c in db.get('campaigns', [])
        if (c.get('email') or '').strip().lower() == email
    ]
    campaigns.sort(key=lambda c: c.get('created_at') or '', reverse=True)
    return jsonify({
        'success': True,
        'email': email,
        'campaigns': campaigns,
        'plans': [
            {
                'name': name,
                'amount': amount,
                'duration_days': plan_duration_days(name),
            }
            for name, amount in PLAN_AMOUNTS.items()
        ],
    })


@app.route('/curation')
@app.route('/api/curation')
def get_curation_campaigns():
    db = load_db()
    campaigns = [
        public_campaign(c)
        for c in db.get('campaigns', [])
        if c.get('curation_approved') and c.get('status') in ['campaign_active', 'campaign_completed']
    ]
    campaigns.sort(key=lambda c: c.get('updated_at') or '', reverse=True)
    return jsonify({'success': True, 'campaigns': campaigns})


@app.route('/stats')
@app.route('/api/stats')
def get_public_stats():
    db = load_db()
    stats = calculate_admin_stats(db)
    return jsonify({
        'creators': len(set(c.get('email') for c in db.get('campaigns', []) if c.get('email'))),
        'views': 0,
        'satisfaction': None,
        'hours': 0,
        'active_campaigns': stats['active_campaigns'],
        'curation_approved': stats['curation_approved'],
    })


@app.route('/admin/login', methods=['POST'])
@app.route('/api/admin/login', methods=['POST'])
def login():
    if not ADMIN_PASSWORD:
        return jsonify({
            'success': False,
            'message': 'Set CREATORLIFT_ADMIN_PASSWORD or ADMIN_PASSWORD before using admin login.',
        }), 500

    if (request.json or {}).get('password') == ADMIN_PASSWORD:
        session['logged_in'] = True
        return jsonify({'success': True})
    return jsonify({'success': False, 'message': 'Invalid password'}), 401


@app.route('/admin/data')
@app.route('/api/admin/data')
@admin_required
def get_admin_data():
    db = load_db()
    stats = calculate_admin_stats(db)
    sync_legacy_orders(db)
    save_db(db)
    return jsonify({
        'stats': {**db.get('stats', {}), **stats},
        'campaigns': [admin_campaign(c) for c in db.get('campaigns', [])],
        'orders': db.get('orders', []),
        'active_target': db.get('active_target', 'None'),
        'statuses': CAMPAIGN_STATUSES,
        'resend_config': resend_config_status(),
        'supabase_config': supabase_config_status(),
    })


@app.route('/admin/campaigns')
@app.route('/api/admin/campaigns')
@admin_required
def list_admin_campaigns():
    db = load_db()
    status = request.args.get('status', '')
    query = (request.args.get('q', '') or '').lower()
    campaigns = db.get('campaigns', [])
    if status:
        campaigns = [c for c in campaigns if c.get('status') == status]
    if query:
        campaigns = [
            c for c in campaigns
            if query in (c.get('email', '') + ' ' + c.get('video_url', '') + ' ' + c.get('plan', '') + ' ' + c.get('paystack_reference', '')).lower()
        ]
    campaigns.sort(key=lambda c: c.get('created_at') or '', reverse=True)
    stats = calculate_admin_stats(db)
    return jsonify({
        'success': True,
        'campaigns': [admin_campaign(c) for c in campaigns],
        'stats': stats,
        'statuses': CAMPAIGN_STATUSES,
        'resend_config': resend_config_status(),
        'supabase_config': supabase_config_status(),
    })


@app.route('/admin/campaigns/<int:campaign_id>')
@app.route('/api/admin/campaigns/<int:campaign_id>')
@admin_required
def get_admin_campaign(campaign_id):
    db = load_db()
    campaign = find_campaign(db, campaign_id)
    if not campaign:
        return jsonify({'success': False, 'message': 'Campaign not found'}), 404
    return jsonify({'success': True, 'campaign': admin_campaign(campaign)})


@app.route('/admin/test-email', methods=['POST'])
@app.route('/api/admin/test-email', methods=['POST'])
@admin_required
def send_test_email():
    data = request.json or {}
    recipient = (data.get('email') or os.environ.get('ADMIN_EMAIL', '')).strip()
    if not recipient:
        return jsonify({'success': False, 'message': 'Enter a test recipient email or set ADMIN_EMAIL.'}), 400

    subject = 'CreatorLift Resend test'
    lines = [
        'This is a test email from CreatorLift.',
        'If this arrived, your RESEND_API_KEY and RESEND_FROM_EMAIL are working.',
        f"App URL: {app_base_url()}",
    ]
    result = send_creatorlift_email(
        recipient,
        subject,
        '\n\n'.join(lines),
        html_body=safe_email_html(subject, lines, app_base_url(), 'Open CreatorLift'),
        tags=[{'name': 'event', 'value': 'admin_test_email'}],
    )
    return jsonify({
        'success': result.get('sent', False),
        'email_result': result,
        'resend_config': resend_config_status(),
        'message': 'Test email sent.' if result.get('sent') else result.get('error', 'Test email was not sent.'),
    }), 200 if result.get('sent') else 400


@app.route('/admin/campaigns/<int:campaign_id>/verify-payment', methods=['POST'])
@app.route('/api/admin/campaigns/<int:campaign_id>/verify-payment', methods=['POST'])
@admin_required
def admin_verify_payment(campaign_id):
    db = load_db()
    campaign = find_campaign(db, campaign_id)
    if not campaign:
        return jsonify({'success': False, 'message': 'Campaign not found'}), 404
    reference = (request.json or {}).get('reference') or campaign.get('paystack_reference')
    verified, message, payload = verify_paystack_reference(reference)
    if not verified:
        return jsonify({'success': False, 'message': message}), 400
    paystack_data = payload.get('data', {})
    campaign['amount_paid'] = float(paystack_data.get('amount', 0)) / 100
    campaign['paystack_reference'] = reference
    campaign['payment_verified_at'] = now_iso()
    campaign['status'] = 'paid_pending_review'
    campaign['updated_at'] = now_iso()
    campaign['paystack_data'] = {
        'id': paystack_data.get('id'),
        'status': paystack_data.get('status'),
        'channel': paystack_data.get('channel'),
        'paid_at': paystack_data.get('paid_at'),
    }
    send_campaign_email(db, campaign, 'payment_received')
    send_admin_new_campaign_email(db, campaign)
    sync_legacy_orders(db)
    save_db(db)
    return jsonify({'success': True, 'campaign': admin_campaign(campaign)})


@app.route('/admin/campaigns/<int:campaign_id>/status', methods=['POST'])
@app.route('/api/admin/campaigns/<int:campaign_id>/status', methods=['POST'])
@admin_required
def set_campaign_status(campaign_id):
    db = load_db()
    campaign = find_campaign(db, campaign_id)
    if not campaign:
        return jsonify({'success': False, 'message': 'Campaign not found'}), 404

    data = request.json or {}
    ok, error = update_campaign_status(db, campaign, data.get('status'), data.get('reason', ''))
    if not ok:
        return jsonify({'success': False, 'message': error}), 400

    calculate_admin_stats(db)
    sync_legacy_orders(db)
    save_db(db)
    return jsonify({'success': True, 'campaign': admin_campaign(campaign)})


@app.route('/admin/campaigns/<int:campaign_id>/notes', methods=['POST'])
@app.route('/api/admin/campaigns/<int:campaign_id>/notes', methods=['POST'])
@admin_required
def save_admin_notes(campaign_id):
    db = load_db()
    campaign = find_campaign(db, campaign_id)
    if not campaign:
        return jsonify({'success': False, 'message': 'Campaign not found'}), 404
    campaign['admin_notes'] = (request.json or {}).get('admin_notes', '')
    campaign['updated_at'] = now_iso()
    save_db(db)
    return jsonify({'success': True, 'campaign': admin_campaign(campaign)})


@app.route('/admin/campaigns/<int:campaign_id>/updates', methods=['POST'])
@app.route('/api/admin/campaigns/<int:campaign_id>/updates', methods=['POST'])
@admin_required
def add_customer_update(campaign_id):
    db = load_db()
    campaign = find_campaign(db, campaign_id)
    if not campaign:
        return jsonify({'success': False, 'message': 'Campaign not found'}), 404

    data = request.json or {}
    message = (data.get('message') or '').strip()
    if not message:
        return jsonify({'success': False, 'message': 'Update message is required'}), 400

    update = {'message': message, 'created_at': now_iso()}
    campaign.setdefault('customer_updates', []).append(update)
    campaign['updated_at'] = now_iso()
    if data.get('send_email', True):
        tracking_url = tracking_url_for(campaign)
        send_email_event(
            db,
            campaign,
            'customer_update',
            campaign.get('email'),
            'CreatorLift campaign update',
            [
                message,
                "You can view this update and your campaign status on your tracking page.",
            ],
            tracking_url,
        )
    save_db(db)
    return jsonify({'success': True, 'campaign': admin_campaign(campaign)})


@app.route('/admin/campaigns/<int:campaign_id>/resend-email', methods=['POST'])
@app.route('/api/admin/campaigns/<int:campaign_id>/resend-email', methods=['POST'])
@admin_required
def resend_update_email(campaign_id):
    db = load_db()
    campaign = find_campaign(db, campaign_id)
    if not campaign:
        return jsonify({'success': False, 'message': 'Campaign not found'}), 404

    data = request.json or {}
    message = (data.get('message') or '').strip()
    if not message:
        updates = campaign.get('customer_updates', [])
        if updates:
            message = updates[-1].get('message', '')
    if not message:
        return jsonify({'success': False, 'message': 'Write a customer update before resending email.'}), 400

    result = send_email_event(
        db,
        campaign,
        'manual_update_resend',
        campaign.get('email'),
        'CreatorLift campaign update',
        [
            message,
            "This is a resent campaign update from the CreatorLift team.",
        ],
        tracking_url_for(campaign),
    )
    campaign['updated_at'] = now_iso()
    save_db(db)
    return jsonify({
        'success': True,
        'campaign': admin_campaign(campaign),
        'email_result': result,
        'warning': '' if result.get('sent') else result.get('error', 'Resend email was not sent.'),
    })


@app.route('/admin/campaigns/<int:campaign_id>/curation', methods=['POST'])
@app.route('/api/admin/campaigns/<int:campaign_id>/curation', methods=['POST'])
@admin_required
def update_curation(campaign_id):
    db = load_db()
    campaign = find_campaign(db, campaign_id)
    if not campaign:
        return jsonify({'success': False, 'message': 'Campaign not found'}), 404

    data = request.json or {}
    approved = bool(data.get('approved'))
    campaign['curation_approved'] = approved
    campaign['curation_category'] = (data.get('category') or campaign.get('curation_category') or '').strip()
    campaign['curation_approved_at'] = now_iso() if approved else None
    campaign['updated_at'] = now_iso()
    save_db(db)
    return jsonify({'success': True, 'campaign': admin_campaign(campaign)})


@app.route('/admin/update-stats', methods=['POST'])
@app.route('/api/admin/update-stats', methods=['POST'])
@admin_required
def update_stats():
    data = request.json or {}
    db = load_db()
    if 'hours' in data:
        db.setdefault('stats', {})['hours'] = int(data['hours'])
        db['stats']['manual_metric'] = int(data['hours'])
    if 'manual_metric' in data:
        db.setdefault('stats', {})['manual_metric'] = int(data['manual_metric'])
    save_db(db)
    return jsonify({'success': True})


@app.route('/admin/activate', methods=['POST'])
@app.route('/api/admin/activate', methods=['POST'])
@admin_required
def activate_order():
    db = load_db()
    campaign = find_campaign(db, (request.json or {}).get('id'))
    if not campaign:
        return jsonify({'success': False, 'message': 'Campaign not found'}), 404
    ok, error = update_campaign_status(db, campaign, 'campaign_active')
    if not ok:
        return jsonify({'success': False, 'message': error}), 400
    sync_legacy_orders(db)
    save_db(db)
    return jsonify({'success': True, 'campaign': admin_campaign(campaign)})


@app.route('/admin/delete-order', methods=['POST'])
@app.route('/api/admin/delete-order', methods=['POST'])
@admin_required
def delete_order():
    db = load_db()
    campaign_id = (request.json or {}).get('id')
    db['campaigns'] = [c for c in db.get('campaigns', []) if int(c.get('id')) != int(campaign_id)]
    sync_legacy_orders(db)
    save_db(db)
    return jsonify({'success': True})


@app.route('/admin/update-target', methods=['POST'])
@app.route('/api/admin/update-target', methods=['POST'])
@admin_required
def update_target():
    db = load_db()
    db['active_target'] = (request.json or {}).get('handle') or 'None'
    save_db(db)
    return jsonify({'success': True})


@app.route('/admin/reset-network', methods=['POST'])
@app.route('/api/admin/reset-network', methods=['POST'])
@admin_required
def reset_network():
    db = load_db()
    for campaign in db.get('campaigns', []):
        campaign['curation_approved'] = False
        campaign['curation_approved_at'] = None
    db['active_target'] = 'None'
    save_db(db)
    return jsonify({'success': True})


@app.route('/<path:path>')
def send_static(path):
    return send_from_directory('.', path)


if __name__ == '__main__':
    app.run(
        host=os.environ.get('HOST', '127.0.0.1'),
        port=int(os.environ.get('PORT', '5000')),
        debug=True,
    )
