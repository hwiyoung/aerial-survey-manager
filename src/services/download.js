/**
 * Resumable Download Service
 * Handles large file downloads with automatic resume capability
 */
export class ResumableDownloader {
    constructor(authToken) {
        this.authToken = authToken;
        this.activeDownloads = new Map();
    }

    /**
     * Download a file with resumable support
     * @param {string} url - Download URL
     * @param {string} filename - Filename to save as
     * @param {Object} callbacks - Callback functions
     * @returns {Object} Download controller with pause/resume/abort methods
     */
    async downloadFile(url, filename, { onProgress, onComplete, onError }) {
        const downloadKey = filename;
        const CHUNK_SIZE = 50 * 1024 * 1024; // 50MB chunks

        try {
            // 1. Get file info
            const headResponse = await fetch(url, {
                method: 'HEAD',
                headers: { 'Authorization': `Bearer ${this.authToken}` },
            });

            if (!headResponse.ok) {
                throw new Error(`Failed to get file info: ${headResponse.status}`);
            }

            const totalSize = parseInt(headResponse.headers.get('Content-Length'));
            const serverChecksum = headResponse.headers.get('X-File-Checksum');

            if (!totalSize) {
                throw new Error('Server did not provide Content-Length');
            }

            // 2. Check for previous download progress
            const stored = localStorage.getItem(`download_${downloadKey}`);
            let downloadedSize = 0;
            let chunks = [];

            if (stored) {
                try {
                    const data = JSON.parse(stored);
                    if (data.totalSize === totalSize) {
                        downloadedSize = data.downloadedSize;
                        chunks = await this.loadChunksFromDB(downloadKey);
                    } else {
                        // File changed, start fresh
                        await this.clearChunksFromDB(downloadKey);
                    }
                } catch (e) {
                    localStorage.removeItem(`download_${downloadKey}`);
                }
            }

            // 3. Track download state
            const state = {
                aborted: false,
                paused: false,
                downloadedSize,
                totalSize,
                chunks,
            };
            this.activeDownloads.set(downloadKey, state);

            // 4. Download remaining chunks
            while (state.downloadedSize < totalSize && !state.aborted) {
                if (state.paused) {
                    // Save progress and wait
                    await new Promise(resolve => {
                        state.resumeCallback = resolve;
                    });
                    continue;
                }

                const start = state.downloadedSize;
                const end = Math.min(start + CHUNK_SIZE - 1, totalSize - 1);

                try {
                    const response = await fetch(url, {
                        headers: {
                            'Authorization': `Bearer ${this.authToken}`,
                            'Range': `bytes=${start}-${end}`,
                        },
                    });

                    if (response.status === 206) {
                        const chunk = await response.arrayBuffer();
                        state.chunks.push({ start, data: chunk });
                        state.downloadedSize = end + 1;

                        // Save progress
                        await this.saveChunkToDB(downloadKey, start, chunk);
                        localStorage.setItem(`download_${downloadKey}`, JSON.stringify({
                            downloadedSize: state.downloadedSize,
                            totalSize,
                            timestamp: Date.now(),
                        }));

                        onProgress?.({
                            downloaded: state.downloadedSize,
                            total: totalSize,
                            percentage: ((state.downloadedSize / totalSize) * 100).toFixed(2),
                        });
                    } else if (response.status === 200) {
                        // Server doesn't support range requests, download entire file
                        const blob = await response.blob();
                        state.chunks = [{ start: 0, data: await blob.arrayBuffer() }];
                        state.downloadedSize = totalSize;
                    } else {
                        throw new Error(`Download failed: ${response.status}`);
                    }
                } catch (error) {
                    if (state.aborted) break;

                    // Network error - wait and retry
                    console.warn('Download chunk failed, retrying...', error);
                    await new Promise(r => setTimeout(r, 3000));
                }
            }

            if (state.aborted) {
                throw new Error('Download aborted');
            }

            // 5. Merge chunks and verify
            const blob = this.mergeChunks(state.chunks, totalSize);

            // 6. Verify checksum if provided
            if (serverChecksum) {
                const localChecksum = await this.calculateChecksum(blob);
                if (localChecksum !== serverChecksum) {
                    throw new Error('Checksum mismatch - file may be corrupted');
                }
            }

            // 7. Cleanup and trigger download
            localStorage.removeItem(`download_${downloadKey}`);
            await this.clearChunksFromDB(downloadKey);
            this.activeDownloads.delete(downloadKey);

            // Trigger browser download
            const downloadUrl = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = downloadUrl;
            a.download = filename;
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
            URL.revokeObjectURL(downloadUrl);

            onComplete?.({ filename, size: totalSize, checksum: serverChecksum });
            return blob;

        } catch (error) {
            onError?.(error);
            throw error;
        }
    }

    /**
     * Merge downloaded chunks into a single blob
     */
    mergeChunks(chunks, totalSize) {
        // Sort chunks by start position
        chunks.sort((a, b) => a.start - b.start);

        const buffer = new Uint8Array(totalSize);
        for (const chunk of chunks) {
            buffer.set(new Uint8Array(chunk.data), chunk.start);
        }

        return new Blob([buffer]);
    }

    /**
     * Calculate SHA-256 checksum of a blob
     */
    async calculateChecksum(blob) {
        const buffer = await blob.arrayBuffer();
        const hashBuffer = await crypto.subtle.digest('SHA-256', buffer);
        const hashArray = Array.from(new Uint8Array(hashBuffer));
        return hashArray.map(b => b.toString(16).padStart(2, '0')).join('');
    }

    /**
     * IndexedDB operations for chunk storage
     */
    async openDB() {
        return new Promise((resolve, reject) => {
            const request = indexedDB.open('AerialSurveyDownloads', 1);

            request.onerror = () => reject(request.error);
            request.onsuccess = () => resolve(request.result);

            request.onupgradeneeded = (event) => {
                const db = event.target.result;
                if (!db.objectStoreNames.contains('chunks')) {
                    db.createObjectStore('chunks', { keyPath: ['filename', 'start'] });
                }
            };
        });
    }

    async saveChunkToDB(filename, start, data) {
        const db = await this.openDB();
        return new Promise((resolve, reject) => {
            const tx = db.transaction('chunks', 'readwrite');
            const store = tx.objectStore('chunks');
            store.put({ filename, start, data });
            tx.oncomplete = resolve;
            tx.onerror = () => reject(tx.error);
        });
    }

    async loadChunksFromDB(filename) {
        const db = await this.openDB();
        return new Promise((resolve, reject) => {
            const tx = db.transaction('chunks', 'readonly');
            const store = tx.objectStore('chunks');
            const chunks = [];

            store.openCursor().onsuccess = (event) => {
                const cursor = event.target.result;
                if (cursor) {
                    if (cursor.value.filename === filename) {
                        chunks.push(cursor.value);
                    }
                    cursor.continue();
                } else {
                    resolve(chunks);
                }
            };

            tx.onerror = () => reject(tx.error);
        });
    }

    async clearChunksFromDB(filename) {
        const db = await this.openDB();
        const chunks = await this.loadChunksFromDB(filename);

        return new Promise((resolve, reject) => {
            const tx = db.transaction('chunks', 'readwrite');
            const store = tx.objectStore('chunks');

            chunks.forEach(chunk => {
                store.delete([filename, chunk.start]);
            });

            tx.oncomplete = resolve;
            tx.onerror = () => reject(tx.error);
        });
    }

    /**
     * Get download controller for an active download
     */
    getController(filename) {
        const state = this.activeDownloads.get(filename);
        if (!state) return null;

        return {
            pause: () => {
                state.paused = true;
            },
            resume: () => {
                state.paused = false;
                state.resumeCallback?.();
            },
            abort: () => {
                state.aborted = true;
                state.resumeCallback?.();
            },
            getProgress: () => ({
                downloaded: state.downloadedSize,
                total: state.totalSize,
                percentage: ((state.downloadedSize / state.totalSize) * 100).toFixed(2),
                paused: state.paused,
            }),
        };
    }

}

export default ResumableDownloader;
