import { useState, useEffect, useCallback, useRef } from 'react';

/**
 * Custom hook for real-time processing progress via WebSocket
 * Connects to the backend WebSocket endpoint and receives progress updates
 * 
 * @param {string|null} projectId - The project ID to track (null to disable)
 * @returns {Object} - { progress, status, message, isConnected }
 */
export function useProcessingProgress(projectId) {
    const [progress, setProgress] = useState(0);
    const [status, setStatus] = useState('idle'); // idle, connecting, processing, complete, error
    const [message, setMessage] = useState('');
    const [isConnected, setIsConnected] = useState(false);

    const wsRef = useRef(null);
    const pingIntervalRef = useRef(null);

    useEffect(() => {
        if (!projectId) {
            setProgress(0);
            setStatus('idle');
            setMessage('');
            setIsConnected(false);
            return;
        }

        // Construct WebSocket URL using current origin (nginx proxy handles routing)
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const host = window.location.host; // Includes port (e.g., localhost:8081)
        const wsUrl = `${protocol}//${host}/api/v1/processing/ws/projects/${projectId}/status`;

        setStatus('connecting');

        try {
            const ws = new WebSocket(wsUrl);
            wsRef.current = ws;

            ws.onopen = () => {
                console.log('[WS] Connected to processing status');
                setIsConnected(true);
                // Status should NOT be set to 'processing' here. 
                // It should be determined by actual status messages from the backend
                // or remain 'connecting' until the first message arrives.

                // Start ping interval to keep connection alive
                pingIntervalRef.current = setInterval(() => {
                    if (ws.readyState === WebSocket.OPEN) {
                        ws.send('ping');
                    }
                }, 30000); // Ping every 30 seconds
            };

            ws.onmessage = (event) => {
                try {
                    // Handle pong response
                    if (event.data === 'pong') return;

                    const data = JSON.parse(event.data);

                    if (data.progress !== undefined) {
                        setProgress(data.progress);
                    }

                    if (data.status) {
                        if (data.status === 'completed') {
                            setStatus('complete');
                            setProgress(100);
                        } else if (data.status === 'error' || data.status === 'failed') {
                            setStatus('error');
                        } else {
                            setStatus('processing');
                        }
                    }

                    if (data.message) {
                        setMessage(data.message);
                    }
                } catch (e) {
                    console.warn('[WS] Failed to parse message:', e);
                }
            };

            ws.onerror = (error) => {
                console.error('[WS] WebSocket error:', error);
                setStatus('error');
                setIsConnected(false);
            };

            ws.onclose = (event) => {
                console.log('[WS] Disconnected:', event.code, event.reason);
                setIsConnected(false);
                if (status !== 'complete' && status !== 'error') {
                    setStatus('idle');
                }
            };
        } catch (error) {
            console.error('[WS] Failed to create WebSocket:', error);
            setStatus('error');
        }

        // Cleanup on unmount or projectId change
        return () => {
            if (pingIntervalRef.current) {
                clearInterval(pingIntervalRef.current);
                pingIntervalRef.current = null;
            }
            if (wsRef.current) {
                wsRef.current.close();
                wsRef.current = null;
            }
        };
    }, [projectId]);

    // Manual reconnect function
    const reconnect = useCallback(() => {
        if (wsRef.current) {
            wsRef.current.close();
        }
        setStatus('connecting');
    }, []);

    return {
        progress,
        status,
        message,
        isConnected,
        reconnect
    };
}

export default useProcessingProgress;
