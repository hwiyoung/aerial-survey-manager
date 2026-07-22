/**
 * API Client for Aerial Survey Manager
 * Handles all communication with the backend
 */

const API_BASE = import.meta.env.VITE_API_URL || '';

const CLIENT_ERROR_SPECS = {
    AUTH_INVALID_CREDENTIALS: {
        message: '로그인 정보를 확인할 수 없습니다.',
        action: '계정과 비밀번호를 확인해주세요.',
        retryable: true,
    },
    AUTH_SESSION_EXPIRED: {
        message: '로그인 시간이 만료되었습니다.',
        action: '다시 로그인해주세요.',
        retryable: true,
    },
    AUTH_ACCESS_DENIED: {
        message: '이 작업을 수행할 수 없습니다.',
        action: '로그인 상태를 확인한 뒤 다시 시도해주세요.',
        retryable: false,
    },
    REQUEST_INVALID: {
        message: '요청 내용을 처리할 수 없습니다.',
        action: '입력값을 확인해주세요.',
        retryable: false,
    },
    RESOURCE_NOT_FOUND: {
        message: '요청한 항목을 찾을 수 없습니다.',
        action: '목록을 새로고침하고 대상을 다시 선택해주세요.',
        retryable: false,
    },
    RESOURCE_STATE_CONFLICT: {
        message: '현재 상태에서는 이 작업을 수행할 수 없습니다.',
        action: '최신 상태를 확인한 뒤 다시 시도해주세요.',
        retryable: true,
    },
    NETWORK_OFFLINE: {
        message: '네트워크에 연결되어 있지 않습니다.',
        action: '연결 상태를 확인해주세요.',
        retryable: true,
    },
    SERVER_UNAVAILABLE: {
        message: '서버에 연결할 수 없습니다.',
        action: '잠시 후 새로고침해주세요.',
        retryable: true,
    },
    INTERNAL_ERROR: {
        message: '시스템 내부 오류가 발생했습니다.',
        action: '오류 참조번호를 운영 담당자에게 전달해주세요.',
        retryable: false,
    },
};

function fallbackCodeForStatus(status, endpoint = '') {
    if (status === 401) {
        return endpoint.includes('/auth/login') ? 'AUTH_INVALID_CREDENTIALS' : 'AUTH_SESSION_EXPIRED';
    }
    if (status === 403) return 'AUTH_ACCESS_DENIED';
    if (status === 404) return 'RESOURCE_NOT_FOUND';
    if (status === 409) return 'RESOURCE_STATE_CONFLICT';
    if (status >= 500) return status === 503 ? 'SERVER_UNAVAILABLE' : 'INTERNAL_ERROR';
    return 'REQUEST_INVALID';
}

function createUserError(publicError, status = 0, context = {}) {
    const fallback = CLIENT_ERROR_SPECS[publicError?.code] || CLIENT_ERROR_SPECS.INTERNAL_ERROR;
    const error = new Error(publicError?.message || fallback.message);
    error.name = 'ApiError';
    error.status = status;
    error.code = publicError?.code || 'INTERNAL_ERROR';
    error.summary = publicError?.message || fallback.message;
    error.action = publicError?.action || fallback.action;
    error.referenceId = publicError?.reference_id || null;
    error.retryable = publicError?.retryable ?? fallback.retryable;
    error.data = {
        ...context,
        code: error.code,
        message: error.summary,
        action: error.action,
        reference_id: error.referenceId,
        retryable: error.retryable,
    };
    return error;
}

function createNetworkError(cause) {
    const offline = typeof navigator !== 'undefined' && navigator.onLine === false;
    const code = offline ? 'NETWORK_OFFLINE' : 'SERVER_UNAVAILABLE';
    const error = createUserError({ code, ...CLIENT_ERROR_SPECS[code] });
    error.cause = cause;
    return error;
}

async function parseErrorResponse(response, endpoint = '') {
    const body = await response.json().catch(() => ({}));
    const candidate = body?.error;
    const fallbackCode = fallbackCodeForStatus(response.status, endpoint);
    const fallback = CLIENT_ERROR_SPECS[fallbackCode] || CLIENT_ERROR_SPECS.INTERNAL_ERROR;
    const referenceId = candidate?.reference_id || response.headers.get('X-Error-Reference');
    return createUserError(
        candidate?.code
            ? { ...fallback, ...candidate, reference_id: referenceId }
            : { code: fallbackCode, ...fallback, reference_id: referenceId },
        response.status,
        body?.context || {},
    );
}

export function formatUserError(error, fallback = '요청을 처리하지 못했습니다.') {
    const message = error?.summary || error?.message || fallback;
    const parts = [message];
    if (error?.action && error.action !== message) parts.push(error.action);
    if (error?.referenceId) parts.push(`오류 참조번호: ${error.referenceId}`);
    return parts.join('\n');
}

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

        let response;
        try {
            response = await fetch(url, {
                ...options,
                headers,
            });
        } catch (cause) {
            if (cause?.name === 'AbortError') throw cause;
            throw createNetworkError(cause);
        }

        // Handle token refresh on 401
        if (response.status === 401 && this.refreshToken) {
            const refreshed = await this.refreshAccessToken();
            if (refreshed) {
                headers['Authorization'] = `Bearer ${this.token}`;
                try {
                    response = await fetch(url, { ...options, headers });
                } catch (cause) {
                    if (cause?.name === 'AbortError') throw cause;
                    throw createNetworkError(cause);
                }
            }
        }

        if (!response.ok) {
            throw await parseErrorResponse(response, endpoint);
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
        const endpoint = '/auth/login';
        let response;
        try {
            response = await fetch(`${API_BASE}/api/v1${endpoint}`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ email, password }),
            });
        } catch (cause) {
            throw createNetworkError(cause);
        }

        if (!response.ok) {
            throw await parseErrorResponse(response, endpoint);
        }

        const data = await response.json();
        this.setTokens(data.access_token, data.refresh_token);
        return data;
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

    async deleteSourceImages(projectId) {
        return this.request(`/projects/${projectId}/source-images`, { method: 'DELETE' });
    }

    async deleteOrthoCog(projectId) {
        return this.request(`/projects/${projectId}/ortho/cog`, { method: 'DELETE' });
    }

    // --- Images ---
    async getProjectImages(projectId) {
        return this.request(`/upload/projects/${projectId}/images`);
    }

    async getImage(imageId) {
        return this.request(`/upload/images/${imageId}`);
    }

    async regenerateThumbnail(imageId) {
        return this.request(`/upload/images/${imageId}/regenerate-thumbnail`, { method: 'POST' });
    }

    // --- Local Import ---
    async localImport(projectId, sourceDir, filePaths = null, cameraModelId = null) {
        const body = { source_dir: sourceDir };
        if (filePaths && filePaths.length > 0) {
            body.file_paths = filePaths;
        }
        if (cameraModelId) {
            body.camera_model_id = cameraModelId;
        }
        return this.request(`/upload/projects/${projectId}/local-import`, {
            method: 'POST',
            body: JSON.stringify(body),
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

    async reserveCrsCorrection(projectId, sourceCrs) {
        return this.request(`/processing/projects/${projectId}/crs-correction`, {
            method: 'POST',
            body: JSON.stringify({ source_crs: sourceCrs }),
        });
    }

    async cancelCrsCorrection(projectId) {
        return this.request(`/processing/projects/${projectId}/crs-correction`, {
            method: 'DELETE',
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
        const httpBase = API_BASE || window.location.origin;
        const wsBase = httpBase.replace(/^http/, 'ws').replace(/\/$/, '');
        const token = this.token || localStorage.getItem('access_token');
        const tokenQuery = token ? `?token=${encodeURIComponent(token)}` : '';
        const wsUrl = `${wsBase}/api/v1/processing/ws/projects/${projectId}/status${tokenQuery}`;
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

    // --- Filesystem Browser ---
    async getFilesystemRoots() {
        return this.request('/filesystem/roots');
    }

    async browseFilesystem(path = '/', fileTypes = 'images') {
        return this.request(`/filesystem/browse?path=${encodeURIComponent(path)}&file_types=${encodeURIComponent(fileTypes)}`);
    }

    async readTextFile(path) {
        return this.request(`/filesystem/read-text?path=${encodeURIComponent(path)}`);
    }

    async getImagePreview(path) {
        return this.request('/filesystem/image-preview', {
            method: 'POST',
            body: JSON.stringify({ path }),
        });
    }

    // --- Camera Models ---
    async getCameraModels() {
        return this.request('/camera-models');
    }

    async getCameraIoConfig() {
        return this.request('/camera-models/io-config');
    }

    async updateCameraIoConfig(content, expectedSha256) {
        return this.request('/camera-models/io-config', {
            method: 'PUT',
            body: JSON.stringify({ content, expected_sha256: expectedSha256 }),
        });
    }

    async createCameraModel(data) {
        return this.request('/camera-models', {
            method: 'POST',
            body: JSON.stringify(data),
        });
    }

    async updateCameraModel(cameraId, data) {
        return this.request(`/camera-models/${cameraId}`, {
            method: 'PUT',
            body: JSON.stringify(data),
        });
    }

    async deleteCameraModel(cameraId) {
        return this.request(`/camera-models/${cameraId}`, {
            method: 'DELETE',
        });
    }

    /**
     * Upload EO data file for a project
     */
    async uploadEoData(projectId, file, config = {}) {
        const formData = new FormData();
        const files = Array.isArray(file) ? file : [file];
        files.forEach((item) => formData.append('files', item));
        formData.append('config', JSON.stringify(config));

        return this.request(`/projects/${projectId}/eo`, {
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

    async deleteGroup(groupId) {
        return this.request(`/groups/${groupId}`, { method: 'DELETE' });
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

    async getSystemResources() {
        return this.request(`/system/resources?t=${Date.now()}`, {
            cache: 'no-store',
            headers: {
                'Cache-Control': 'no-store',
            },
        });
    }

    // --- 도엽 (Map Sheets) ---
    async getSheetScales() {
        return this.request('/sheets/scales');
    }

    async getSheets(scale, bounds) {
        const b = `${bounds.minlat},${bounds.minlon},${bounds.maxlat},${bounds.maxlon}`;
        return this.request(`/sheets?scale=${scale}&bounds=${encodeURIComponent(b)}`);
    }

    async searchSheet(mapid) {
        return this.request(`/sheets/search?mapid=${encodeURIComponent(mapid)}`);
    }

    async clipExport(projectIds, sheetIds, options = {}) {
        return this.request('/download/clip', {
            method: 'POST',
            body: JSON.stringify({
                project_ids: projectIds,
                sheet_ids: sheetIds,
                scale: options.scale || 5000,
                format: options.format || 'GeoTiff',
                crs: options.crs || 'EPSG:5186',
                gsd: options.gsd ? parseFloat(options.gsd) : null,
                custom_filename: options.custom_filename || null,
            }),
        });
    }

    async getClipExportJob(jobId) {
        return this.request(`/download/clip/jobs/${jobId}`);
    }

    async getClipExportHistory(limit = 10) {
        return this.request(`/download/clip/jobs?limit=${encodeURIComponent(limit)}`);
    }

    async cancelClipExport(jobId) {
        return this.request(`/download/clip/jobs/${jobId}/cancel`, { method: 'POST' });
    }

    async prepareClipExportDownload(jobId) {
        return this.request(`/download/clip/jobs/${jobId}/download`, { method: 'POST' });
    }

    async mergeExport(projectIds, sheetId, options = {}) {
        return this.request('/download/merge', {
            method: 'POST',
            body: JSON.stringify({
                project_ids: projectIds,
                sheet_id: sheetId,
                scale: options.scale || 5000,
                crs: options.crs || 'EPSG:5186',
                gsd: options.gsd ? parseFloat(options.gsd) : null,
            }),
        });
    }

    // --- COG/Orthoimage ---
    async getCogUrl(projectId) {
        return this.request(`/download/projects/${projectId}/cog-url`);
    }

    /**
     * 파일 준비 후 다운로드 ID 반환 (대용량 파일용)
     * @param {string[]} projectIds - 프로젝트 ID 배열
     * @param {object} options - 내보내기 옵션
     * @returns {Promise<{download_id: string, filename: string, file_size: number}>}
     */
    async prepareBatchExport(projectIds, options = {}, signal) {
        return this.request('/download/batch/prepare', {
            method: 'POST',
            body: JSON.stringify({
                project_ids: projectIds,
                format: options.format || 'GeoTiff',
                crs: options.crs || 'EPSG:5186',
                gsd: options.gsd ? parseFloat(options.gsd) : null,
                custom_filename: options.custom_filename || null,
            }),
            signal,
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
