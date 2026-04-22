/**
 * DuoNet Contacts Logic
 * Loading and managing contacts list
 */

let currentEditContactId = null;

async function loadContacts() {
    const container = document.getElementById('contactsList');
    if (!container) return;

    showLoading('contactsList', 'Загрузка контактов...');

    const result = await DuoNetAPI.loadContacts();

    if (result.success && result.data.contacts && result.data.contacts.length > 0) {
        let html = '';
        for (const contact of result.data.contacts) {
            const statusIcon = contact.online ? '🟢' : '⚪';
            html += `
                <div class="border rounded-lg p-3 hover:bg-gray-50 transition">
                    <div class="flex justify-between items-center">
                        <div class="flex-1 cursor-pointer" onclick="window.openChat('${escapeHtml(contact.public_id)}')">
                            <div class="font-bold">${statusIcon} ${escapeHtml(contact.name)}</div>
                            <div class="text-xs text-gray-500 font-mono">${escapeHtml(contact.public_id)}</div>
                        </div>
                        <div class="flex items-center space-x-2">
                            <button onclick="openEditModal('${escapeHtml(contact.public_id)}', '${escapeHtml(contact.name)}')"
                                    class="text-gray-500 hover:text-blue-500 px-2 py-1 rounded" title="Редактировать имя">
                                ✏️
                            </button>
                            ${contact.phrase_known ? '<span class="text-green-500 text-sm" title="Фраза установлена">🔐</span>' : ''}
                        </div>
                    </div>
                </div>
            `;
        }
        container.innerHTML = html;
    } else {
        container.innerHTML = '<div class="text-center text-gray-500 py-8">📭 Нет контактов. Отправьте приглашение.</div>';
    }
}

function openEditModal(contactId, currentName) {
    currentEditContactId = contactId;
    document.getElementById('editContactId').textContent = contactId;
    document.getElementById('editNameInput').value = currentName;
    showModal('editNameModal');
}

async function saveContactName() {
    const newName = document.getElementById('editNameInput').value.trim();
    if (!newName || newName.length > 64) {
        showToast('Имя должно быть от 1 до 64 символов', 'error');
        return;
    }

    const result = await DuoNetAPI.updateContactName(currentEditContactId, newName);

    if (result.success) {
        showToast('Имя контакта обновлено', 'success');
        hideModal('editNameModal');
        await loadContacts();
    } else {
        showToast(result.error || 'Ошибка обновления имени', 'error');
    }
}

function setupContactsModule() {
    const cancelBtn = document.getElementById('cancelEditBtn');
    if (cancelBtn) cancelBtn.onclick = () => hideModal('editNameModal');

    const saveBtn = document.getElementById('saveEditBtn');
    if (saveBtn) saveBtn.onclick = saveContactName;

    setupModalClose('editNameModal', 'cancelEditBtn');
}

window.openChat = function(contactId) {
    const token = getToken();
    window.location.href = `/api/web/chat/${encodeURIComponent(contactId)}/page?token=${encodeURIComponent(token)}`;
};

window.DuoNetContacts = {
    loadContacts,
    openEditModal,
    saveContactName,
    setupContactsModule
};
