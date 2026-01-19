/**
 * Resumable Upload Service using tus protocol
 * Handles large file uploads with automatic resume capability
 */

import * as tus from 'tus-js-client';

// Use configured TUS URL or dynamically build from current origin
// This ensures the request goes to the correct port (e.g., :8081 in nginx proxy)
const getBaseUrl = () => {
    const configured = import.meta.env.VITE_TUS_URL;
    if (configured && configured.startsWith('http')) {
        return configured;
    }
    // Use relative path from current origin (preserves port like :8081)
    return `${window.location.origin}${configured || '/files/'}`;
};
const TUS_URL = getBaseUrl();

export class ResumableUploader {
    constructor(authToken) {
        this.authToken = authToken;
        this.uploads = new Map(); // Track active uploads
    }

    /**
     * Upload a file with resumable support
     * @param {File} file - File to upload
     * @param {string} projectId - Project ID
     * @param {Object} callbacks - Callback functions
     * @returns {Object} Upload controller with pause/resume/abort methods
     */
    uploadFile(file, projectId, { onProgress, onError, onSuccess }) {
        const uploadKey = `${projectId}_${file.name}`;

        const upload = new tus.Upload(file, {
            endpoint: TUS_URL,
            retryDelays: [0, 1000, 3000, 5000, 10000, 20000],
            chunkSize: 50 * 1024 * 1024, // 50MB for better throughput on large files
            parallelUploads: 1, // Single stream per file for maximum stability over proxy

            metadata: {
                filename: file.name,
                filetype: file.type,
                projectId: projectId,
            },

            headers: {
                'Authorization': `Bearer ${this.authToken}`,
            },

            onProgress: (bytesUploaded, bytesTotal) => {
                const percentage = ((bytesUploaded / bytesTotal) * 100).toFixed(2);
                const speed = this.calculateSpeed(uploadKey, bytesUploaded);
                const eta = this.calculateETA(bytesUploaded, bytesTotal, speed);

                onProgress?.({
                    bytesUploaded,
                    bytesTotal,
                    percentage: parseFloat(percentage),
                    speed,
                    eta,
                });
            },

            onError: (error) => {
                console.error('Upload error:', error);

                // Save upload URL for resume
                if (upload.url) {
                    localStorage.setItem(`upload_${uploadKey}`, JSON.stringify({
                        url: upload.url,
                        timestamp: Date.now(),
                        filename: file.name,
                        size: file.size,
                    }));
                }

                onError?.(error);
            },

            onSuccess: () => {
                // Clear saved upload
                localStorage.removeItem(`upload_${uploadKey}`);
                this.uploads.delete(uploadKey);

                onSuccess?.({
                    uploadId: upload.url?.split('/').pop(),
                    filename: file.name,
                });
            },

            onShouldRetry: (err, retryAttempt, options) => {
                // Retry on network errors
                const status = err.originalResponse?.getStatus();
                if (status === 409 || status === 423) {
                    // Conflict or Locked - don't retry
                    return false;
                }
                // Retry on other errors up to 10 times
                return retryAttempt < 10;
            },
        });

        // Check for previous upload to resume
        const saved = localStorage.getItem(`upload_${uploadKey}`);
        if (saved) {
            try {
                const { url, timestamp } = JSON.parse(saved);
                // Only resume if less than 24 hours old
                if (Date.now() - timestamp < 24 * 60 * 60 * 1000) {
                    upload.url = url;
                } else {
                    localStorage.removeItem(`upload_${uploadKey}`);
                }
            } catch (e) {
                localStorage.removeItem(`upload_${uploadKey}`);
            }
        }

        // Find previous uploads on server
        upload.findPreviousUploads().then((previousUploads) => {
            if (previousUploads.length > 0) {
                upload.resumeFromPreviousUpload(previousUploads[0]);
            }
            upload.start();
        });

        // Track this upload
        this.uploads.set(uploadKey, {
            upload,
            startTime: Date.now(),
            lastBytes: 0,
            lastTime: Date.now(),
        });

        // Return controller
        return {
            pause: () => upload.abort(),
            resume: () => upload.start(),
            abort: () => {
                upload.abort();
                this.uploads.delete(uploadKey);
                localStorage.removeItem(`upload_${uploadKey}`);
            },
        };
    }

    /**
     * Upload multiple files
     */
    /**
     * Upload multiple files with concurrency control
     */
    uploadFiles(files, projectId, { onFileProgress, onFileComplete, onAllComplete, onError, concurrency = 3 }) {
        const controllers = [];
        let completedCount = 0;
        let activeCount = 0;
        let currentIndex = 0;

        const results = new Array(files.length);
        let isAborted = false;

        const processNext = () => {
            if (isAborted || currentIndex >= files.length) {
                if (completedCount === files.length && !isAborted) {
                    onAllComplete?.();
                }
                return;
            }

            while (activeCount < concurrency && currentIndex < files.length) {
                const index = currentIndex++;
                const file = files[index];
                activeCount++;

                const controller = this.uploadFile(file, projectId, {
                    onProgress: (progress) => {
                        onFileProgress?.(index, file.name, progress);
                    },
                    onError: (error) => {
                        activeCount--;
                        onError?.(index, file.name, error);
                        processNext();
                    },
                    onSuccess: (result) => {
                        activeCount--;
                        completedCount++;
                        results[index] = result;
                        onFileComplete?.(index, file.name, result);
                        processNext();
                    },
                });
                controllers.push(controller);
            }
        };

        processNext();

        return {
            pauseAll: () => controllers.forEach(c => c.pause?.()),
            resumeAll: () => controllers.forEach(c => c.resume?.()),
            abortAll: () => {
                isAborted = true;
                controllers.forEach(c => c.abort?.());
            },
        };
    }

    /**
     * Calculate upload speed in bytes/second
     */
    calculateSpeed(uploadKey, currentBytes) {
        const data = this.uploads.get(uploadKey);
        if (!data) return 0;

        const now = Date.now();
        const timeDiff = (now - data.lastTime) / 1000; // seconds

        if (timeDiff < 0.5) return data.lastSpeed || 0;

        const bytesDiff = currentBytes - data.lastBytes;
        const speed = bytesDiff / timeDiff;

        data.lastBytes = currentBytes;
        data.lastTime = now;
        data.lastSpeed = speed;

        return speed;
    }

    /**
     * Calculate ETA in seconds
     */
    calculateETA(bytesUploaded, bytesTotal, speed) {
        if (speed <= 0) return Infinity;
        const remaining = bytesTotal - bytesUploaded;
        return Math.ceil(remaining / speed);
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

export default ResumableUploader;
