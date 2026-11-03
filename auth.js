/* Shared authenticated API helper for the browser clients. */
(function () {
    function clearSessionAndRedirect() {
        localStorage.removeItem('user');
        localStorage.removeItem('auth_token');
        if (window.location.pathname !== '/login') {
            window.location.href = '/login';
        }
    }

    function authHeaders(extraHeaders) {
        const token = localStorage.getItem('auth_token');
        return {
            ...(extraHeaders || {}),
            ...(token ? { Authorization: `Bearer ${token}` } : {})
        };
    }

    async function apiFetch(url, options) {
        const requestOptions = options ? { ...options } : {};
        requestOptions.headers = authHeaders(requestOptions.headers);
        const response = await fetch(url, requestOptions);
        if (response.status === 401) {
            clearSessionAndRedirect();
        }
        return response;
    }

    function clearStoredSession() {
        localStorage.removeItem('user');
        localStorage.removeItem('auth_token');
        localStorage.removeItem('chat_sessions');
    }

    async function changePassword(currentPassword, newPassword, confirmPassword) {
        const response = await apiFetch('/api/change-password', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                current_password: currentPassword,
                new_password: newPassword,
                confirm_password: confirmPassword
            })
        });
        return { response, result: await response.json().catch(() => ({})) };
    }

    async function deleteAccount(currentPassword) {
        const response = await apiFetch('/api/account', {
            method: 'DELETE',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ current_password: currentPassword })
        });
        return { response, result: await response.json().catch(() => ({})) };
    }

    window.authHeaders = authHeaders;
    window.apiFetch = apiFetch;
    window.clearSessionAndRedirect = clearSessionAndRedirect;
    window.clearStoredSession = clearStoredSession;
    window.changePassword = changePassword;
    window.deleteAccount = deleteAccount;
})();