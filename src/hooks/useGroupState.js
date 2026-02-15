import { useState, useCallback, useEffect } from 'react';
import api from '../api/client';

/**
 * Custom hook that encapsulates group (folder) state and CRUD handlers.
 *
 * @param {Object} params
 * @param {Function} params.refreshProjects - Callback to refresh project list after group changes
 * @param {Function} params.canEditProjectById - Permission check for project moves
 * @returns Group state and handler functions
 */
export function useGroupState({ refreshProjects, canEditProjectById }) {
    const [groups, setGroups] = useState([]);
    const [expandedGroupIds, setExpandedGroupIds] = useState(new Set());
    const [isGroupModalOpen, setIsGroupModalOpen] = useState(false);
    const [editingGroup, setEditingGroup] = useState(null);
    const [activeGroupId, setActiveGroupId] = useState(null);

    // Fetch groups on mount
    useEffect(() => {
        api.getGroups().then(data => {
            setGroups(Array.isArray(data) ? data : (data.items || []));
        }).catch(err => console.error('Failed to fetch groups:', err));
    }, []);

    const handleCreateGroup = useCallback(async (name, color) => {
        try {
            const created = await api.createGroup({ name, color: color || '#94a3b8' });
            setGroups(prev => [...prev, created]);
            setExpandedGroupIds(prev => new Set([...prev, created.id]));
            return created;
        } catch (err) {
            console.error('Failed to create group:', err);
            throw err;
        }
    }, []);

    const handleUpdateGroup = useCallback(async (groupId, data) => {
        try {
            const updated = await api.updateGroup(groupId, data);
            setGroups(prev => prev.map(g => g.id === groupId ? { ...g, ...updated } : g));
        } catch (err) {
            console.error('Failed to update group:', err);
        }
    }, []);

    const handleDeleteGroup = useCallback(async (groupId) => {
        if (!window.confirm('이 그룹을 삭제하시겠습니까? 그룹 내 프로젝트는 유지됩니다.')) return;
        try {
            await api.deleteGroup(groupId);
            setGroups(prev => prev.filter(g => g.id !== groupId));
            refreshProjects();
        } catch (err) {
            console.error('Failed to delete group:', err);
        }
    }, [refreshProjects]);

    const handleMoveProjectToGroup = useCallback(async (projectId, groupId) => {
        if (!canEditProjectById(projectId)) {
            alert('프로젝트 이동 권한이 없습니다.');
            return;
        }

        try {
            await api.moveProjectToGroup(projectId, groupId);
            refreshProjects();
        } catch (err) {
            console.error('Failed to move project:', err);
        }
    }, [canEditProjectById, refreshProjects]);

    const toggleGroupExpand = useCallback((groupId) => {
        setExpandedGroupIds(prev => {
            const next = new Set(prev);
            if (next.has(groupId)) next.delete(groupId);
            else next.add(groupId);
            return next;
        });
    }, []);

    const openGroupModal = useCallback(() => setIsGroupModalOpen(true), []);
    const closeGroupModal = useCallback(() => {
        setIsGroupModalOpen(false);
        setEditingGroup(null);
    }, []);

    const toggleGroupFilter = useCallback((groupId) => {
        setActiveGroupId(prev => prev === groupId ? null : groupId);
    }, []);

    const clearGroupFilter = useCallback(() => {
        setActiveGroupId(null);
    }, []);

    return {
        groups,
        expandedGroupIds,
        isGroupModalOpen,
        editingGroup,
        activeGroupId,
        setEditingGroup,
        handleCreateGroup,
        handleUpdateGroup,
        handleDeleteGroup,
        handleMoveProjectToGroup,
        toggleGroupExpand,
        openGroupModal,
        closeGroupModal,
        toggleGroupFilter,
        clearGroupFilter,
    };
}
