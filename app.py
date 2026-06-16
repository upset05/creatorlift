from datetime import datetime, timezone
from email.message import EmailMessage
from functools import wraps
from flask import Flask, request, jsonify, send_from_directory, session
from flask_cors import CORS
import json
import os
import re
import smtplib
import uuid
import requests

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

PLAN_AMOUNTS = {
    'Starter Campaign': 15000,
    'Growth Accelerator': 45000,
    'Agency Partnership': 85000,
}


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def default_db():
    return {
        'campaigns': [],
        'orders': [],
        'active_target': 'None',
        'stats': {'revenue': 0, 'manual_metric': 0, 'hours': 0},
        'email_log': [],
    }


def load_db():
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

    next_id = 1
    for campaign in data.get('campaigns', []):
        changed = ensure_campaign_shape(campaign, next_id) or changed
        next_id = max(next_id, int(campaign.get('id', 0)) + 1)

    return changed


def campaign_from_legacy_order(order, fallback_id):
    video_id = extract_youtube_video_id(order.get('video_url', ''))
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
        'plan': normalize_plan(order.get('plan', 'Starter Campaign')),
        'amount_expected': plan_amount(normalize_plan(order.get('plan', 'Starter Campaign'))),
        'amount_paid': order.get('amount', 0),
        'currency': 'NGN',
        'status': status_map.get(order.get('status'), 'paid_pending_review'),
        'paystack_reference': order.get('reference', ''),
        'payment_verified_at': order.get('payment_verified_at'),
        'admin_notes': order.get('admin_notes', ''),
        'customer_updates': order.get('customer_updates', []),
        'curation_approved': order.get('curation_approved', False),
        'curation_category': order.get('curation_category', ''),
        'curation_approved_at': order.get('curation_approved_at'),
        'reject_reason': order.get('reject_reason', ''),
        'refund_status': order.get('refund_status', ''),
        'paystack_data': order.get('paystack_data', {}),
    }


def ensure_campaign_shape(campaign, fallback_id):
    changed = False
    video_id = extract_youtube_video_id(campaign.get('video_url', '')) or campaign.get('video_id', '')
    plan = normalize_plan(campaign.get('plan', 'Starter Campaign'))
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
        'admin_notes': '',
        'customer_updates': [],
        'curation_approved': False,
        'curation_category': '',
        'curation_approved_at': None,
        'reject_reason': '',
        'refund_status': '',
        'paystack_data': {},
    }
    for key, value in defaults.items():
        if key not in campaign:
            campaign[key] = value
            changed = True
    if campaign.get('status') not in CAMPAIGN_STATUSES:
        campaign['status'] = 'paid_pending_review' if campaign.get('amount_paid') else 'pending_payment'
        changed = True
    if campaign.get('plan') != plan:
        campaign['plan'] = plan
        changed = True
    if video_id and campaign.get('video_id') != video_id:
        campaign['video_id'] = video_id
        campaign['thumbnail'] = youtube_thumbnail(video_id)
        changed = True
    return changed


def normalize_plan(plan):
    if plan in PLAN_AMOUNTS:
        return plan
    if '45' in plan or 'Growth' in plan:
        return 'Growth Accelerator'
    if '85' in plan or 'Agency' in plan:
        return 'Agency Partnership'
    return 'Starter Campaign'


def plan_amount(plan):
    return PLAN_AMOUNTS.get(plan, PLAN_AMOUNTS['Starter Campaign'])


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
        'tracking_code': campaign.get('tracking_code'),
        'created_at': campaign.get('created_at'),
        'updated_at': campaign.get('updated_at'),
        'video_url': campaign.get('video_url'),
        'video_id': campaign.get('video_id'),
        'thumbnail': campaign.get('thumbnail'),
        'video_title': campaign.get('video_title'),
        'plan': campaign.get('plan'),
        'amount_paid': campaign.get('amount_paid'),
        'currency': campaign.get('currency', 'NGN'),
        'status': campaign.get('status'),
        'customer_updates': campaign.get('customer_updates', []),
        'curation_approved': campaign.get('curation_approved', False),
        'curation_category': campaign.get('curation_category', ''),
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


def send_notification(email, subject, body):
    result = {
        'to': email,
        'subject': subject,
        'body': body,
        'created_at': now_iso(),
        'sent': False,
        'error': '',
    }

    smtp_host = os.environ.get('SMTP_HOST')
    smtp_from = os.environ.get('SMTP_FROM') or os.environ.get('SMTP_USER')
    if smtp_host and smtp_from and email:
        try:
            message = EmailMessage()
            message['From'] = smtp_from
            message['To'] = email
            message['Subject'] = subject
            message.set_content(body)

            smtp_port = int(os.environ.get('SMTP_PORT', '587'))
            with smtplib.SMTP(smtp_host, smtp_port, timeout=20) as smtp:
                if os.environ.get('SMTP_TLS', 'true').lower() != 'false':
                    smtp.starttls()
                smtp_user = os.environ.get('SMTP_USER')
                smtp_password = os.environ.get('SMTP_PASSWORD')
                if smtp_user and smtp_password:
                    smtp.login(smtp_user, smtp_password)
                smtp.send_message(message)
            result['sent'] = True
        except Exception as exc:
            result['error'] = str(exc)

    print('--- EMAIL NOTIFICATION ---')
    print(f"To: {email}")
    print(f"Subject: {subject}")
    print(f"Body: {body}")
    if result['error']:
        print(f"Email Error: {result['error']}")
    print('--------------------------')
    return result


def add_email_log(db, email, subject, body):
    log = send_notification(email, subject, body)
    db.setdefault('email_log', []).append(log)
    return log


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
        'admin_notes': '',
        'customer_updates': [],
        'curation_approved': False,
        'curation_category': '',
        'curation_approved_at': None,
        'reject_reason': '',
        'refund_status': '',
        'paystack_data': {},
    }
    return campaign, ''


def update_campaign_status(db, campaign, status, reason=''):
    if status not in CAMPAIGN_STATUSES:
        return False, 'Invalid campaign status'

    previous_status = campaign.get('status')
    campaign['status'] = status
    campaign['updated_at'] = now_iso()

    tracking_url = f"{request.host_url.rstrip('/')}/track/{campaign.get('tracking_code')}"
    email = campaign.get('email')
    subject = None
    body = None

    if status == 'approved_for_setup':
        subject = 'CreatorLift campaign approved for setup'
        body = (
            "Your campaign has been reviewed and approved for setup. "
            f"You can track updates here: {tracking_url}"
        )
    elif status == 'rejected_refunded':
        campaign['reject_reason'] = reason or campaign.get('reject_reason') or 'Campaign was not eligible for promotion.'
        campaign['refund_status'] = 'refund_review_required'
        campaign['curation_approved'] = False
        subject = 'CreatorLift campaign review update'
        body = (
            "Your campaign was not approved for launch after review. "
            "If payment was captured, the refund request will be reviewed based on campaign status. "
            f"Reason: {campaign['reject_reason']}"
        )
    elif status == 'campaign_active':
        subject = 'CreatorLift campaign is active'
        body = (
            "Your campaign has been marked active. Monitor performance in YouTube Studio and follow updates here: "
            f"{tracking_url}"
        )
    elif status == 'campaign_completed':
        subject = 'CreatorLift campaign completed'
        body = (
            "Your campaign has been marked completed. Results may vary based on content quality, niche, "
            "audience interest, campaign settings, and YouTube systems."
        )

    if subject and body and previous_status != status:
        add_email_log(db, email, subject, body)

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


@app.route('/api/campaigns', methods=['POST'])
def submit_campaign():
    data = request.json or {}
    campaign, error = create_campaign(data)
    if error:
        return jsonify({'success': False, 'message': error}), 400

    db = load_db()
    campaign['id'] = next_campaign_id(db)
    db.setdefault('campaigns', []).append(campaign)
    sync_legacy_orders(db)
    save_db(db)

    return jsonify({
        'success': True,
        'campaign': public_campaign(campaign),
        'campaign_id': campaign['id'],
        'tracking_code': campaign['tracking_code'],
    })


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

    tracking_url = f"{request.host_url.rstrip('/')}/track/{campaign.get('tracking_code')}"
    add_email_log(
        db,
        campaign.get('email'),
        'Payment received - CreatorLift campaign review',
        (
            f"We received your payment for {campaign.get('plan')}. "
            "Our team will review your video and campaign details before setup. "
            f"Track your campaign here: {tracking_url}"
        ),
    )

    calculate_admin_stats(db)
    sync_legacy_orders(db)
    save_db(db)

    return jsonify({
        'success': True,
        'campaign': public_campaign(campaign),
        'tracking_url': tracking_url,
    })


@app.route('/api/campaigns/track/<tracking_code>')
def track_campaign(tracking_code):
    db = load_db()
    campaign = find_campaign_by_tracking(db, tracking_code)
    if not campaign:
        return jsonify({'success': False, 'message': 'Campaign not found'}), 404
    return jsonify({'success': True, 'campaign': public_campaign(campaign)})


@app.route('/api/curation')
def get_curation_campaigns():
    db = load_db()
    campaigns = [
        public_campaign(c)
        for c in db.get('campaigns', [])
        if c.get('curation_approved') and c.get('status') not in ['pending_payment', 'rejected_refunded']
    ]
    campaigns.sort(key=lambda c: c.get('updated_at') or '', reverse=True)
    return jsonify({'success': True, 'campaigns': campaigns})


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
    })


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
    })


@app.route('/api/admin/campaigns/<int:campaign_id>')
@admin_required
def get_admin_campaign(campaign_id):
    db = load_db()
    campaign = find_campaign(db, campaign_id)
    if not campaign:
        return jsonify({'success': False, 'message': 'Campaign not found'}), 404
    return jsonify({'success': True, 'campaign': admin_campaign(campaign)})


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
    sync_legacy_orders(db)
    save_db(db)
    return jsonify({'success': True, 'campaign': admin_campaign(campaign)})


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
        tracking_url = f"{request.host_url.rstrip('/')}/track/{campaign.get('tracking_code')}"
        add_email_log(
            db,
            campaign.get('email'),
            'CreatorLift campaign update',
            f"{message}\n\nTrack your campaign here: {tracking_url}",
        )
    save_db(db)
    return jsonify({'success': True, 'campaign': admin_campaign(campaign)})


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


@app.route('/api/admin/delete-order', methods=['POST'])
@admin_required
def delete_order():
    db = load_db()
    campaign_id = (request.json or {}).get('id')
    db['campaigns'] = [c for c in db.get('campaigns', []) if int(c.get('id')) != int(campaign_id)]
    sync_legacy_orders(db)
    save_db(db)
    return jsonify({'success': True})


@app.route('/api/admin/update-target', methods=['POST'])
@admin_required
def update_target():
    db = load_db()
    db['active_target'] = (request.json or {}).get('handle') or 'None'
    save_db(db)
    return jsonify({'success': True})


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
