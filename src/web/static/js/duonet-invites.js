/**
 * DuoNet Invites Logic
 * Loading and managing incoming/outgoing invites with local history
 */

let currentInviteTab = 'incoming';

// Ключ для хранения истории отклонённых приглашений в localStorage
const REJECTED_INVITES_KEY = 'duonet_rejected_invites';

// Сохраняем отклонённое приглашение в историю
function saveRejectedInvite(invite) {
    const stored = JSON.parse(localStorage.getItem(REJECTED_INVITES_KEY) || '{}');
    const userKey = `user_${invite.from_id}`;
    if (!stored[userKey]) stored[userKey] = [];

    // Добавляем новое приглашение в начало
    stored[userKey].unshift({
        invite_id: invite.invite_id,
        from_id: invite.from_id,
        message: invite.message,
        timestamp: invite.timestamp,
        rejected_at: Date.now() / 1000,
        status: 'rejected'
    });

    // Оставляем только последние 20 записей
    if (stored[userKey].length > 20) stored[userKey] = stored[userKey].slice(0, 20);

    localStorage.setItem(REJECTED_INVITES_KEY, JSON.stringify(stored));
}

// Получаем историю отклонённых для пользователя
function getRejectedHistory(fromId) {
    const stored = JSON.parse(localStorage.getItem(REJECTED_INVITES_KEY) || '{}');
    const userKey = `user_${fromId}`;
    return stored[userKey] || [];
}

// Очищаем историю для пользователя (если приглашение было принято позже)
function clearRejectedHistory(fromId) {
    const stored = JSON.parse(localStorage.getItem(REJECTED_INVITES_KEY) || '{}');
    const userKey = `user_${fromId}`;
    delete stored[userKey];
    localStorage.setItem(REJECTED_INVITES_KEY, JSON.stringify(stored));
}

async function loadIncomingInvites() {
    const container = document.getElementById('invitesContainer');
    if (!container) return;

    showLoading('invitesContainer', 'Загрузка...');

    const result = await DuoNetAPI.loadIncomingInvites();

    // Получаем историю отклонённых
    const allInvites = [];

    if (result.success && result.data.invites && result.data.invites.length > 0) {
        // Добавляем активные приглашения
        for (const invite of result.data.invites) {
            allInvites.push({
                ...invite,
                source: 'active',
                is_expired: invite.expires_at < Date.now() / 1000
            });
        }
    }

    // Добавляем историю отклонённых для каждого отправителя
    const senders = new Set(allInvites.map(i => i.from_id));
    for (const sender of senders) {
        const history = getRejectedHistory(sender);
        for (const hist of history) {
            allInvites.push({
                invite_id: hist.invite_id,
                from_id: hist.from_id,
                message: hist.message,
                status: hist.status,
                timestamp: hist.timestamp,
                rejected_at: hist.rejected_at,
                source: 'history',
                is_expired: true
            });
        }
    }

    // Сортируем по времени (сначала новые)
    allInvites.sort((a, b) => (b.timestamp || 0) - (a.timestamp || 0));

    if (allInvites.length > 0) {
        let html = '';
        for (const invite of allInvites) {
            const isExpired = invite.is_expired || (invite.expires_at < Date.now() / 1000);
            const isActive = invite.source === 'active' && invite.status === 'pending' && !isExpired;

            // Определяем стиль
            let statusBadge = '';
            let statusClass = '';

            if (invite.source === 'history') {
                statusBadge = '<span class="ml-2 px-2 py-0.5 rounded text-xs bg-red-100 text-red-800">✗ Отклонено (история)</span>';
                statusClass = 'bg-gray-50 opacity-70';
            } else if (invite.status === 'accepted') {
                statusBadge = '<span class="ml-2 px-2 py-0.5 rounded text-xs bg-green-100 text-green-800">✓ Принято</span>';
                statusClass = 'bg-green-50';
            } else if (invite.status === 'rejected') {
                statusBadge = '<span class="ml-2 px-2 py-0.5 rounded text-xs bg-red-100 text-red-800">✗ Отклонено</span>';
                statusClass = 'bg-gray-50 opacity-70';
                // Сохраняем в историю
                saveRejectedInvite(invite);
            } else if (invite.status === 'revoked') {
                statusBadge = '<span class="ml-2 px-2 py-0.5 rounded text-xs bg-gray-100 text-gray-800">↩ Отозвано</span>';
                statusClass = 'bg-gray-50 opacity-70';
            } else if (isExpired && invite.status === 'pending') {
                statusBadge = '<span class="ml-2 px-2 py-0.5 rounded text-xs bg-gray-100 text-gray-800">⏰ Истекло</span>';
                statusClass = 'bg-gray-50 opacity-70';
            } else if (invite.status === 'pending') {
                statusBadge = '<span class="ml-2 px-2 py-0.5 rounded text-xs bg-yellow-100 text-yellow-800">⏳ Ожидает</span>';
                statusClass = 'bg-white';
            }

            const messagePreview = invite.message ?
                (invite.message.length > 60 ? invite.message.substring(0, 60) + '...' : invite.message) :
                'Без сообщения';

            const showActions = isActive;

            html += `
                <div class="border rounded-lg p-3 ${statusClass}">
                    <div class="flex justify-between items-start">
                        <div class="flex-1">
                            <div class="font-bold">📩 От: ${escapeHtml(invite.from_id)}${statusBadge}</div>
                            <div class="text-sm text-gray-500 italic mt-1">📝 "${escapeHtml(messagePreview)}"</div>
                            <div class="text-xs text-gray-400 mt-2">
                                Получено: ${formatTime(invite.timestamp)}
                                ${invite.rejected_at ? `<br>✗ Отклонено: ${formatTime(invite.rejected_at)}` : ''}
                            </div>
                        </div>
                        ${showActions ? `
                        <div class="flex gap-2 ml-4">
                            <button onclick="DuoNetInvites.acceptInvite('${invite.invite_id}')"
                                    class="bg-green-500 text-white px-3 py-1 rounded hover:bg-green-600 text-sm">
                                ✓ Принять
                            </button>
                            <button onclick="DuoNetInvites.rejectInvite('${invite.invite_id}')"
                                    class="bg-red-500 text-white px-3 py-1 rounded hover:bg-red-600 text-sm">
                                ✗ Отклонить
                            </button>
                        </div>
                        ` : ''}
                    </div>
                </div>
            `;
        }
        container.innerHTML = html;
    } else {
        container.innerHTML = '<div class="text-center text-gray-500 py-8">📭 Нет входящих приглашений</div>';
    }
}

async function loadOutgoingInvites() {
    const container = document.getElementById('invitesContainer');
    if (!container) return;

    showLoading('invitesContainer', 'Загрузка...');

    const result = await DuoNetAPI.loadOutgoingInvites();

    if (result.success && result.data.invites && result.data.invites.length > 0) {
        let html = '';
        for (const invite of result.data.invites) {
            const isExpired = invite.expires_at < Date.now() / 1000;
            const isPending = invite.status === 'pending';
            const messagePreview = invite.message ?
                (invite.message.length > 60 ? invite.message.substring(0, 60) + '...' : invite.message) :
                'Без сообщения';

            let statusBadge = '';
            if (invite.status === 'accepted') {
                statusBadge = '<span class="ml-2 px-2 py-0.5 rounded text-xs bg-green-100 text-green-800">✓ Принято</span>';
            } else if (invite.status === 'rejected') {
                statusBadge = '<span class="ml-2 px-2 py-0.5 rounded text-xs bg-red-100 text-red-800">✗ Отклонено</span>';
            } else if (invite.status === 'revoked') {
                statusBadge = '<span class="ml-2 px-2 py-0.5 rounded text-xs bg-gray-100 text-gray-800">↩ Отозвано</span>';
            } else if (isExpired && invite.status === 'pending') {
                statusBadge = '<span class="ml-2 px-2 py-0.5 rounded text-xs bg-gray-100 text-gray-800">⏰ Истекло</span>';
            } else if (invite.status === 'pending') {
                statusBadge = '<span class="ml-2 px-2 py-0.5 rounded text-xs bg-yellow-100 text-yellow-800">⏳ Ожидает</span>';
            }

            html += `
                <div class="border rounded-lg p-3 bg-white">
                    <div class="flex justify-between items-start">
                        <div class="flex-1">
                            <div class="font-bold">📤 Кому: ${escapeHtml(invite.to_id)}${statusBadge}</div>
                            <div class="text-sm text-gray-500 italic mt-1">📝 "${escapeHtml(messagePreview)}"</div>
                            <div class="text-xs text-gray-400 mt-2">
                                Отправлено: ${formatTime(invite.timestamp)}
                            </div>
                        </div>
                        ${isPending && !isExpired ? `
                        <button onclick="DuoNetInvites.revokeInvite('${invite.invite_id}')"
                                class="bg-orange-500 text-white px-3 py-1 rounded hover:bg-orange-600 text-sm ml-4">
                            ↩ Отозвать
                        </button>
                        ` : ''}
                    </div>
                </div>
            `;
        }
        container.innerHTML = html;
    } else {
        container.innerHTML = '<div class="text-center text-gray-500 py-8">📤 Нет отправленных приглашений</div>';
    }
}

async function acceptInvite(inviteId) {
    const result = await DuoNetAPI.acceptInvite(inviteId);
    if (result.success) {
        showToast('✅ Контакт добавлен!', 'success');

        // Получаем информацию о принятом приглашении
        const invitesResult = await DuoNetAPI.loadIncomingInvites();
        if (invitesResult.success && invitesResult.data.invites) {
            const acceptedInvite = invitesResult.data.invites.find(i => i.invite_id === inviteId);
            if (acceptedInvite) {
                clearRejectedHistory(acceptedInvite.from_id);
            }
        }

        if (currentInviteTab === 'incoming') await loadIncomingInvites();
        await loadContacts();
    } else {
        showToast('❌ Ошибка: ' + (result.detail || result.error), 'error');
    }
}

async function rejectInvite(inviteId) {
    const result = await DuoNetAPI.rejectInvite(inviteId);
    if (result.success) {
        showToast('❌ Приглашение отклонено', 'success');

        // Получаем информацию об отклонённом приглашении
        const invitesResult = await DuoNetAPI.loadIncomingInvites();
        if (invitesResult.success && invitesResult.data.invites) {
            const rejectedInvite = invitesResult.data.invites.find(i => i.invite_id === inviteId);
            if (rejectedInvite) {
                saveRejectedInvite(rejectedInvite);
            }
        }

        if (currentInviteTab === 'incoming') await loadIncomingInvites();
    } else {
        showToast('Ошибка: ' + (result.detail || result.error), 'error');
    }
}

async function revokeInvite(inviteId) {
    if (!confirm('Отозвать приглашение? Получатель не сможет его принять.')) return;

    const result = await DuoNetAPI.revokeInvite(inviteId);
    if (result.success) {
        showToast('✅ Приглашение отозвано', 'success');
        if (currentInviteTab === 'outgoing') await loadOutgoingInvites();
    } else {
        showToast('Ошибка: ' + (result.detail || result.error), 'error');
    }
}

function switchInviteTab(tab) {
    currentInviteTab = tab;

    const tabIncoming = document.getElementById('tab-incoming');
    const tabOutgoing = document.getElementById('tab-outgoing');
    const container = document.getElementById('invitesContainer');

    if (tabIncoming) tabIncoming.className = 'flex-1 py-2 bg-gray-200 text-gray-700';
    if (tabOutgoing) tabOutgoing.className = 'flex-1 py-2 bg-gray-200 text-gray-700';

    if (tab === 'incoming') {
        if (tabIncoming) tabIncoming.className = 'flex-1 py-2 bg-blue-500 text-white';
        loadIncomingInvites();
    } else {
        if (tabOutgoing) tabOutgoing.className = 'flex-1 py-2 bg-blue-500 text-white';
        loadOutgoingInvites();
    }
}

function setupInvitesModule() {
    const tabIncoming = document.getElementById('tab-incoming');
    const tabOutgoing = document.getElementById('tab-outgoing');

    if (tabIncoming) tabIncoming.onclick = () => switchInviteTab('incoming');
    if (tabOutgoing) tabOutgoing.onclick = () => switchInviteTab('outgoing');
}

// Экспортируем функции
window.DuoNetInvites = {
    loadIncomingInvites,
    loadOutgoingInvites,
    acceptInvite,
    rejectInvite,
    revokeInvite,
    switchInviteTab,
    setupInvitesModule
};
