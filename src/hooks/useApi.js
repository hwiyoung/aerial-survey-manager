/**
 * Custom hooks for API data fetching
 */
import { useState, useEffect, useCallback } from 'react';
import api from '../api/client';

/**
 * Hook for fetching and managing projects
 */
export function useProjects(options = {}) {
    const [projects, setProjects] = useState([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);
    const [pagination, setPagination] = useState({ total: 0, page: 1, pageSize: 20 });

    const fetchProjects = useCallback(async (params = {}) => {
        setLoading(true);
        setError(null);
        try {
            // Filter out undefined values to prevent "undefined" string in URL params
            const queryParams = {
                page: params.page || 1,
                page_size: params.pageSize || 20,
            };
            if (params.status && params.status !== 'ALL') queryParams.status = params.status;
            if (params.region && params.region !== 'ALL') queryParams.region = params.region;
            if (params.search) queryParams.search = params.search;

            const response = await api.getProjects(queryParams);
            const fetchedProjects = response.items || [];

            // Merge: Keep locally-created projects that aren't in the response yet
            // This prevents projects from "disappearing" due to timing issues
            setProjects(prev => {
                const fetchedIds = new Set(fetchedProjects.map(p => p.id));
                // Find locally-created projects not in response (likely just created)
                const localOnly = prev.filter(p => !fetchedIds.has(p.id));
                // Return fetched projects + local-only projects at the start
                return [...localOnly, ...fetchedProjects];
            });

            setPagination({
                total: response.total,
                page: response.page,
                pageSize: response.page_size,
            });
        } catch (err) {
            setError(err.message);
            setProjects([]);
        } finally {
            setLoading(false);
        }
    }, []);

    const createProject = useCallback(async (data) => {
        try {
            const newProject = await api.createProject(data);
            setProjects(prev => [newProject, ...prev]);
            return newProject;
        } catch (err) {
            setError(err.message);
            throw err;
        }
    }, []);

    const updateProject = useCallback(async (projectId, data) => {
        try {
            const updated = await api.updateProject(projectId, data);
            setProjects(prev => prev.map(p => p.id === projectId ? updated : p));
            return updated;
        } catch (err) {
            setError(err.message);
            throw err;
        }
    }, []);

    const deleteProject = useCallback(async (projectId) => {
        try {
            const result = await api.batchDeleteProjects([projectId]);
            if (result.failed && result.failed.length > 0) {
                const failed = result.failed.find((item) => item.project_id === projectId);
                const reason = failed?.reason || '프로젝트 삭제에 실패했습니다.';
                const err = new Error(reason);
                setError(err.message);
                throw err;
            }
            setProjects(prev => prev.filter(p => p.id !== projectId));
            return result;
        } catch (err) {
            setError(err.message);
            throw err;
        }
    }, []);

    const batchDeleteProjects = useCallback(async (projectIds) => {
        try {
            const result = await api.batchDeleteProjects(projectIds);
            const successSet = new Set(result.succeeded || []);
            setProjects(prev => prev.filter(p => !successSet.has(p.id)));
            return result;
        } catch (err) {
            setError(err.message);
            throw err;
        }
    }, []);

    const batchUpdateProjectStatus = useCallback(async (projectIds, status) => {
        try {
            const result = await api.batchUpdateProjectStatus(projectIds, status);
            const successSet = new Set(result.succeeded || []);
            setProjects(prev => prev.map(p => successSet.has(p.id) ? { ...p, status: result.action === 'update_status' ? status : p.status } : p));
            return result;
        } catch (err) {
            setError(err.message);
            throw err;
        }
    }, []);

    useEffect(() => {
        fetchProjects(options);
    }, []);

    return {
        projects,
        loading,
        error,
        pagination,
        refresh: fetchProjects,
        createProject,
        updateProject,
        deleteProject,
        batchDeleteProjects,
        batchUpdateProjectStatus,
    };
}

/**
 * Hook for fetching single project details
 */
export function useProject(projectId) {
    const [project, setProject] = useState(null);
    const [images, setImages] = useState([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);

    const fetchProject = useCallback(async () => {
        if (!projectId) {
            setProject(null);
            setImages([]);
            setLoading(false);
            return;
        }

        setLoading(true);
        setError(null);
        try {
            const [projectData, imagesData] = await Promise.all([
                api.getProject(projectId),
                api.getProjectImages(projectId).catch(() => []),
            ]);
            setProject(projectData);
            setImages(imagesData);
        } catch (err) {
            setError(err.message);
            setProject(null);
        } finally {
            setLoading(false);
        }
    }, [projectId]);

    useEffect(() => {
        fetchProject();
    }, [fetchProject]);

    return {
        project,
        images,
        loading,
        error,
        refresh: fetchProject,
    };
}

/**
 * Hook for processing status with WebSocket updates
 */
export function useProcessingStatus(projectId) {
    const [status, setStatus] = useState(null);
    const [connected, setConnected] = useState(false);

    useEffect(() => {
        if (!projectId) return;

        // Initial status fetch
        api.getProcessingStatus(projectId)
            .then(setStatus)
            .catch(() => setStatus(null));

        // WebSocket connection for real-time updates
        const ws = api.connectStatusWebSocket(projectId, (data) => {
            setStatus(prev => ({ ...prev, ...data }));
        });

        setConnected(true);

        return () => {
            ws.close();
            setConnected(false);
        };
    }, [projectId]);

    const startProcessing = useCallback(async (options, force = false) => {
        try {
            const job = await api.startProcessing(projectId, options, force);
            setStatus(job);
            return job;
        } catch (err) {
            throw err;
        }
    }, [projectId]);

    const cancelProcessing = useCallback(async () => {
        try {
            await api.cancelProcessing(projectId);
            setStatus(prev => ({ ...prev, status: 'cancelled' }));
        } catch (err) {
            throw err;
        }
    }, [projectId]);

    return {
        status,
        connected,
        startProcessing,
        cancelProcessing,
    };
}
