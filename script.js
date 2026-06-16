const API_BASE = '/api';
// Scroll Reveal Animation
const observerOptions = {
    threshold: 0.1
};

const observer = new IntersectionObserver((entries) => {
    entries.forEach(entry => {
        if (entry.isIntersecting) {
            entry.target.classList.add('active');
        }
    });
}, observerOptions);

document.querySelectorAll('.reveal').forEach(el => {
    observer.observe(el);
});

// Payment Form Handling
const paymentForm = document.getElementById('paymentForm');
const paymentFeedback = document.getElementById('paymentFeedback');

if (paymentForm) {
    paymentForm.addEventListener('submit', (e) => {
        e.preventDefault();
        
        const videoUrl = document.getElementById('videoUrl').value;
        const submitBtn = paymentForm.querySelector('button');
        
        // Disable button
        submitBtn.disabled = true;
        submitBtn.textContent = 'Processing...';

        const planSelect = paymentForm.querySelector('select');
        const selectedPlan = planSelect.options[planSelect.selectedIndex];
        const planName = planSelect.value;
        const email = document.getElementById('email').value;
        
        // Calculate price in Kobo (Naira * 100)
        const amount = Number(selectedPlan.dataset.amount || 15000) * 100;

        const PAYSTACK_PUBLIC_KEY = 'pk_live_7f3162d6e8ef7df846b5420af9f8084a9c7be2e1'; 

        fetch(`${API_BASE}/campaigns`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                email: email,
                video_url: videoUrl,
                plan: planName
            })
        })
        .then(async res => {
            const data = await res.json();
            if (!res.ok || !data.success) throw new Error(data.message || 'Could not create campaign.');

            const handler = PaystackPop.setup({
                key: PAYSTACK_PUBLIC_KEY,
                email: email,
                amount: amount,
                currency: 'NGN',
                metadata: {
                    campaign_id: data.campaign_id,
                    tracking_code: data.tracking_code,
                    plan: planName
                },
                callback: function(response) {
                    fetch(`${API_BASE}/order`, {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({
                            campaign_id: data.campaign_id,
                            tracking_code: data.tracking_code,
                            email: email,
                            video_url: videoUrl,
                            plan: planName,
                            reference: response.reference
                        })
                    })
                    .then(async verifyRes => {
                        const verifyData = await verifyRes.json();
                        if (!verifyRes.ok || !verifyData.success) {
                            throw new Error(verifyData.message || 'Payment verification failed.');
                        }
                        paymentForm.style.display = 'none';
                        paymentFeedback.innerHTML = `
                            <i class="fas fa-check-circle" style="font-size: 3rem; color: #22c55e; margin-bottom: 1rem;"></i>
                            <h3>Payment Received!</h3>
                            <p>Our team will review your video and campaign details before setup.</p>
                            <a href="${verifyData.tracking_url}" class="btn btn-primary" style="margin-top: 1.5rem;">Track Campaign</a>
                        `;
                        paymentFeedback.style.display = 'block';
                    })
                    .catch(err => {
                        submitBtn.disabled = false;
                        submitBtn.textContent = 'Pay & Submit for Review';
                        alert(err.message);
                    });
                },
                onClose: function() {
                    submitBtn.disabled = false;
                    submitBtn.textContent = 'Pay & Submit for Review';
                    alert('Transaction was not completed. Your campaign is saved as pending payment.');
                }
            });
            handler.openIframe();
        })
        .catch(err => {
            submitBtn.disabled = false;
            submitBtn.textContent = 'Pay & Submit for Review';
            alert(err.message);
        });
    });
}

// Update Total Due display when plan changes
const planSelect = document.getElementById('planSelect');
const totalDue = document.getElementById('totalDue');

if (planSelect && totalDue) {
    const formatNaira = (amount) => `\u20a6${Number(amount).toLocaleString()}`;
    const updateTotalDue = () => {
        const selectedPlan = planSelect.options[planSelect.selectedIndex];
        totalDue.textContent = formatNaira(selectedPlan.dataset.amount || 15000);
    };

    planSelect.addEventListener('change', updateTotalDue);
    updateTotalDue();

    document.querySelectorAll('.plan-cta').forEach(button => {
        button.addEventListener('click', () => {
            const plan = button.dataset.plan;
            const option = Array.from(planSelect.options).find(item => item.value === plan);
            if (option) {
                planSelect.value = option.value;
                updateTotalDue();
            }
        });
    });
}

function escapeHtml(value) {
    return String(value || '').replace(/[&<>"']/g, (char) => ({
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        '"': '&quot;',
        "'": '&#039;'
    }[char]));
}

// Smooth scrolling for anchor links
document.querySelectorAll('a[href^="#"]').forEach(anchor => {
    anchor.addEventListener('click', function (e) {
        e.preventDefault();

        const target = document.querySelector(this.getAttribute('href'));
        if (target) {
            target.scrollIntoView({
                behavior: 'smooth'
            });
        }
    });
});

// Dynamic Video Loader for Landing Page
async function loadNetworkVideos() {
    const grid = document.getElementById('curationGrid');
    if (!grid) return;

    try {
        const response = await fetch(`${API_BASE}/curation`);
        if (!response.ok) throw new Error('No campaign data found');
        
        const data = await response.json();
        const videos = data.campaigns || [];
        
        if (videos.length === 0) {
            grid.innerHTML = `
                <div class="empty-state">
                    <i class="fas fa-video" aria-hidden="true"></i>
                    <h3>No active featured videos yet</h3>
                    <p>Eligible campaigns appear here after review, setup, and curation approval.</p>
                </div>
            `;
            return;
        }
        
        // Clear existing static cards
        grid.innerHTML = '';
        
        // Add new dynamic cards
        videos.forEach(video => {
            const card = document.createElement('a');
            card.href = `watch.html?campaign=${encodeURIComponent(video.tracking_code)}`;
            card.className = 'card reveal';
            card.style.textDecoration = 'none';
            card.style.textAlign = 'center';
            card.innerHTML = `
                <img src="${escapeHtml(video.thumbnail)}" alt="" style="width: 100%; border-radius: 12px; margin-bottom: 1rem;">
                <h3>${escapeHtml(video.video_title || 'Featured Creator Video')}</h3>
                <p>${escapeHtml(video.curation_category || 'Creator Campaign')} &bull; Reviewed placement</p>
            `;
            grid.appendChild(card);
            
            // Re-observe the new card for reveal animation
            observer.observe(card);
        });
    } catch (err) {
        grid.innerHTML = `
            <div class="empty-state">
                <i class="fas fa-video" aria-hidden="true"></i>
                <h3>Curation hub is unavailable</h3>
                <p>Please refresh later to see approved campaign placements.</p>
            </div>
        `;
    }
}

loadNetworkVideos();

// Subtle background mouse effect
document.addEventListener('mousemove', (e) => {
    const blobs = document.querySelectorAll('.blob');
    const x = e.clientX;
    const y = e.clientY;

    blobs.forEach((blob, index) => {
        const speed = (index + 1) * 0.02;
        const dx = (window.innerWidth / 2 - x) * speed;
        const dy = (window.innerHeight / 2 - y) * speed;
        blob.style.transform = `translate(${dx}px, ${dy}px)`;
    });
});

// FAQ Toggle Logic
function toggleFaq(btn) {
    const item = btn.parentElement;
    const isActive = item.classList.contains('active');
    
    // Close all other items
    document.querySelectorAll('.faq-item').forEach(el => el.classList.remove('active'));
    
    // Toggle current item
    if (!isActive) {
        item.classList.add('active');
    }
}

// WhatsApp Tooltip Pulse
const whatsappBtn = document.getElementById('whatsappBtn');
if (whatsappBtn) {
    setTimeout(() => {
        const tooltip = whatsappBtn.querySelector('.whatsapp-tooltip');
        if (tooltip) tooltip.style.opacity = '1';
        if (tooltip) tooltip.style.visibility = 'visible';
    }, 3000);
}
