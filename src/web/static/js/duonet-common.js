/**
 * DuoNet Common Utilities
 * Shared functions for all pages
 */

// ============================================================================
// Token Management
// ============================================================================

function getToken() {
    // Сначала пробуем из sessionStorage
    let token = sessionStorage.getItem('duonet_token');
    if (token) return token;

    // Потом из cookie (теперь cookie не httponly, должна быть видна)
    token = getCookie('token');
    if (token) {
        sessionStorage.setItem('duonet_token', token);
        return token;
    }

    // Потом из URL параметра
    const urlParams = new URLSearchParams(window.location.search);
    token = urlParams.get('token');
    if (token) {
        sessionStorage.setItem('duonet_token', token);
        return token;
    }

    console.error('No token found!');
    return null;
}

function getCookie(name) {
    const value = `; ${document.cookie}`;
    const parts = value.split(`; ${name}=`);
    if (parts.length === 2) return parts.pop().split(';').shift();
    return null;
}

function clearToken() {
    sessionStorage.removeItem('duonet_token');
}

// ============================================================================
// UI Helpers
// ============================================================================

function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function showToast(message, type = 'info') {
    const existingToast = document.querySelector('.toast');
    if (existingToast) existingToast.remove();

    const toast = document.createElement('div');
    toast.className = `fixed bottom-4 right-4 px-4 py-2 rounded text-white z-50 ${
        type === 'success' ? 'bg-green-500' :
        type === 'error' ? 'bg-red-500' :
        'bg-blue-500'
    }`;
    toast.textContent = message;
    document.body.appendChild(toast);

    setTimeout(() => toast.remove(), 3000);
}

function formatTime(timestamp) {
    if (!timestamp) return '';
    return new Date(timestamp * 1000).toLocaleString();
}

function formatTimeShort(timestamp) {
    if (!timestamp) return '';
    return new Date(timestamp * 1000).toLocaleTimeString([], {
        hour: '2-digit',
        minute: '2-digit'
    });
}

// ============================================================================
// Loading States
// ============================================================================

function showLoading(containerId, message = 'Загрузка...') {
    const container = document.getElementById(containerId);
    if (container) {
        container.innerHTML = `<div class="text-center text-gray-500 py-8">${escapeHtml(message)}</div>`;
    }
}

function showError(containerId, message) {
    const container = document.getElementById(containerId);
    if (container) {
        container.innerHTML = `<div class="text-center text-red-500 py-8">❌ ${escapeHtml(message)}</div>`;
    }
}

// ============================================================================
// Modal Helpers
// ============================================================================

function showModal(modalId) {
    const modal = document.getElementById(modalId);
    if (modal) {
        modal.classList.remove('hidden');
        modal.classList.add('flex');
    }
}

function hideModal(modalId) {
    const modal = document.getElementById(modalId);
    if (modal) {
        modal.classList.add('hidden');
        modal.classList.remove('flex');
    }
}

function setupModalClose(modalId, closeBtnId = null) {
    const modal = document.getElementById(modalId);
    if (!modal) return;

    if (closeBtnId) {
        const closeBtn = document.getElementById(closeBtnId);
        if (closeBtn) closeBtn.onclick = () => hideModal(modalId);
    }

    modal.addEventListener('click', (e) => {
        if (e.target === modal) hideModal(modalId);
    });

    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && modal.classList.contains('flex')) {
            hideModal(modalId);
        }
    });
}

// ============================================================================
// Exports (global)
// ============================================================================

window.DuoNetCommon = {
    getToken, clearToken, getCookie,
    escapeHtml, showToast, formatTime, formatTimeShort,
    showLoading, showError,
    showModal, hideModal, setupModalClose
};
