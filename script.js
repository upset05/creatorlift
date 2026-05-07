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

        const planName = paymentForm.querySelector('select').value;
        const email = document.getElementById('email').value;
        
        // Calculate price in Kobo (Naira * 100)
        let amount = 15000 * 100; // Default
        if (planName.includes('45k')) amount = 45000 * 100;
        if (planName.includes('85k')) amount = 85000 * 100;

        const PAYSTACK_PUBLIC_KEY = 'pk_test_3068412269896bd3f923c070d8c645118979fcf6'; 

        const handler = PaystackPop.setup({
            key: PAYSTACK_PUBLIC_KEY,
            email: email,
            amount: amount,
            currency: 'NGN',
            callback: function(response) {
                // Payment successful! Now send to backend
                fetch(`${API_BASE}/order`, {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({
                        email: email,
                        video_url: videoUrl,
                        plan: planName,
                        reference: response.reference
                    })
                }).then(() => {
                    paymentForm.style.display = 'none';
                    paymentFeedback.innerHTML = `
                        <i class="fas fa-check-circle" style="font-size: 3rem; color: #22c55e; margin-bottom: 1rem;"></i>
                        <h3>Payment Received!</h3>
                        <p>Our agency is now preparing your campaign. Check your email for details.</p>
                    `;
                    paymentFeedback.style.display = 'block';
                });
            },
            onClose: function() {
                submitBtn.disabled = false;
                submitBtn.textContent = 'Pay & Start Promotion';
                alert('Transaction was not completed.');
            }
        });
        handler.openIframe();
    });
}

// Update Total Due display when plan changes
const planSelect = document.getElementById('planSelect');
const totalDue = document.getElementById('totalDue');

if (planSelect && totalDue) {
    planSelect.addEventListener('change', () => {
        const plan = planSelect.value;
        let priceText = '₦15,000';
        if (plan.includes('45k')) priceText = '₦45,000';
        if (plan.includes('85k')) priceText = '₦85,000';
        totalDue.textContent = priceText;
    });
}

// Smooth scrolling for anchor links
document.querySelectorAll('a[href^="#"]').forEach(anchor => {
    anchor.addEventListener('click', function (e) {
        e.preventDefault();

        document.querySelector(this.getAttribute('href')).scrollIntoView({
            behavior: 'smooth'
        });
    });
});

// Dynamic Video Loader for Landing Page
async function loadNetworkVideos() {
    const grid = document.querySelector('#pricing').previousElementSibling.querySelector('.grid');
    if (!grid) return;

    try {
        const response = await fetch('videos.json');
        if (!response.ok) throw new Error('No video data found');
        
        const videos = await response.json();
        
        if (videos.length === 0) {
            grid.innerHTML = `
                <div style="grid-column: 1/-1; text-align: center; padding: 4rem; background: rgba(255,255,255,0.02); border-radius: 24px; border: 1px dashed var(--glass-border);">
                    <i class="fas fa-rocket" style="font-size: 3rem; color: var(--primary-glow); margin-bottom: 1rem; opacity: 0.5;"></i>
                    <h3>Network Initializing...</h3>
                    <p style="color: var(--text-secondary);">Your campaign will appear here once activated by our team.</p>
                </div>
            `;
            return;
        }
        
        // Clear existing static cards
        grid.innerHTML = '';
        
        // Add new dynamic cards
        videos.forEach(video => {
            const card = document.createElement('a');
            card.href = `watch.html?v=${video.id}`;
            card.className = 'card reveal';
            card.style.textDecoration = 'none';
            card.style.textAlign = 'center';
            card.innerHTML = `
                <img src="${video.thumbnail}" style="width: 100%; border-radius: 12px; margin-bottom: 1rem;">
                <h3>${video.title}</h3>
                <p>By ${video.creator} • Promoted</p>
            `;
            grid.appendChild(card);
            
            // Re-observe the new card for reveal animation
            observer.observe(card);
        });
    } catch (err) {
        console.log('Using static demo data (Run ingest.py to update)');
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

// Stats Counter Animation
function animateStats() {
    const stats = document.querySelectorAll('.stat-number');
    stats.forEach(stat => {
        const target = parseInt(stat.getAttribute('data-target'));
        const suffix = stat.getAttribute('data-suffix') || '';
        let count = 0;
        const duration = 2000; // 2 seconds
        const increment = target / (duration / 16); // 60fps
        
        const updateCount = () => {
            count += increment;
            if (count < target) {
                stat.innerText = Math.floor(count).toLocaleString() + suffix;
                requestAnimationFrame(updateCount);
            } else {
                stat.innerText = target.toLocaleString() + suffix;
            }
        };
        updateCount();
    });
}

// Update Intersection Observer to trigger stats animation
const statsObserver = new IntersectionObserver((entries) => {
    entries.forEach(entry => {
        if (entry.isIntersecting) {
            animateStats();
            statsObserver.unobserve(entry.target);
        }
    });
}, { threshold: 0.5 });

const statsBanner = document.querySelector('.stats-banner');
if (statsBanner) statsObserver.observe(statsBanner);

// WhatsApp Tooltip Pulse
const whatsappBtn = document.getElementById('whatsappBtn');
if (whatsappBtn) {
    setTimeout(() => {
        const tooltip = whatsappBtn.querySelector('.whatsapp-tooltip');
        if (tooltip) tooltip.style.opacity = '1';
        if (tooltip) tooltip.style.visibility = 'visible';
    }, 3000);
}
