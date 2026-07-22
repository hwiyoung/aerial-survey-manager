import { useState, useEffect, useCallback, useRef } from 'react';
import api from '../api/client';

function formatProcessingError(data) {
    const parts = [data?.error_message || data?.message || '처리 중 오류가 발생했습니다.'];
    if (data?.error_action) parts.push(data.error_action);
    if (data?.error_reference) parts.push(`오류 참조번호: ${data.error_reference}`);
    return parts.join('\n');
}

/**
 * Custom hook for real-time processing progress via WebSocket
 * Connects to the backend WebSocket endpoint and receives progress updates
 * 
 * @param {string|null} projectId - The project ID to track (null to disable)
 * @returns {Object} - { progress, status, message, isConnected }
 */
export function useProcessingProgress(projectId) {
    const [progress, setProgress] = useState(0);
    const [status, setStatus] = useState('idle'); // idle, connecting, queued, processing, complete, error
    const [message, setMessage] = useState('');
    const [isConnected, setIsConnected] = useState(false);
    const [reconnectKey, setReconnectKey] = useState(0);

    const wsRef = useRef(null);
    const pingIntervalRef = useRef(null);
    const statusRef = useRef(status);
    const updateStatus = useCallback((nextStatus) => {
        statusRef.current = nextStatus;
        setStatus(nextStatus);
    }, []);

    useEffect(() => {
        if (!projectId) {
            setProgress(0);
            updateStatus('idle');
            setMessage('');
            setIsConnected(false);
            return;
        }

        // Fetch latest status once on entry to avoid "connecting" stall
        let cancelled = false;
        const fetchInitialStatus = async () => {
            try {
                const data = await api.getProcessingStatus(projectId);
                if (cancelled) return;

                if (data.progress !== undefined) {
                    setProgress(data.progress);
                }
                if (data.status) {
                    if (data.status === 'completed') {
                        updateStatus('complete');
                        setProgress(100);
                    } else if (data.status === 'cancelled') {
                        updateStatus('cancelled');
                        setProgress(0);
                    } else if (data.status === 'error' || data.status === 'failed') {
                        updateStatus('error');
                        setMessage(formatProcessingError(data));
                    } else if (data.status === 'queued') {
                        updateStatus('queued');
                    } else if (data.status === 'processing' || data.status === 'running') {
                        updateStatus('processing');
                    }
                }
            } catch {
                // Ignore initial status fetch errors
            }
        };
        fetchInitialStatus();

        // Construct WebSocket URL using current origin (nginx proxy handles routing)
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const host = window.location.host; // Includes port (e.g., localhost:18110)
        const token = localStorage.getItem('access_token');
        const wsUrl = `${protocol}//${host}/api/v1/processing/ws/projects/${projectId}/status${token ? `?token=${token}` : ''}`;

        updateStatus('connecting');

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
                            updateStatus('complete');
                            setProgress(100);
                        } else if (data.status === 'cancelled') {
                            updateStatus('cancelled');
                            setProgress(0);
                        } else if (data.status === 'error' || data.status === 'failed') {
                            updateStatus('error');
                            setMessage(formatProcessingError(data));
                        } else if (data.status === 'queued') {
                            updateStatus('queued');
                        } else if (data.status === 'processing' || data.status === 'running') {
                            updateStatus('processing');
                        }
                        // 'scheduled', 'pending' 등은 무시 (idle 유지)
                    }

                    const incomingMessage = String(data.message || '');
                    const isCrsCorrectionReservationMessage = /^좌표계 변경 예약/.test(incomingMessage);
                    const isErrorStatus = data.status === 'error' || data.status === 'failed';
                    if (incomingMessage && !isCrsCorrectionReservationMessage && !isErrorStatus) {
                        setMessage(data.message);
                    }
                } catch (e) {
                    console.warn('[WS] Failed to parse message:', e);
                }
            };

            ws.onerror = (error) => {
                console.error('[WS] WebSocket error:', error);
                updateStatus('error');
                setIsConnected(false);
            };

            ws.onclose = (event) => {
                console.log('[WS] Disconnected:', event.code, event.reason);
                setIsConnected(false);
                if (cancelled) return;
                if (statusRef.current !== 'complete' && statusRef.current !== 'error') {
                    updateStatus('idle');
                }
            };
        } catch (error) {
            console.error('[WS] Failed to create WebSocket:', error);
            updateStatus('error');
        }

        // Cleanup on unmount or projectId change
        return () => {
            cancelled = true;
            if (pingIntervalRef.current) {
                clearInterval(pingIntervalRef.current);
                pingIntervalRef.current = null;
            }
            if (wsRef.current) {
                wsRef.current.close();
                wsRef.current = null;
            }
        };
    }, [projectId, reconnectKey, updateStatus]);

    // Manual reconnect function
    const reconnect = useCallback(() => {
        if (wsRef.current) {
            wsRef.current.close();
        }
        updateStatus('connecting');
        setReconnectKey(prev => prev + 1);
    }, [updateStatus]);

    return {
        progress,
        status,
        message,
        isConnected,
        reconnect
    };
}

export default useProcessingProgress;
