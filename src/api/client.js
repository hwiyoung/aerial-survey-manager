/**
 * API Client for Aerial Survey Manager
 * Handles all communication with the backend
 */

const API_BASE = import.meta.env.VITE_API_URL || '';

// Use configured TUS URL or dynamically build from current origin
// This ensures the request goes to the correct port (e.g., :8081 in nginx proxy)
const getTusUrl = () => {
    const configured = import.meta.env.VITE_TUS_URL;
    if (configured && configured.startsWith('http')) {
        return configured;
    }
    // Use relative path from current origin (preserves port like :8081)
    return `${window.location.origin}${configured || '/files/'}`;
};
const TUS_URL = getTusUrl();

class ApiClient {
    constructor() {
        this.token = localStorage.getItem('access_token');
        this.refreshToken = localStorage.getItem('refresh_token');
    }

    // --- Auth ---
    setTokens(accessToken, refreshToken) {
        this.token = accessToken;
        this.refreshToken = refreshToken;
        localStorage.setItem('access_token', accessToken);
        localStorage.setItem('refresh_token', refreshToken);
    }

    clearTokens() {
        this.token = null;
        this.refreshToken = null;
        localStorage.removeItem('access_token');
        localStorage.removeItem('refresh_token');
    }

    async request(endpoint, options = {}) {
        const url = `${API_BASE}/api/v1${endpoint}`;
        const headers = {
            'Content-Type': 'application/json',
            ...options.headers,
        };

        // If body is FormData, delete Content-Type to let browser set boundary
        if (options.body instanceof FormData) {
            delete headers['Content-Type'];
        }

        if (this.token) {
            headers['Authorization'] = `Bearer ${this.token}`;
        }

        const response = await fetch(url, {
            ...options,
            headers,
        });

        // Handle token refresh on 401
        if (response.status === 401 && this.refreshToken) {
            const refreshed = await this.refreshAccessToken();
            if (refreshed) {
                headers['Authorization'] = `Bearer ${this.token}`;
                return fetch(url, { ...options, headers });
            }
        }

        if (!response.ok) {
            const errorData = await response.json().catch(() => ({}));
            const error = new Error(
                typeof errorData.detail === 'string'
                    ? errorData.detail
                    : errorData.detail?.message || `Request failed: ${response.status}`
            );
            error.status = response.status;
            error.data = errorData.detail;
            throw error;
        }

        if (response.status === 204) {
            return null;
        }

        const text = await response.text();
        return text ? JSON.parse(text) : {};

    }

    async refreshAccessToken() {
        try {
            const response = await fetch(`${API_BASE}/api/v1/auth/refresh`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ refresh_token: this.refreshToken }),
            });

            if (response.ok) {
                const data = await response.json();
                this.setTokens(data.access_token, data.refresh_token);
                return true;
            }
        } catch (e) {
            console.error('Token refresh failed:', e);
        }
        this.clearTokens();
        return false;
    }

    // --- Authentication ---
    async login(email, password) {
        const response = await fetch(`${API_BASE}/api/v1/auth/login`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ email, password }),
        });

        if (!response.ok) {
            const error = await response.json().catch(() => ({}));
            throw new Error(error.detail || 'Login failed');
        }

        const data = await response.json();
        this.setTokens(data.access_token, data.refresh_token);
        return data;
    }

    async register(email, password, name) {
        const response = await fetch(`${API_BASE}/api/v1/auth/register`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ email, password, name }),
        });

        if (!response.ok) {
            const error = await response.json().catch(() => ({}));
            throw new Error(error.detail || 'Registration failed');
        }

        return response.json();
    }

    async logout() {
        try {
            await this.request('/auth/logout', { method: 'POST' });
        } finally {
            this.clearTokens();
        }
    }

    async getCurrentUser() {
        return this.request('/auth/me');
    }

    // --- User & Organization Management (Admin) ---
    async getUsers(params = {}) {
        const query = new URLSearchParams(params).toString();
        return this.request(`/users${query ? `?${query}` : ''}`);
    }

    async createUser(data) {
        return this.request('/users', {
            method: 'POST',
            body: JSON.stringify(data),
        });
    }

    async inviteUser(data) {
        return this.request('/users/invite', {
            method: 'POST',
            body: JSON.stringify(data),
        });
    }

    async transferUser(userId, data) {
        return this.request(`/users/${userId}/transfer`, {
            method: 'POST',
            body: JSON.stringify(data),
        });
    }

    async updateUser(userId, data) {
        return this.request(`/users/${userId}`, {
            method: 'PATCH',
            body: JSON.stringify(data),
        });
    }

    async deactivateUser(userId) {
        return this.request(`/users/${userId}`, {
            method: 'DELETE',
        });
    }

    async deleteUser(userId) {
        return this.request(`/users/${userId}/permanent`, {
            method: 'DELETE',
        });
    }

    async getOrganizations() {
        return this.request('/organizations');
    }

    async createOrganization(data) {
        return this.request('/organizations', {
            method: 'POST',
            body: JSON.stringify(data),
        });
    }

    async updateOrganization(organizationId, data) {
        return this.request(`/organizations/${organizationId}`, {
            method: 'PATCH',
            body: JSON.stringify(data),
        });
    }

    async deleteOrganization(organizationId, force = false) {
        return this.request(`/organizations/${organizationId}?force=${force ? 'true' : 'false'}`, {
            method: 'DELETE',
        });
    }

    async getPermissionCatalog() {
        return this.request('/permissions/roles');
    }

    async getProjectPermissions(projectId) {
        return this.request(`/permissions/projects/${projectId}`);
    }

    async setProjectPermission(projectId, userId, data) {
        return this.request(`/permissions/projects/${projectId}/users/${userId}`, {
            method: 'PUT',
            body: JSON.stringify(data),
        });
    }

    async removeProjectPermission(projectId, userId) {
        return this.request(`/permissions/projects/${projectId}/users/${userId}`, {
            method: 'DELETE',
        });
    }

    // --- Projects ---
    async getProjects(params = {}) {
        const query = new URLSearchParams(params).toString();
        return this.request(`/projects${query ? `?${query}` : ''}`);
    }

    async getProject(projectId) {
        return this.request(`/projects/${projectId}`);
    }

    async createProject(data) {
        return this.request('/projects', {
            method: 'POST',
            body: JSON.stringify(data),
        });
    }

    async updateProject(projectId, data) {
        return this.request(`/projects/${projectId}`, {
            method: 'PATCH',
            body: JSON.stringify(data),
        });
    }

    async deleteProject(projectId) {
        return this.batchDeleteProjects([projectId]);
    }

    async batchProjects(payload) {
        return this.request('/projects/batch', {
            method: 'POST',
            body: JSON.stringify(payload),
        });
    }

    async batchDeleteProjects(projectIds) {
        return this.batchProjects({
            action: 'delete',
            project_ids: projectIds,
        });
    }

    async batchUpdateProjectStatus(projectIds, status) {
        return this.batchProjects({
            action: 'update_status',
            project_ids: projectIds,
            status,
        });
    }

    async deleteSourceImages(projectId) {
        return this.request(`/projects/${projectId}/source-images`, { method: 'DELETE' });
    }

    // --- Images ---
    async getProjectImages(projectId) {
        return this.request(`/upload/projects/${projectId}/images`);
    }

    async initImageUpload(projectId, filename, fileSize) {
        return this.request(`/upload/projects/${projectId}/images/init?filename=${encodeURIComponent(filename)}&file_size=${fileSize}`, {
            method: 'POST',
        });
    }

    // --- Processing ---
    async startProcessing(projectId, options, force = false, forceRestart = false) {
        const params = new URLSearchParams();
        if (force) params.append('force', 'true');
        if (forceRestart) params.append('force_restart', 'true');
        const queryString = params.toString();
        const url = `/processing/projects/${projectId}/start${queryString ? `?${queryString}` : ''}`;
        return this.request(url, {
            method: 'POST',
            body: JSON.stringify(options),
        });
    }

    async getProcessingEngines() {
        return this.request('/processing/engines');
    }

    async getProcessingStatus(projectId) {
        return this.request(`/processing/projects/${projectId}/status`);
    }

    async cancelProcessing(projectId) {
        return this.request(`/processing/projects/${projectId}/cancel`, {
            method: 'POST',
        });
    }

    async scheduleProcessing(projectId, options) {
        return this.request(`/processing/projects/${projectId}/schedule`, {
            method: 'POST',
            body: JSON.stringify(options),
        });
    }

    async getProcessingJobs() {
        return this.request('/processing/jobs');
    }

    async getProcessingMetrics() {
        return this.request('/processing/metrics');
    }

    // --- Download ---
    getDownloadUrl(projectId) {
        return `${API_BASE}/api/v1/download/projects/${projectId}/ortho`;
    }

    // --- WebSocket ---
    connectStatusWebSocket(projectId, onMessage) {
        const wsUrl = `${API_BASE.replace('http', 'ws')}/api/v1/processing/ws/projects/${projectId}/status`;
        const ws = new WebSocket(wsUrl);

        ws.onopen = () => {
            console.log('WebSocket connected');
        };

        ws.onmessage = (event) => {
            const data = JSON.parse(event.data);
            onMessage(data);
        };

        ws.onerror = (error) => {
            console.error('WebSocket error:', error);
        };

        ws.onclose = () => {
            console.log('WebSocket closed');
        };

        // Ping to keep connection alive
        const pingInterval = setInterval(() => {
            if (ws.readyState === WebSocket.OPEN) {
                ws.send('ping');
            }
        }, 30000);

        return {
            close: () => {
                clearInterval(pingInterval);
                ws.close();
            },
        };
    }

    // --- Camera Models ---
    async getCameraModels() {
        return this.request('/camera-models');
    }

    async createCameraModel(data) {
        return this.request('/camera-models', {
            method: 'POST',
            body: JSON.stringify(data),
        });
    }

    /**
     * Upload EO data file for a project
     */
    async uploadEoData(projectId, file, config = {}) {
        const formData = new FormData();
        formData.append('file', file);

        return this.request(`/projects/${projectId}/eo?config=${encodeURIComponent(JSON.stringify(config))}`, {
            method: 'POST',
            body: formData,
        });
    }

    // --- Processing Presets ---
    async getPresets() {
        return this.request('/presets');
    }

    async getDefaultPresets() {
        return this.request('/presets/defaults');
    }

    async createPreset(data) {
        return this.request('/presets', {
            method: 'POST',
            body: JSON.stringify(data),
        });
    }

    async updatePreset(presetId, data) {
        return this.request(`/presets/${presetId}`, {
            method: 'PATCH',
            body: JSON.stringify(data),
        });
    }

    async deletePreset(presetId) {
        return this.request(`/presets/${presetId}`, { method: 'DELETE' });
    }

    // --- Project Groups ---
    async getGroups(flat = false) {
        return this.request(`/groups?flat=${flat}`);
    }

    async createGroup(data) {
        return this.request('/groups', {
            method: 'POST',
            body: JSON.stringify(data),
        });
    }

    async updateGroup(groupId, data) {
        return this.request(`/groups/${groupId}`, {
            method: 'PATCH',
            body: JSON.stringify(data),
        });
    }

    async deleteGroup(groupId, mode = 'keep') {
        return this.request(`/groups/${groupId}?mode=${mode}`, { method: 'DELETE' });
    }

    async moveProjectToGroup(projectId, groupId) {
        return this.updateProject(projectId, { group_id: groupId });
    }

    // --- Statistics ---
    async getMonthlyStats(year = null) {
        const query = year ? `?year=${year}` : '';
        return this.request(`/projects/stats/monthly${query}`);
    }

    async getRegionalStats() {
        return this.request('/projects/stats/regional');
    }

    async getStorageStats(refresh = false) {
        const query = refresh ? '?refresh=true' : '';
        return this.request(`/projects/stats/storage${query}`);
    }

    // --- COG/Orthoimage ---
    async getCogUrl(projectId) {
        return this.request(`/download/projects/${projectId}/cog-url`);
    }

    /**
     * Batch export multiple project orthoimages as a ZIP file (legacy - uses blob)
     * @param {string[]} projectIds - Array of project IDs to export
     * @param {object} options - Export options (format, crs)
     * @returns {Promise<Blob>} - ZIP file blob for download
     */
    async batchExport(projectIds, options = {}) {
        const url = `${API_BASE}/api/v1/download/batch`;
        const headers = {
            'Content-Type': 'application/json',
        };

        if (this.token) {
            headers['Authorization'] = `Bearer ${this.token}`;
        }

        const response = await fetch(url, {
            method: 'POST',
            headers,
            body: JSON.stringify({
                project_ids: projectIds,
                format: options.format || 'GeoTiff',
                crs: options.crs || 'EPSG:5186',
                gsd: options.gsd ? parseFloat(options.gsd) : null,
                custom_filename: options.custom_filename || null,
            }),
        });

        if (!response.ok) {
            const error = await response.json().catch(() => ({}));
            throw new Error(error.detail || `Batch export failed: ${response.status}`);
        }

        return response.blob();
    }

    /**
     * 파일 준비 후 다운로드 ID 반환 (대용량 파일용)
     * @param {string[]} projectIds - 프로젝트 ID 배열
     * @param {object} options - 내보내기 옵션
     * @returns {Promise<{download_id: string, filename: string, file_size: number}>}
     */
    async prepareBatchExport(projectIds, options = {}) {
        return this.request('/download/batch/prepare', {
            method: 'POST',
            body: JSON.stringify({
                project_ids: projectIds,
                format: options.format || 'GeoTiff',
                crs: options.crs || 'EPSG:5186',
                gsd: options.gsd ? parseFloat(options.gsd) : null,
                custom_filename: options.custom_filename || null,
            }),
        });
    }

    /**
     * 준비된 파일 직접 다운로드 URL 반환
     * @param {string} downloadId - 다운로드 ID
     * @returns {string} - 다운로드 URL
     */
    getBatchDownloadUrl(downloadId) {
        return `${API_BASE}/api/v1/download/batch/${downloadId}`;
    }

    /**
     * 직접 다운로드 트리거 (브라우저 메모리 사용 안함)
     * @param {string} downloadId - 다운로드 ID
     */
    triggerDirectDownload(downloadId) {
        // anchor 태그로 직접 다운로드 (인증 불필요 - download_id가 임시 토큰 역할)
        const a = document.createElement('a');
        a.href = this.getBatchDownloadUrl(downloadId);
        a.style.display = 'none';
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
    }

    /**
     * Download a blob as a file
     * @param {Blob} blob - The blob to download
     * @param {string} filename - Suggested filename
     */
    downloadBlob(blob, filename) {
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = filename;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        window.URL.revokeObjectURL(url);
    }
}

export const api = new ApiClient();
export default api;
