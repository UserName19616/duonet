/**
 * DuoNet API Calls
 * All backend API interactions
 */

// ============================================================================
// Contacts API
// ============================================================================

async function apiLoadContacts() {
    const token = getToken();
    if (!token) return { success: false, error: 'no_token' };

    try {
        const response = await fetch('/api/web/contacts', {
            headers: { 'Authorization': `Bearer ${token}` },
            credentials: 'include'
        });
        return await response.json();
    } catch (error) {
        console.error('apiLoadContacts error:', error);
        return { success: false, error: error.message };
    }
}

async function apiUpdateContactName(contactId, newName) {
    const token = getToken();
    if (!token) return { success: false, error: 'no_token' };

    try {
        const response = await fetch(`/api/web/contacts/${encodeURIComponent(contactId)}/name`, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
            credentials: 'include',
            body: JSON.stringify({ name: newName })
        });
        return await response.json();
    } catch (error) {
        console.error('apiUpdateContactName error:', error);
        return { success: false, error: error.message };
    }
}

// ============================================================================
// Invites API
// ============================================================================

async function apiLoadIncomingInvites() {
    const token = getToken();
    if (!token) return { success: false, error: 'no_token' };

    try {
        const response = await fetch('/api/web/invites', {
            headers: { 'Authorization': `Bearer ${token}` },
            credentials: 'include'
        });
        return await response.json();
    } catch (error) {
        console.error('apiLoadIncomingInvites error:', error);
        return { success: false, error: error.message };
    }
}

async function apiLoadOutgoingInvites() {
    const token = getToken();
    if (!token) return { success: false, error: 'no_token' };

    try {
        const response = await fetch('/api/web/invites/sent', {
            headers: { 'Authorization': `Bearer ${token}` },
            credentials: 'include'
        });
        return await response.json();
    } catch (error) {
        console.error('apiLoadOutgoingInvites error:', error);
        return { success: false, error: error.message };
    }
}

async function apiSendInvite(publicId, message, name) {
    const token = getToken();
    if (!token) return { success: false, error: 'no_token' };

    try {
        const response = await fetch('/api/web/invites/send', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
            credentials: 'include',
            body: JSON.stringify({ public_id: publicId, message: message, name: name })
        });
        return await response.json();
    } catch (error) {
        console.error('apiSendInvite error:', error);
        return { success: false, error: error.message };
    }
}

async function apiAcceptInvite(inviteId) {
    const token = getToken();
    if (!token) return { success: false, error: 'no_token' };

    try {
        const response = await fetch(`/api/web/invites/${inviteId}/accept`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
            credentials: 'include'
        });
        return await response.json();
    } catch (error) {
        console.error('apiAcceptInvite error:', error);
        return { success: false, error: error.message };
    }
}

async function apiRejectInvite(inviteId) {
    const token = getToken();
    if (!token) return { success: false, error: 'no_token' };

    try {
        const response = await fetch(`/api/web/invites/${inviteId}/reject`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
            credentials: 'include'
        });
        return await response.json();
    } catch (error) {
        console.error('apiRejectInvite error:', error);
        return { success: false, error: error.message };
    }
}

async function apiRevokeInvite(inviteId) {
    const token = getToken();
    if (!token) return { success: false, error: 'no_token' };

    try {
        const response = await fetch(`/api/web/invites/${inviteId}/revoke`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
            credentials: 'include'
        });
        return await response.json();
    } catch (error) {
        console.error('apiRevokeInvite error:', error);
        return { success: false, error: error.message };
    }
}

// ============================================================================
// Search API
// ============================================================================

async function apiSearchContacts(query) {
    const token = getToken();
    if (!token) return { success: false, error: 'no_token' };

    try {
        const response = await fetch('/api/web/contacts/search', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
            credentials: 'include',
            body: JSON.stringify({ query: query })
        });
        return await response.json();
    } catch (error) {
        console.error('apiSearchContacts error:', error);
        return { success: false, error: error.message };
    }
}

// ============================================================================
// Exports (global)
// ============================================================================

window.DuoNetAPI = {
    loadContacts: apiLoadContacts,
    updateContactName: apiUpdateContactName,
    loadIncomingInvites: apiLoadIncomingInvites,
    loadOutgoingInvites: apiLoadOutgoingInvites,
    sendInvite: apiSendInvite,
    acceptInvite: apiAcceptInvite,
    rejectInvite: apiRejectInvite,
    revokeInvite: apiRevokeInvite,
    searchContacts: apiSearchContacts
};
