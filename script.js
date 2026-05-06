const API_BASE = 'http://localhost:5000/api';
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

        const PAYSTACK_PUBLIC_KEY = 'pk_test_your_key_here'; // REPLACE THIS WITH YOUR KEY

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
