/**
 * S3 Multipart Upload Service
 * High-performance direct upload to MinIO using presigned URLs
 */

const API_BASE = '/api/v1';

export class S3MultipartUploader {
    constructor(authToken) {
        this.authToken = authToken;
        this.activeUploads = new Map();
        this.speedTracker = new Map();
    }

    /**
     * Upload multiple files with parallel parts
     * @param {File[]} files - Array of files to upload
     * @param {string} projectId - Project ID
     * @param {Object} callbacks - Callback functions
     * @returns {Object} Controller with abort method (returned synchronously)
     */
    uploadFiles(files, projectId, {
        onFileProgress,
        onFileComplete,
        onAllComplete,
        onError,
        concurrency = 6,      // Files in parallel
        partConcurrency = 4,  // Parts per file in parallel
        partSize = 10 * 1024 * 1024,  // 10MB
        cameraModelName = null  // Camera model to link to images
    } = {}) {
        const abortController = { aborted: false };
        const fileArray = Array.from(files);

        // 컨트롤러를 동기적으로 반환하고, 실제 업로드는 비동기로 진행
        const controller = {
            abort: () => {
                abortController.aborted = true;
                this.activeUploads.forEach(ctrl => {
                    ctrl.abort?.();
                });
                this.activeUploads.clear();
            }
        };

        // 비동기 업로드 시작 (백그라운드에서 실행)
        this._startUpload(fileArray, projectId, {
            abortController,
            onFileProgress,
            onFileComplete,
            onAllComplete,
            onError,
            concurrency,
            partConcurrency,
            partSize,
            cameraModelName
        });

        return controller;
    }

    /**
     * Internal async upload method
     */
    async _startUpload(fileArray, projectId, {
        abortController,
        onFileProgress,
        onFileComplete,
        onAllComplete,
        onError,
        concurrency,
        partConcurrency,
        partSize,
        cameraModelName
    }) {
        try {
            // 1. Initialize all uploads at once (batch API call)
            const initResponse = await this.initMultipartUploads(projectId, fileArray, partSize, cameraModelName);

            if (!initResponse.uploads || initResponse.uploads.length === 0) {
                throw new Error('Failed to initialize uploads');
            }

            // 2. Upload files with controlled concurrency
            const results = [];
            let completedCount = 0;
            let activeCount = 0;
            let currentIndex = 0;

            const processNext = () => {
                return new Promise((resolve) => {
                    const checkComplete = () => {
                        if (completedCount === fileArray.length || abortController.aborted) {
                            resolve(results);
                            return true;
                        }
                        return false;
                    };

                    const uploadNext = async () => {
                        if (abortController.aborted || checkComplete()) return;

                        while (activeCount < concurrency && currentIndex < initResponse.uploads.length) {
                            if (abortController.aborted) break;

                            const index = currentIndex++;
                            const uploadInfo = initResponse.uploads[index];
                            const file = fileArray.find(f => f.name === uploadInfo.filename);

                            if (!file) {
                                completedCount++;
                                onError?.(index, uploadInfo.filename, new Error('File not found'));
                                continue;
                            }

                            activeCount++;

                            this.uploadSingleFile(file, uploadInfo, {
                                partConcurrency,
                                onProgress: (progress) => {
                                    onFileProgress?.(index, file.name, progress);
                                },
                                abortSignal: abortController
                            }).then((result) => {
                                activeCount--;
                                completedCount++;
                                results.push(result);
                                onFileComplete?.(index, file.name, result);
                                uploadNext();
                            }).catch((error) => {
                                activeCount--;
                                completedCount++;
                                // AbortError는 정상적인 취소이므로 에러로 처리하지 않음
                                if (error.name === 'AbortError' || abortController.aborted) {
                                    console.log(`Upload cancelled: ${file.name}`);
                                } else {
                                    onError?.(index, file.name, error);
                                }
                                uploadNext();
                            });
                        }

                        if (checkComplete()) return;
                    };

                    uploadNext();
                });
            };

            await processNext();

            // 3. Complete all uploads in batch
            if (!abortController.aborted && results.length > 0) {
                await this.completeMultipartUploads(projectId, results);
                onAllComplete?.();
            }

        } catch (error) {
            console.error('Upload initialization failed:', error);
            onError?.(0, 'initialization', error);
        }
    }

    /**
     * Upload a single file using multipart upload
     */
    async uploadSingleFile(file, uploadInfo, { partConcurrency, onProgress, abortSignal }) {
        const { parts, upload_id, object_key, filename } = uploadInfo;
        const completedParts = [];
        let uploadedBytes = 0;

        const uploadId = `${object_key}_${Date.now()}`;
        const abortController = new AbortController();
        this.activeUploads.set(uploadId, abortController);

        // Initialize speed tracking
        this.speedTracker.set(uploadId, {
            startTime: Date.now(),
            lastTime: Date.now(),
            lastBytes: 0,
            speed: 0
        });

        try {
            // Upload parts with controlled concurrency
            const queue = [...parts];
            const activePromises = new Set();

            const uploadPart = async (part) => {
                if (abortSignal?.aborted) {
                    throw new Error('Upload aborted');
                }

                const { part_number, presigned_url, start, end } = part;
                const chunk = file.slice(start, end + 1);

                // Local mode: API URLs need auth header
                const headers = presigned_url.startsWith('/api/')
                    ? { 'Authorization': `Bearer ${this.authToken}` }
                    : {};

                const response = await fetch(presigned_url, {
                    method: 'PUT',
                    body: chunk,
                    headers,
                    signal: abortController.signal
                });

                if (!response.ok) {
                    throw new Error(`Part ${part_number} failed: ${response.status}`);
                }

                // Local mode returns ETag in JSON body, S3 returns it in header
                let etag;
                if (presigned_url.startsWith('/api/')) {
                    const data = await response.json();
                    etag = data.etag;
                } else {
                    etag = response.headers.get('ETag');
                }
                uploadedBytes += chunk.size;

                // Calculate speed
                const tracker = this.speedTracker.get(uploadId);
                const now = Date.now();
                const timeDiff = (now - tracker.lastTime) / 1000;

                if (timeDiff >= 0.5) {
                    const bytesDiff = uploadedBytes - tracker.lastBytes;
                    tracker.speed = bytesDiff / timeDiff;
                    tracker.lastTime = now;
                    tracker.lastBytes = uploadedBytes;
                }

                const speed = tracker.speed;
                const remaining = file.size - uploadedBytes;
                const eta = speed > 0 ? Math.ceil(remaining / speed) : Infinity;

                onProgress?.({
                    bytesUploaded: uploadedBytes,
                    bytesTotal: file.size,
                    percentage: parseFloat((uploadedBytes / file.size * 100).toFixed(2)),
                    speed,
                    eta
                });

                return { part_number, etag };
            };

            // Process parts with concurrency control
            while (queue.length > 0 || activePromises.size > 0) {
                if (abortSignal?.aborted) {
                    throw new Error('Upload aborted');
                }

                // Start new uploads up to concurrency limit
                while (activePromises.size < partConcurrency && queue.length > 0) {
                    const part = queue.shift();
                    const promise = uploadPart(part)
                        .then(result => {
                            completedParts.push(result);
                            activePromises.delete(promise);
                            return result;
                        })
                        .catch(error => {
                            activePromises.delete(promise);
                            throw error;
                        });
                    activePromises.add(promise);
                }

                // Wait for at least one to complete
                if (activePromises.size > 0) {
                    await Promise.race(activePromises);
                }
            }

            return {
                filename,
                upload_id,
                object_key,
                parts: completedParts
            };

        } finally {
            this.activeUploads.delete(uploadId);
            this.speedTracker.delete(uploadId);
        }
    }

    /**
     * Initialize multipart uploads via backend API
     */
    async initMultipartUploads(projectId, files, partSize, cameraModelName = null) {
        const body = {
            files: files.map(f => ({
                filename: f.name,
                size: f.size,
                content_type: f.type || 'application/octet-stream'
            })),
            part_size: partSize
        };

        if (cameraModelName) {
            body.camera_model_name = cameraModelName;
        }

        const response = await fetch(`${API_BASE}/upload/projects/${projectId}/multipart/init`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${this.authToken}`
            },
            body: JSON.stringify(body)
        });

        if (!response.ok) {
            const error = await response.text();
            throw new Error(`Failed to initialize uploads: ${error}`);
        }

        return response.json();
    }

    /**
     * Complete multipart uploads via backend API
     */
    async completeMultipartUploads(projectId, uploads) {
        const response = await fetch(`${API_BASE}/upload/projects/${projectId}/multipart/complete`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${this.authToken}`
            },
            body: JSON.stringify({ uploads })
        });

        if (!response.ok) {
            const error = await response.text();
            throw new Error(`Failed to complete uploads: ${error}`);
        }

        return response.json();
    }

    /**
     * Abort multipart uploads via backend API
     */
    async abortMultipartUploads(projectId, uploads) {
        const response = await fetch(`${API_BASE}/upload/projects/${projectId}/multipart/abort`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${this.authToken}`
            },
            body: JSON.stringify({ uploads })
        });

        if (!response.ok) {
            console.error('Failed to abort uploads');
        }

        return response.json();
    }

    /**
     * Format bytes to human readable string
     */
    static formatBytes(bytes) {
        if (bytes === 0) return '0 B';
        const k = 1024;
        const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
        const i = Math.floor(Math.log(bytes) / Math.log(k));
        return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
    }

    /**
     * Format speed to human readable string
     */
    static formatSpeed(bytesPerSecond) {
        return this.formatBytes(bytesPerSecond) + '/s';
    }

    /**
     * Format ETA to human readable string
     */
    static formatETA(seconds) {
        if (!isFinite(seconds)) return '--:--';
        const h = Math.floor(seconds / 3600);
        const m = Math.floor((seconds % 3600) / 60);
        const s = Math.floor(seconds % 60);
        if (h > 0) return `${h}:${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;
        return `${m}:${s.toString().padStart(2, '0')}`;
    }
}

export default S3MultipartUploader;
