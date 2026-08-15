/**
 * API Client for AlertFlow
 */

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

interface ApiOptions {
    method?: string;
    body?: any;
    token?: string;
}

async function apiRequest(endpoint: string, options: ApiOptions = {}) {
    const { method = 'GET', body, token } = options;

    const headers: Record<string, string> = {
        'Content-Type': 'application/json',
    };

    if (token && token !== 'cookie-session') {
        headers['Authorization'] = `Bearer ${token}`;
    }

    const response = await fetch(`${API_URL}/api${endpoint}`, {
        method,
        headers,
        body: body ? JSON.stringify(body) : undefined,
        credentials: 'include',
    });

    // Handle expired/invalid token — auto-redirect to login
    if (response.status === 401) {
        if (typeof window !== 'undefined') {
            localStorage.removeItem('alertflow_token');
            localStorage.removeItem('alertflow_user');
            window.location.href = '/en/login';
        }
        throw new Error('Session expired');
    }

    if (!response.ok) {
        const error = await response.json().catch(() => ({ detail: 'Request failed' }));
        throw new Error(error.detail || 'Request failed');
    }

    return response.json();
}


export const api = {
    // Auth
    login: async (username: string, password: string) => {
        const formData = new URLSearchParams();
        formData.append('username', username);
        formData.append('password', password);

        const response = await fetch(`${API_URL}/api/auth/login`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
            body: formData,
            credentials: 'include',
        });

        if (!response.ok) throw new Error('Login failed');
        return response.json();
    },
    logout: () => apiRequest('/auth/logout', { method: 'POST' }),
    // Health
    health: () => apiRequest('/health'),
    status: (token: string) => apiRequest('/status', { token }),
    metrics: (token: string) => apiRequest('/metrics', { token }),
    observabilityHealth: (token: string) => apiRequest('/observability-health', { token }),

    // Alerts
    alerts: (token: string, params?: { limit?: number; offset?: number; status?: string; severity?: string; q?: string }) => {
        const query = new URLSearchParams();
        if (params?.limit) query.set('limit', params.limit.toString());
        if (params?.offset) query.set('offset', params.offset.toString());
        if (params?.status) query.set('status', params.status);
        if (params?.severity) query.set('severity', params.severity);
        if (params?.q) query.set('q', params.q);
        return apiRequest(`/alerts?${query}`, { token });
    },
    alert: (token: string, id: string) => apiRequest(`/alerts/${id}`, { token }),
    alertTimeline: (token: string, id: string) => apiRequest(`/alerts/${id}/timeline`, { token }),
    alertOperations: (token: string, id: string) => apiRequest(`/alerts/${id}/operations`, { token }),
    updateAlertStatus: (token: string, id: string, status: string) =>
        apiRequest(`/alerts/${id}/status?status=${status}`, { method: 'PATCH', token }),
    rerunAI: (token: string, id: string) => apiRequest(`/alerts/${id}/rerun-ai`, { method: 'POST', token }),
    resendAlert: (token: string, id: string) => apiRequest(`/alerts/${id}/resend`, { method: 'POST', token }),
    forceSummary: (token: string) => apiRequest('/alerts/force-summary', { method: 'POST', token }),

    // Routing Rules
    routingRules: (token: string) => apiRequest('/routing-rules', { token }),
    createRoutingRule: (token: string, rule: any) => apiRequest('/routing-rules', { method: 'POST', body: rule, token }),
    updateRoutingRule: (token: string, id: string, rule: any) => apiRequest(`/routing-rules/${id}`, { method: 'PUT', body: rule, token }),
    deleteRoutingRule: (token: string, id: string) => apiRequest(`/routing-rules/${id}`, { method: 'DELETE', token }),
    resolutionProfiles: (token: string) => apiRequest('/resolution-profiles', { token }),
    createResolutionProfile: (token: string, profile: any) => apiRequest('/resolution-profiles', { method: 'POST', body: profile, token }),
    updateResolutionProfile: (token: string, id: string, profile: any) => apiRequest(`/resolution-profiles/${id}`, { method: 'PUT', body: profile, token }),
    deleteResolutionProfile: (token: string, id: string) => apiRequest(`/resolution-profiles/${id}`, { method: 'DELETE', token }),
    testRoutingMatch: (token: string, email: string, matchField: string = 'from') =>
        apiRequest('/routing-rules/test-match', { method: 'POST', body: { email_address: email, match_field: matchField }, token }),

    // Test Email
    sendTestEmail: (token: string, data: { from_email: string; to_email: string; subject: string; body: string }) =>
        apiRequest('/test-email', { method: 'POST', body: data, token }),
    previewRouting: (token: string, data: { from_email: string; to_email: string; subject: string; body: string }) =>
        apiRequest('/test-email/preview', { method: 'POST', body: data, token }),

    // Logs
    logs: (token: string, params?: { limit?: number; service?: string }) => {
        const query = new URLSearchParams();
        if (params?.limit) query.set('limit', params.limit.toString());
        if (params?.service) query.set('service', params.service);
        return apiRequest(`/logs?${query}`, { token });
    },
    searchLogs: (token: string, params?: { limit?: number; service?: string; level?: string; q?: string; sinceMinutes?: number }) => {
        const query = new URLSearchParams();
        if (params?.limit) query.set('limit', params.limit.toString());
        if (params?.service) query.set('service', params.service);
        if (params?.level) query.set('level', params.level);
        if (params?.q) query.set('q', params.q);
        if (params?.sinceMinutes) query.set('since_minutes', params.sinceMinutes.toString());
        return apiRequest(`/logs/search?${query}`, { token });
    },
    relayLogs: (token: string, limit: number = 100) => apiRequest(`/logs/relay?limit=${limit}`, { token }),

    // Integrations
    integrationSettings: (token: string) => apiRequest('/integrations/settings', { token }),
    updateIntegrationSettings: (token: string, settings: any) =>
        apiRequest('/integrations/settings', { method: 'PUT', body: settings, token }),
    testTelegram: (token: string) => apiRequest('/integrations/telegram/test', { method: 'POST', token }),
    testMatrix: (token: string) => apiRequest('/integrations/matrix/test', { method: 'POST', token }),

    // Mutes
    mutesFrom: (token: string) => apiRequest('/integrations/mutes/from', { token }),
    mutesDomain: (token: string) => apiRequest('/integrations/mutes/domain', { token }),
    addFromMute: (token: string, address: string) => apiRequest(`/integrations/mutes/from/${encodeURIComponent(address)}`, { method: 'POST', token }),
    removeFromMute: (token: string, address: string) => apiRequest(`/integrations/mutes/from/${encodeURIComponent(address)}`, { method: 'DELETE', token }),
    addDomainMute: (token: string, domain: string) => apiRequest(`/integrations/mutes/domain/${encodeURIComponent(domain)}`, { method: 'POST', token }),
    removeDomainMute: (token: string, domain: string) => apiRequest(`/integrations/mutes/domain/${encodeURIComponent(domain)}`, { method: 'DELETE', token }),

    // AI Providers
    aiProviders: (token: string) => apiRequest('/ai-providers', { token }),
    createAIProvider: (token: string, provider: any) => apiRequest('/ai-providers', { method: 'POST', body: provider, token }),
    updateAIProvider: (token: string, id: string, provider: any) => apiRequest(`/ai-providers/${id}`, { method: 'PUT', body: provider, token }),
    deleteAIProvider: (token: string, id: string) => apiRequest(`/ai-providers/${id}`, { method: 'DELETE', token }),
    testAIProvider: (token: string, id: string) => apiRequest(`/ai-providers/${id}/test`, { method: 'POST', token }),

    // Notification Channels
    notificationChannels: (token: string) => apiRequest('/notification-channels', { token }),
    createNotificationChannel: (token: string, channel: any) => apiRequest('/notification-channels', { method: 'POST', body: channel, token }),
    updateNotificationChannel: (token: string, id: string, channel: any) => apiRequest(`/notification-channels/${id}`, { method: 'PUT', body: channel, token }),
    deleteNotificationChannel: (token: string, id: string) => apiRequest(`/notification-channels/${id}`, { method: 'DELETE', token }),
    testNotificationChannel: (token: string, id: string) => apiRequest(`/notification-channels/${id}/test`, { method: 'POST', token }),
    notificationDestinations: (token: string) => apiRequest('/notification-channels/destinations/list', { token }),
    createNotificationDestination: (token: string, item: any) => apiRequest('/notification-channels/destinations', { method: 'POST', body: item, token }),
    updateNotificationDestination: (token: string, id: string, item: any) => apiRequest(`/notification-channels/destinations/${id}`, { method: 'PUT', body: item, token }),
    deleteNotificationDestination: (token: string, id: string) => apiRequest(`/notification-channels/destinations/${id}`, { method: 'DELETE', token }),

    // Settings
    getCurrentUser: (token: string) => apiRequest('/settings/me', { token }),
    changePassword: (token: string, currentPassword: string, newPassword: string) =>
        apiRequest('/settings/password', { method: 'PUT', body: { current_password: currentPassword, new_password: newPassword }, token }),
    adminChangePassword: (token: string, username: string, newPassword: string) =>
        apiRequest(`/settings/users/${username}/password`, { method: 'PUT', body: { new_password: newPassword }, token }),
    listUsers: (token: string) => apiRequest('/settings/users', { token }),
    getGeneralSettings: (token: string) => apiRequest('/settings/general', { token }),
    updateGeneralSettings: (token: string, settings: any) =>
        apiRequest('/settings/general', { method: 'PUT', body: settings, token }),

    // Queue Monitoring
    queueDlq: (token: string, limit: number = 50) => apiRequest(`/queue/dlq?limit=${limit}`, { token }),
    queueRetry: (token: string, limit: number = 50) => apiRequest(`/queue/retry?limit=${limit}`, { token }),
    queueFlushDlq: (token: string) => apiRequest('/queue/dlq/flush', { method: 'POST', token }),
    queueRequeueDlq: (token: string, index: number) => apiRequest(`/queue/dlq/${index}/requeue`, { method: 'POST', token }),

    // Analytics
    analytics: (token: string) => apiRequest('/analytics', { token }),
};
