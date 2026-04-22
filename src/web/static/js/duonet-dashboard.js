/**
 * DuoNet Dashboard Controller
 * Main initialization and tab switching
 */

let currentTab = 'contacts';

function switchTab(tab) {
    currentTab = tab;

    const contactsList = document.getElementById('contactsList');
    const invitesContainer = document.getElementById('invitesContainer');
    const tabContacts = document.getElementById('tab-contacts');
    const tabIncoming = document.getElementById('tab-incoming');
    const tabOutgoing = document.getElementById('tab-outgoing');

    if (tabContacts) tabContacts.className = 'flex-1 py-2 bg-gray-200 text-gray-700';
    if (tabIncoming) tabIncoming.className = 'flex-1 py-2 bg-gray-200 text-gray-700';
    if (tabOutgoing) tabOutgoing.className = 'flex-1 py-2 bg-gray-200 text-gray-700';

    if (tab === 'contacts') {
        if (contactsList) contactsList.style.display = 'block';
        if (invitesContainer) invitesContainer.style.display = 'none';
        if (tabContacts) tabContacts.className = 'flex-1 py-2 bg-blue-500 text-white';
        loadContacts();
    } else if (tab === 'incoming') {
        if (contactsList) contactsList.style.display = 'none';
        if (invitesContainer) invitesContainer.style.display = 'block';
        if (tabIncoming) tabIncoming.className = 'flex-1 py-2 bg-blue-500 text-white';
        loadIncomingInvites();
    } else if (tab === 'outgoing') {
        if (contactsList) contactsList.style.display = 'none';
        if (invitesContainer) invitesContainer.style.display = 'block';
        if (tabOutgoing) tabOutgoing.className = 'flex-1 py-2 bg-blue-500 text-white';
        loadOutgoingInvites();
    }
}

function initDashboard() {
    // Setup modules
    setupContactsModule();
    setupInvitesModule();
    setupSearchModule();

    // Setup tab buttons
    const tabContacts = document.getElementById('tab-contacts');
    const tabIncoming = document.getElementById('tab-incoming');
    const tabOutgoing = document.getElementById('tab-outgoing');

    if (tabContacts) tabContacts.onclick = () => switchTab('contacts');
    if (tabIncoming) tabIncoming.onclick = () => switchTab('incoming');
    if (tabOutgoing) tabOutgoing.onclick = () => switchTab('outgoing');

    // Start with contacts tab
    switchTab('contacts');
}

// Initialize when DOM is ready
document.addEventListener('DOMContentLoaded', () => {
    const token = getToken();
    if (!token) {
        console.error('No token, redirecting to accounts');
        window.location.href = '/accounts';
        return;
    }
    initDashboard();
});
