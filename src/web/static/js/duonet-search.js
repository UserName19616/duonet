/**
 * DuoNet Search Logic
 * Finding users and sending invites
 */

let pendingInvitePublicId = null;

function showSendInviteModal(publicId) {
    pendingInvitePublicId = publicId;
    document.getElementById('inviteTargetPublicId').innerText = publicId;
    document.getElementById('inviteMessage').value = '';
    document.getElementById('inviteLocalName').value = 'Контакт';
    document.getElementById('inviteMessageCounter').innerText = '0';
    showModal('sendInviteModal');
}

function hideSendInviteModal() {
    hideModal('sendInviteModal');
    pendingInvitePublicId = null;
}

async function sendInviteAction() {
    const message = document.getElementById('inviteMessage').value.trim();
    const name = document.getElementById('inviteLocalName').value.trim();

    if (!name) {
        showToast('Укажите локальное имя контакта', 'error');
        return;
    }
    if (message.length > 200) {
        showToast('Сообщение слишком длинное (макс. 200 символов)', 'error');
        return;
    }

    const result = await DuoNetAPI.sendInvite(pendingInvitePublicId, message, name);

    if (result.success) {
        showToast(`✅ Приглашение отправлено пользователю ${pendingInvitePublicId}`, 'success');
        hideSendInviteModal();

        const searchInput = document.getElementById('searchInput');
        if (searchInput) searchInput.value = '';

        const searchResults = document.getElementById('searchResults');
        if (searchResults) searchResults.style.display = 'none';

        if (currentInviteTab === 'outgoing') {
            await loadOutgoingInvites();
        }
    } else {
        showToast('❌ Ошибка: ' + (result.detail || result.error), 'error');
    }
}

async function searchContact() {
    const query = document.getElementById('searchInput').value.trim();
    if (!query) return;

    const result = await DuoNetAPI.searchContacts(query);
    const resultsDiv = document.getElementById('searchResults');
    const resultsList = document.getElementById('searchResultsList');

    if (result.success && result.data.results && result.data.results.length > 0) {
        resultsList.innerHTML = '';
        for (const item of result.data.results) {
            resultsList.innerHTML += `
                <div class="border rounded-lg p-3 flex justify-between items-center">
                    <div>
                        <div class="font-bold">${escapeHtml(item.public_id)}</div>
                        <div class="text-sm text-gray-500">${item.type}</div>
                    </div>
                    <button onclick="showSendInviteModal('${escapeHtml(item.public_id)}')"
                            class="bg-green-500 text-white px-3 py-1 rounded hover:bg-green-600">
                        ➕ Пригласить
                    </button>
                </div>
            `;
        }
        resultsDiv.style.display = 'block';
    } else {
        resultsList.innerHTML = '<div class="text-gray-500">Ничего не найдено</div>';
        resultsDiv.style.display = 'block';
    }
}

function closeSearchResults() {
    const resultsDiv = document.getElementById('searchResults');
    const searchInput = document.getElementById('searchInput');
    if (resultsDiv) resultsDiv.style.display = 'none';
    if (searchInput) searchInput.value = '';
}

function setupSearchModule() {
    const searchBtn = document.getElementById('searchBtn');
    const searchInput = document.getElementById('searchInput');
    const closeBtn = document.getElementById('closeSearchResults');
    const cancelBtn = document.getElementById('cancelInviteBtn');
    const sendBtn = document.getElementById('sendInviteBtn');
    const messageInput = document.getElementById('inviteMessage');

    if (searchBtn) searchBtn.onclick = searchContact;
    if (searchInput) searchInput.onkeypress = (e) => { if (e.key === 'Enter') searchContact(); };
    if (closeBtn) closeBtn.onclick = closeSearchResults;
    if (cancelBtn) cancelBtn.onclick = hideSendInviteModal;
    if (sendBtn) sendBtn.onclick = sendInviteAction;

    if (messageInput) {
        messageInput.addEventListener('input', function() {
            const len = this.value.length;
            const counter = document.getElementById('inviteMessageCounter');
            if (counter) counter.innerText = len;
            if (len > 200) this.value = this.value.substring(0, 200);
        });
    }

    setupModalClose('sendInviteModal', 'cancelInviteBtn');
}

window.DuoNetSearch = {
    showSendInviteModal,
    hideSendInviteModal,
    sendInviteAction,
    searchContact,
    closeSearchResults,
    setupSearchModule
};
