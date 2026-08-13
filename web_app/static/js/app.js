// WebOpti Real-time Status & Execution JS

let statusInterval = null;

function formatBytes(bytes) {
    if (!bytes || bytes === 0) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
}

function startJob(mode) {
    const form = document.getElementById('pipeline-form');
    const formData = new FormData(form);
    formData.append('mode', mode);

    if (mode === 'dry_run') {
        formData.set('mode', 'generate');
        formData.append('dry_run', 'true');
    }

    fetch('/api/run/', {
        method: 'POST',
        body: formData
    })
    .then(res => res.json())
    .then(data => {
        if (data.success) {
            updateBadge('running', 'Processing...');
            if (!statusInterval) {
                statusInterval = setInterval(pollJobStatus, 1000);
            }
        } else {
            alert('Error: ' + data.error);
        }
    })
    .catch(err => console.error(err));
}

function stopJob() {
    fetch('/api/stop/', { method: 'POST' })
    .then(res => res.json())
    .then(data => {
        const btnStop = document.getElementById('btn-stop');
        if (btnStop) btnStop.textContent = 'Stopping...';
    })
    .catch(err => console.error(err));
}

function updateBadge(state, text) {
    const badge = document.getElementById('job-badge');
    const btnStop = document.getElementById('btn-stop');
    if (btnStop) {
        btnStop.style.display = (state === 'running') ? 'inline-flex' : 'none';
        if (state !== 'running') btnStop.textContent = '🛑 Stop Running Job';
    }
    if (!badge) return;
    badge.textContent = text;
    badge.className = 'badge';
    if (state === 'running') badge.classList.add('badge-info');
    else if (state === 'completed') badge.classList.add('badge-success');
    else if (state === 'error') badge.classList.add('badge-danger');
    else badge.classList.add('badge-neutral');
}

function pollJobStatus() {
    fetch('/api/status/')
    .then(res => res.json())
    .then(data => {
        const total = data.total_products || 0;
        const completed = data.completed_products || 0;
        const pct = total > 0 ? Math.round((completed / total) * 100) : 0;

        const progressBar = document.getElementById('progress-bar');
        const progressPct = document.getElementById('progress-percentage');
        const activeLabel = document.getElementById('active-product-label');
        const metricProducts = document.getElementById('metric-products');
        const metricAi = document.getElementById('metric-ai');
        const metricWebp = document.getElementById('metric-webp');
        const metricSaved = document.getElementById('metric-saved');
        const terminalBody = document.getElementById('terminal-logs');

        if (progressBar) progressBar.style.width = pct + '%';
        if (progressPct) progressPct.textContent = pct + '%';
        if (activeLabel) activeLabel.textContent = data.status_message || 'Idle';
        if (metricProducts) metricProducts.textContent = `${completed} / ${total}`;
        if (metricAi) metricAi.textContent = data.generations_count || 0;
        if (metricWebp) metricWebp.textContent = data.conversions_count || 0;

        const saved = (data.total_input_bytes || 0) - (data.total_output_bytes || 0);
        if (metricSaved) metricSaved.textContent = formatBytes(Math.max(0, saved));

        if (terminalBody && data.logs) {
            terminalBody.innerHTML = '';
            data.logs.forEach(line => {
                const div = document.createElement('div');
                div.className = 'log-line';
                div.textContent = line;
                terminalBody.appendChild(div);
            });
            terminalBody.scrollTop = terminalBody.scrollHeight;
        }

        if (!data.running) {
            if (completed === total && total > 0) {
                updateBadge('completed', 'Completed');
            } else if (data.errors && data.errors.length > 0) {
                updateBadge('error', 'Failed');
            } else {
                updateBadge('idle', 'Idle');
            }
            if (statusInterval) {
                clearInterval(statusInterval);
                statusInterval = null;
            }
        } else {
            updateBadge('running', 'Processing...');
        }
    })
    .catch(err => console.error(err));
}

document.addEventListener('DOMContentLoaded', () => {
    pollJobStatus();
});
