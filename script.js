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
