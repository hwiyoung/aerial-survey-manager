/**
 * API Client for Aerial Survey Manager
 * Handles all communication with the backend
 */

const API_BASE = import.meta.env.VITE_API_URL || 'http://localhost:8000';
const TUS_URL = import.meta.env.VITE_TUS_URL || 'http://localhost:1080/files/';

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
            const error = await response.json().catch(() => ({}));
            throw new Error(error.detail || `Request failed: ${response.status}`);
        }

        return response.json();
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
        return this.request(`/projects/${projectId}`, { method: 'DELETE' });
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
    async startProcessing(projectId, options) {
        return this.request(`/processing/projects/${projectId}/start`, {
            method: 'POST',
            body: JSON.stringify(options),
        });
    }

    async getProcessingStatus(projectId) {
        return this.request(`/processing/projects/${projectId}/status`);
    }

    async cancelProcessing(projectId) {
        return this.request(`/processing/projects/${projectId}/cancel`, {
            method: 'POST',
        });
    }

    async getProcessingJobs() {
        return this.request('/processing/jobs');
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
}

export const api = new ApiClient();
export default api;
