/**
 * Main Web App JavaScript
 */

document.addEventListener('DOMContentLoaded', () => {
    initApp();
});

async function initApp() {
    setupSidebar();

    try {
        // Fetch current user details
        const response = await fetch('/api/user/me');
        if (!response.ok) {
            if (window.location.pathname !== '/login') {
                window.location.href = '/login';
            }
            return;
        }

        const data = await response.json();
        const user = data.user;

        renderUserSidebar(user);
        applyRoleRestrictions(user.role);
    } catch (e) {
        console.error('Error initializing app:', e);
    }
}

function renderUserSidebar(user) {
    const userContainer = document.getElementById('sidebarUser');
    if (!userContainer) return;

    // Clear skeletons
    userContainer.innerHTML = '';

    const initial = user.first_name ? user.first_name.charAt(0) : (user.username ? user.username.charAt(0) : '?');

    let avatarHtml = '';
    if (user.photo_url) {
        avatarHtml = `<img src="${user.photo_url}" class="user-avatar" alt="Avatar">`;
    } else {
        avatarHtml = `<div class="user-avatar-placeholder">${initial}</div>`;
    }

    const roleMap = {
        'admin': 'Администратор',
        'manager': 'Менеджер',
        'user': 'Сотрудник'
    };

    const displayRole = roleMap[user.role] || 'Сотрудник';
    const displayName = user.first_name ? `${user.first_name} ${user.last_name || ''}` : user.username;

    userContainer.innerHTML = `
        ${avatarHtml}
        <div class="user-details">
            <div class="user-name">${displayName}</div>
            <div class="user-role">${displayRole}</div>
        </div>
    `;
}

function applyRoleRestrictions(user) {
    const role = user.role;
    if (role === 'admin' || role === 'manager') {
        const adminElements = document.querySelectorAll('.admin-only');
        adminElements.forEach(el => {
            el.style.display = 'block'; // Or flex, depending on layout
            if (el.tagName === 'LI') {
                el.style.display = 'list-item';
            }
        });
    }

    if (user.is_superadmin) {
        const superadminElements = document.querySelectorAll('.superadmin-only');
        superadminElements.forEach(el => {
            el.style.display = 'block';
            if (el.tagName === 'LI') {
                el.style.display = 'list-item';
            }
        });
    }
}

function setupSidebar() {
    const openBtn = document.getElementById('openSidebarBtn');
    const closeBtn = document.getElementById('closeSidebarBtn');
    const sidebar = document.getElementById('sidebar');
    const overlay = document.getElementById('sidebarOverlay');

    if (!openBtn || !sidebar) return;

    const toggleMenu = () => {
        sidebar.classList.toggle('active');
        if (overlay) overlay.classList.toggle('active');
        document.body.classList.toggle('sidebar-open');
    };

    openBtn.addEventListener('click', toggleMenu);

    if (closeBtn) {
        closeBtn.addEventListener('click', toggleMenu);
    }

    if (overlay) {
        overlay.addEventListener('click', toggleMenu);
    }
}

/**
 * Utility: Show beautiful notification toast
 */
function showToast(message, type = 'success') {
    // Check if toast container exists
    let container = document.getElementById('toast-container');
    if (!container) {
        container = document.createElement('div');
        container.id = 'toast-container';
        document.body.appendChild(container);
    }

    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;

    const iconMap = {
        'success': 'check_circle',
        'error': 'error',
        'warning': 'warning',
        'info': 'info'
    };

    toast.innerHTML = `
        <span class="material-symbols-rounded toast-icon">${iconMap[type] || 'info'}</span>
        <span class="toast-message">${message}</span>
    `;

    container.appendChild(toast);

    // Animate in
    setTimeout(() => toast.classList.add('show'), 10);

    // Remove after 3 seconds
    setTimeout(() => {
        toast.classList.remove('show');
        setTimeout(() => toast.remove(), 300);
    }, 3000);
}
