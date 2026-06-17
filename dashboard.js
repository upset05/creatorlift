const API_BASE = '/api';
const PAYSTACK_PUBLIC_KEY = 'pk_live_7f3162d6e8ef7df846b5420af9f8084a9c7be2e1';

const state = {
    email: localStorage.getItem('creatorlift_email') || '',
    plans: [],
    campaigns: []
};

const elements = {
    emailForm: document.getElementById('emailLookupForm'),
    emailInput: document.getElementById('dashboardEmail'),
    paymentForm: document.getElementById('dashboardPaymentForm'),
    planSelect: document.getElementById('dashPlanSelect'),
    videoUrl: document.getElementById('dashVideoUrl'),
    viewsBefore: document.getElementById('dashViewsBefore'),
    totalDue: document.getElementById('dashTotalDue'),
    notice: document.getElementById('dashboardNotice'),
    list: document.getElementById('campaignList'),
    subtitle: document.getElementById('dashboardSubtitle'),
    totalCampaigns: document.getElementById('totalCampaigns'),
    activeCampaigns: document.getElementById('activeCampaigns'),
    pendingCampaigns: document.getElementById('pendingCampaigns'),
    refresh: document.getElementById('refreshDashboard')
};

function escapeHtml(value) {
    return String(value || '').replace(/[&<>"']/g, (char) => ({
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        '"': '&quot;',
        "'": '&#039;'
    }[char]));
}

function formatMoney(amount) {
    return `NGN ${Number(amount || 0).toLocaleString()}`;
}

function statusLabel(status) {
    return String(status || '').replace(/_/g, ' ').replace(/\b\w/g, (char) => char.toUpperCase());
}

function selectedPlan() {
    return state.plans.find((plan) => plan.name === elements.planSelect.value) || state.plans[0];
}

function updateTotalDue() {
    const plan = selectedPlan();
    elements.totalDue.textContent = formatMoney(plan?.amount || 0);
}

function showNotice(message, tone = 'info') {
    elements.notice.textContent = message;
    elements.notice.style.display = message ? 'block' : 'none';
    elements.notice.style.borderColor = tone === 'error' ? 'rgba(239, 68, 68, 0.45)' : 'rgba(139, 92, 246, 0.3)';
    elements.notice.style.color = tone === 'error' ? '#fecaca' : '#ddd6fe';
}

function countdownText(campaign) {
    if (campaign.status !== 'campaign_active') {
        return campaign.promotion_ends_at ? 'Campaign timeline saved' : 'Starts when active';
    }
    if (!campaign.promotion_ends_at) return 'End date pending';

    const end = new Date(campaign.promotion_ends_at).getTime();
    const diff = end - Date.now();
    if (Number.isNaN(end)) return 'End date pending';
    if (diff <= 0) return 'Promotion window ended';

    const days = Math.floor(diff / 86400000);
    const hours = Math.floor((diff % 86400000) / 3600000);
    const minutes = Math.floor((diff % 3600000) / 60000);
    return `${days}d ${hours}h ${minutes}m left`;
}

function latestUpdate(campaign) {
    const updates = campaign.customer_updates || [];
    if (!updates.length) return 'No customer update yet.';
    return updates[updates.length - 1].message || 'No customer update yet.';
}

function renderPlans() {
    elements.planSelect.innerHTML = state.plans.map((plan) => (
        `<option value="${escapeHtml(plan.name)}">${escapeHtml(plan.name)} (${formatMoney(plan.amount)} / ${plan.duration_days} days)</option>`
    )).join('');

    const params = new URLSearchParams(window.location.search);
    const requestedPlan = params.get('plan');
    if (requestedPlan && state.plans.some((plan) => plan.name === requestedPlan)) {
        elements.planSelect.value = requestedPlan;
    }
    updateTotalDue();
}

function renderStats() {
    elements.totalCampaigns.textContent = state.campaigns.length;
    elements.activeCampaigns.textContent = state.campaigns.filter((campaign) => campaign.status === 'campaign_active').length;
    elements.pendingCampaigns.textContent = state.campaigns.filter((campaign) => ['pending_payment', 'paid_pending_review', 'approved_for_setup'].includes(campaign.status)).length;
}

function renderCampaigns() {
    renderStats();
    elements.subtitle.textContent = state.email ? `Showing campaigns for ${state.email}` : 'Enter your email to load your campaigns.';

    if (!state.email) {
        elements.list.innerHTML = '<div class="empty-state">No dashboard loaded yet.</div>';
        return;
    }

    if (!state.campaigns.length) {
        elements.list.innerHTML = '<div class="empty-state">No campaigns yet. Start a new promotion from the left panel.</div>';
        return;
    }

    elements.list.innerHTML = state.campaigns.map((campaign) => `
        <article class="campaign-card">
            <img src="${escapeHtml(campaign.thumbnail)}" alt="">
            <div class="campaign-main">
                <div style="display:flex; justify-content:space-between; gap:0.75rem; align-items:center; flex-wrap:wrap;">
                    <h3>${escapeHtml(campaign.video_title || 'Submitted YouTube Video')}</h3>
                    <span class="status-pill status-${escapeHtml(campaign.status)}">${escapeHtml(statusLabel(campaign.status))}</span>
                </div>
                <div class="campaign-meta">
                    <div><span>Plan</span>${escapeHtml(campaign.plan)}</div>
                    <div><span>Paid</span>${formatMoney(campaign.amount_paid || 0)}</div>
                    <div><span>Views Before</span>${Number(campaign.views_before || 0).toLocaleString()}</div>
                    <div><span>Countdown</span>${escapeHtml(countdownText(campaign))}</div>
                </div>
                <div class="dash-actions">
                    <a class="dash-btn" href="${escapeHtml(campaign.tracking_url)}" target="_blank"><i class="fas fa-location-dot"></i> Track</a>
                    <a class="dash-btn" href="${escapeHtml(campaign.video_url)}" target="_blank"><i class="fab fa-youtube"></i> Video</a>
                    ${campaign.status === 'pending_payment' ? `<button class="dash-btn primary" type="button" onclick="payExistingCampaign('${escapeHtml(campaign.tracking_code)}')"><i class="fas fa-credit-card"></i> Pay Now</button>` : ''}
                </div>
                <div class="updates">${escapeHtml(latestUpdate(campaign))}</div>
            </div>
        </article>
    `).join('');
}

async function loadPlans() {
    const response = await fetch(`${API_BASE}/plans`);
    const data = await response.json();
    if (!response.ok || !data.success) throw new Error(data.message || 'Could not load plans.');
    state.plans = data.plans || [];
    renderPlans();
}

async function loadDashboard(email = state.email) {
    const cleanEmail = String(email || '').trim().toLowerCase();
    if (!cleanEmail) return;

    showNotice('Loading your dashboard...');
    const response = await fetch(`${API_BASE}/customer/campaigns?email=${encodeURIComponent(cleanEmail)}`);
    const data = await response.json();
    if (!response.ok || !data.success) throw new Error(data.message || 'Could not load dashboard.');

    state.email = cleanEmail;
    state.campaigns = data.campaigns || [];
    if (data.plans?.length) {
        state.plans = data.plans;
        renderPlans();
    }
    localStorage.setItem('creatorlift_email', cleanEmail);
    elements.emailInput.value = cleanEmail;
    elements.paymentForm.style.display = 'grid';
    showNotice('');
    renderCampaigns();
}

async function createCampaign() {
    const plan = selectedPlan();
    if (!plan) throw new Error('Choose a campaign plan.');

    const response = await fetch(`${API_BASE}/campaigns`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
            email: state.email,
            video_url: elements.videoUrl.value,
            plan: plan.name,
            views_before: Number(elements.viewsBefore.value || 0),
            promotion_duration_days: plan.duration_days
        })
    });
    const data = await response.json();
    if (!response.ok || !data.success) throw new Error(data.message || 'Could not create campaign.');
    return data;
}

function openPaystackForCampaign(campaignData, plan, videoUrl) {
    const handler = PaystackPop.setup({
        key: PAYSTACK_PUBLIC_KEY,
        email: state.email,
        amount: Number(plan.amount || 0) * 100,
        currency: 'NGN',
        metadata: {
            campaign_id: campaignData.campaign_id,
            tracking_code: campaignData.tracking_code,
            plan: plan.name
        },
        callback: async function(response) {
            try {
                const verifyRes = await fetch(`${API_BASE}/order`, {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({
                        campaign_id: campaignData.campaign_id,
                        tracking_code: campaignData.tracking_code,
                        email: state.email,
                        video_url: videoUrl,
                        plan: plan.name,
                        reference: response.reference
                    })
                });
                const verifyData = await verifyRes.json();
                if (!verifyRes.ok || !verifyData.success) {
                    throw new Error(verifyData.message || 'Payment verification failed.');
                }
                showNotice('Payment received. Your campaign is pending review.');
                elements.videoUrl.value = '';
                elements.viewsBefore.value = '';
                await loadDashboard(state.email);
            } catch (err) {
                showNotice(err.message, 'error');
            }
        },
        onClose: function() {
            showNotice('Payment was not completed. The campaign is saved as pending payment.');
            loadDashboard(state.email).catch((err) => showNotice(err.message, 'error'));
        }
    });
    handler.openIframe();
}

window.payExistingCampaign = async function payExistingCampaign(trackingCode) {
    const campaign = state.campaigns.find((item) => item.tracking_code === trackingCode);
    if (!campaign) return;
    const plan = state.plans.find((item) => item.name === campaign.plan) || selectedPlan();
    openPaystackForCampaign({
        campaign_id: campaign.id,
        tracking_code: campaign.tracking_code
    }, plan, campaign.video_url);
};

elements.emailForm.addEventListener('submit', async (event) => {
    event.preventDefault();
    try {
        await loadDashboard(elements.emailInput.value);
    } catch (err) {
        showNotice(err.message, 'error');
    }
});

elements.paymentForm.addEventListener('submit', async (event) => {
    event.preventDefault();
    const button = elements.paymentForm.querySelector('button[type="submit"]');
    button.disabled = true;
    try {
        if (!state.email) throw new Error('Open your dashboard with an email first.');
        const plan = selectedPlan();
        const videoUrl = elements.videoUrl.value;
        showNotice('Creating your campaign...');
        const campaignData = await createCampaign();
        openPaystackForCampaign(campaignData, plan, videoUrl);
    } catch (err) {
        showNotice(err.message, 'error');
    } finally {
        button.disabled = false;
    }
});

elements.planSelect.addEventListener('change', updateTotalDue);
elements.refresh.addEventListener('click', () => loadDashboard(state.email).catch((err) => showNotice(err.message, 'error')));

loadPlans()
    .then(() => {
        if (state.email) return loadDashboard(state.email);
        renderCampaigns();
        return null;
    })
    .catch((err) => showNotice(err.message, 'error'));

setInterval(renderCampaigns, 60000);
