import { useState, useCallback } from 'react';
import api from '../api/client';

// --- Constants ---
const ADMIN_PANEL_TAB_STORAGE_KEY = 'aerial_admin_last_tab';
export const ADMIN_PANEL_TABS = ['users', 'organizations', 'permissions'];
export const ADMIN_ROLE_OPTIONS = [
    { value: 'admin', label: '관리자' },
    { value: 'manager', label: '편집자' },
    { value: 'user', label: '뷰어' },
];

export const normalizeAdminRoleForForm = (role) => {
    const normalized = typeof role === 'string' ? role.trim().toLowerCase() : 'user';
    if (normalized === 'editor') return 'manager';
    if (normalized === 'viewer') return 'user';
    if (['admin', 'manager', 'user'].includes(normalized)) return normalized;
    return 'user';
};

export const getAdminRoleLabel = (role) => {
    const normalized = normalizeAdminRoleForForm(role);
    const roleMap = { admin: '관리자', manager: '편집자', user: '뷰어' };
    return roleMap[normalized] || '뷰어';
};

export const normalizePermissionRoleOption = (role) => {
    if (!role || typeof role !== 'object') return null;

    const rawValue = typeof role.value === 'string' ? role.value.trim().toLowerCase() : '';
    const normalizedValue =
        rawValue === 'editor' ? 'manager' : rawValue === 'viewer' ? 'user' : rawValue;

    const roleMap = { admin: '관리자', manager: '편집자', user: '뷰어' };

    return {
        value: normalizedValue || 'user',
        label: roleMap[normalizedValue] || role.label || roleMap[rawValue] || '뷰어',
        description: role.description || '',
    };
};

export const getInitialAdminTab = () => {
    if (typeof window === 'undefined') return 'users';
    const saved = window.localStorage.getItem(ADMIN_PANEL_TAB_STORAGE_KEY);
    return ADMIN_PANEL_TABS.includes(saved) ? saved : 'users';
};

/**
 * Custom hook that encapsulates all admin panel state and handlers.
 *
 * @param {Object} params
 * @param {Object} params.currentUser - Currently logged-in user
 * @param {boolean} params.canManageUsers
 * @param {boolean} params.canManageOrganizations
 * @param {boolean} params.canManagePermissions
 * @param {boolean} params.hasAdminMenuAccess
 * @param {Array} params.projects - List of projects (for permission tab)
 * @returns Admin panel state and handlers
 */
export function useAdminPanel({
    currentUser,
    canManageUsers,
    canManageOrganizations,
    canManagePermissions,
    hasAdminMenuAccess,
    projects,
}) {
    const [isAdminPanelOpen, setIsAdminPanelOpen] = useState(false);
    const [adminTab, setAdminTab] = useState(() => getInitialAdminTab());
    const [adminUsers, setAdminUsers] = useState([]);
    const [adminOrganizations, setAdminOrganizations] = useState([]);
    const [adminPermissionCatalog, setAdminPermissionCatalog] = useState({ roles: [], project_permissions: [] });
    const [adminLoading, setAdminLoading] = useState(false);
    const [adminError, setAdminError] = useState('');
    const [adminEditingUser, setAdminEditingUser] = useState(null);
    const [adminUserForm, setAdminUserForm] = useState({
        email: '', password: '', name: '', role: 'user', organizationId: '', inviteUser: false,
    });
    const [adminEditingOrganization, setAdminEditingOrganization] = useState(null);
    const [adminOrganizationForm, setAdminOrganizationForm] = useState({
        name: '', quota_storage_gb: 1000, quota_projects: 100,
    });
    const [selectedPermissionProjectId, setSelectedPermissionProjectId] = useState('');
    const [projectPermissions, setProjectPermissions] = useState([]);
    const [selectedPermissionUserId, setSelectedPermissionUserId] = useState('');
    const [selectedPermissionLevel, setSelectedPermissionLevel] = useState('view');

    // --- Form reset helpers ---
    const resetAdminUserForm = useCallback(() => {
        setAdminEditingUser(null);
        setAdminUserForm({ email: '', password: '', name: '', role: 'user', organizationId: '', inviteUser: false });
    }, []);

    const resetAdminOrganizationForm = useCallback(() => {
        setAdminEditingOrganization(null);
        setAdminOrganizationForm({ name: '', quota_storage_gb: 1000, quota_projects: 100 });
    }, []);

    // --- Data loading ---
    const loadAdminData = useCallback(async (nextTab = adminTab) => {
        if (!hasAdminMenuAccess) return;

        setAdminLoading(true);
        setAdminError('');
        const shouldLoadUsersForPermissions = canManageUsers || canManagePermissions;

        try {
            if (shouldLoadUsersForPermissions) {
                const usersResponse = await api.getUsers();
                setAdminUsers(Array.isArray(usersResponse) ? usersResponse : (usersResponse.items || []));
            } else {
                setAdminUsers([]);
            }

            if (canManageOrganizations) {
                const orgResponse = await api.getOrganizations();
                setAdminOrganizations(Array.isArray(orgResponse) ? orgResponse : (orgResponse.items || []));
            } else {
                setAdminOrganizations([]);
            }

            if (canManagePermissions) {
                const catalogResponse = await api.getPermissionCatalog();
                const normalizedRoles = (catalogResponse.roles || [])
                    .map(normalizePermissionRoleOption)
                    .filter(Boolean);

                setAdminPermissionCatalog({
                    roles: normalizedRoles,
                    project_permissions: catalogResponse.project_permissions || [],
                });

                if (nextTab === 'permissions') {
                    const projectIds = new Set(projects.map(p => p.id));
                    const projectId = (projectIds.has(selectedPermissionProjectId) ? selectedPermissionProjectId : '') || projects[0]?.id || '';
                    setSelectedPermissionProjectId(projectId);
                    if (projectId) {
                        const permissionResponse = await api.getProjectPermissions(projectId);
                        setProjectPermissions(permissionResponse.items || []);
                    } else {
                        setProjectPermissions([]);
                    }
                } else {
                    setProjectPermissions([]);
                }
            } else {
                setAdminPermissionCatalog({ roles: [], project_permissions: [] });
                setProjectPermissions([]);
            }
        } catch (err) {
            setAdminError(err.message || '관리 데이터 조회 실패');
        } finally {
            setAdminLoading(false);
        }
    }, [adminTab, hasAdminMenuAccess, canManageUsers, canManageOrganizations, canManagePermissions, projects, selectedPermissionProjectId]);

    const resolveAdminTab = useCallback((requestedTab = 'users') => {
        const allowed = {
            users: canManageUsers,
            organizations: canManageOrganizations,
            permissions: canManagePermissions,
        };

        const normalizedRequestedTab = ADMIN_PANEL_TABS.includes(requestedTab) ? requestedTab : 'users';

        if (allowed[normalizedRequestedTab]) return normalizedRequestedTab;
        return ADMIN_PANEL_TABS.find((tab) => allowed[tab]) || null;
    }, [canManageOrganizations, canManagePermissions, canManageUsers]);

    // --- Panel open/close ---
    const openAdminPanel = useCallback(async (tab = adminTab) => {
        if (!hasAdminMenuAccess) return;
        const resolvedTab = resolveAdminTab(tab);
        if (!resolvedTab) return;

        if (typeof window !== 'undefined') {
            window.localStorage.setItem(ADMIN_PANEL_TAB_STORAGE_KEY, resolvedTab);
        }

        setAdminTab(resolvedTab);
        if (resolvedTab === 'users') {
            resetAdminUserForm();
            setSelectedPermissionUserId('');
            setSelectedPermissionProjectId('');
            setProjectPermissions([]);
        }
        if (resolvedTab === 'organizations') {
            resetAdminOrganizationForm();
            setSelectedPermissionUserId('');
            setSelectedPermissionProjectId('');
            setProjectPermissions([]);
        }
        if (resolvedTab === 'permissions') {
            setSelectedPermissionLevel('view');
        }
        setIsAdminPanelOpen(true);
        await loadAdminData(resolvedTab);
    }, [adminTab, hasAdminMenuAccess, resolveAdminTab, resetAdminUserForm, resetAdminOrganizationForm, loadAdminData]);

    const closeAdminPanel = useCallback(() => {
        setIsAdminPanelOpen(false);
        setAdminError('');
        resetAdminUserForm();
        resetAdminOrganizationForm();
        setProjectPermissions([]);
    }, [resetAdminUserForm, resetAdminOrganizationForm]);

    // --- User handlers ---
    const handleAdminUserSubmit = useCallback(async (e) => {
        e.preventDefault();
        try {
            const email = adminUserForm.email?.trim();
            const name = adminUserForm.name?.trim();
            const organizationId = adminUserForm.organizationId || null;
            const targetRole = normalizeAdminRoleForForm(adminUserForm.role);
            const isEditing = Boolean(adminEditingUser);
            const isInviteMode = !isEditing && Boolean(adminUserForm.inviteUser);
            if (!adminEditingUser && !email) { alert('이메일은 필수입니다.'); return; }

            const payload = { role: targetRole, organization_id: organizationId || null };
            if (name) payload.name = name;

            if (isEditing) {
                const currentRole = normalizeAdminRoleForForm(adminEditingUser.role);
                const currentOrgId = adminEditingUser.organization_id || '';
                const nextOrgId = organizationId || '';

                const updatePayload = {};
                if (name !== (adminEditingUser.name || '')) updatePayload.name = name || '';

                const transferPayload = {};
                if (nextOrgId !== (currentOrgId || '')) transferPayload.organization_id = organizationId;
                if (targetRole !== currentRole) transferPayload.role = targetRole;

                if (Object.keys(updatePayload).length > 0) await api.updateUser(adminEditingUser.id, updatePayload);
                if (Object.keys(transferPayload).length > 0) await api.transferUser(adminEditingUser.id, transferPayload);

                if (Object.keys(updatePayload).length === 0 && Object.keys(transferPayload).length === 0) {
                    alert('변경된 내용이 없습니다.');
                } else {
                    alert('사용자 정보가 수정되었습니다.');
                }
            } else {
                if (!isInviteMode && (!adminUserForm.password || adminUserForm.password.length < 8)) {
                    alert('비밀번호는 8자 이상이어야 합니다.');
                    return;
                }

                if (isInviteMode) {
                    const inviteResult = await api.inviteUser({ email, ...payload });
                    if (inviteResult?.temporary_password) {
                        alert(`사용자가 초대되었습니다. 임시 비밀번호: ${inviteResult.temporary_password}`);
                    } else {
                        alert('기존 사용자 초대 처리(조직/권한 반영)가 완료되었습니다.');
                    }
                } else {
                    await api.createUser({ ...payload, email, password: adminUserForm.password });
                    alert('사용자가 생성되었습니다.');
                }
            }

            resetAdminUserForm();
            await loadAdminData('users');
        } catch (err) {
            alert(`사용자 저장 실패: ${err.message}`);
        }
    }, [adminUserForm, adminEditingUser, resetAdminUserForm, loadAdminData]);

    const handleEditUser = useCallback((user) => {
        setAdminEditingUser(user);
        setAdminUserForm({
            email: user.email || '', password: '', name: user.name || '',
            role: normalizeAdminRoleForForm(user.role),
            organizationId: user.organization_id || '', inviteUser: false,
        });
    }, []);

    const handleDeactivateUser = useCallback(async (userData) => {
        if (userData.id === currentUser?.id) { alert('현재 로그인한 사용자 계정은 비활성화할 수 없습니다.'); return; }
        if (!window.confirm(`"${userData.email}" 사용자를 비활성화 하시겠습니까?`)) return;
        try {
            await api.deactivateUser(userData.id);
            await loadAdminData('users');
            alert('사용자가 비활성화되었습니다.');
        } catch (err) {
            alert(`사용자 비활성화 실패: ${err.message}`);
        }
    }, [currentUser?.id, loadAdminData]);

    const handleDeleteUser = useCallback(async (userData) => {
        if (userData.id === currentUser?.id) { alert('현재 로그인한 사용자 계정은 삭제할 수 없습니다.'); return; }
        if (!window.confirm(`"${userData.email}" 사용자를 영구 삭제 하시겠습니까?`)) return;
        try {
            await api.deleteUser(userData.id);
            await loadAdminData('users');
            alert('사용자가 삭제되었습니다.');
        } catch (err) {
            alert(`사용자 삭제 실패: ${err.message}`);
        }
    }, [currentUser?.id, loadAdminData]);

    // --- Organization handlers ---
    const handleAdminOrganizationSubmit = useCallback(async (e) => {
        e.preventDefault();
        try {
            const payload = {
                name: adminOrganizationForm.name.trim(),
                quota_storage_gb: Number(adminOrganizationForm.quota_storage_gb),
                quota_projects: Number(adminOrganizationForm.quota_projects),
            };

            if (!payload.name) { alert('조직명은 필수입니다.'); return; }
            if (Number.isNaN(payload.quota_storage_gb) || Number.isNaN(payload.quota_projects) || payload.quota_storage_gb < 0 || payload.quota_projects < 0) {
                alert('스토리지/프로젝트 한도는 0 이상 정수여야 합니다.');
                return;
            }

            if (adminEditingOrganization) {
                await api.updateOrganization(adminEditingOrganization.id, payload);
                alert('조직이 수정되었습니다.');
            } else {
                await api.createOrganization(payload);
                alert('조직이 생성되었습니다.');
            }

            resetAdminOrganizationForm();
            await loadAdminData('organizations');
        } catch (err) {
            alert(`조직 저장 실패: ${err.message}`);
        }
    }, [adminOrganizationForm, adminEditingOrganization, resetAdminOrganizationForm, loadAdminData]);

    const handleEditOrganization = useCallback((org) => {
        setAdminEditingOrganization(org);
        setAdminOrganizationForm({
            name: org.name || '',
            quota_storage_gb: org.quota_storage_gb ?? 1000,
            quota_projects: org.quota_projects ?? 100,
        });
    }, []);

    const handleDeleteOrganization = useCallback(async (org) => {
        if (!window.confirm(`"${org.name}" 조직을 삭제하시겠습니까?`)) return;
        try {
            await api.deleteOrganization(org.id, false);
            await loadAdminData('organizations');
            alert('조직이 삭제되었습니다.');
        } catch (err) {
            if (err.status === 409) {
                if (window.confirm('조직에 사용자/프로젝트가 연결되어 있습니다. 강제 삭제하시겠습니까?')) {
                    try {
                        await api.deleteOrganization(org.id, true);
                        await loadAdminData('organizations');
                        alert('조직이 강제 삭제되었습니다.');
                    } catch (forceErr) {
                        alert(`조직 삭제 실패: ${forceErr.message}`);
                    }
                }
                return;
            }
            alert(`조직 삭제 실패: ${err.message}`);
        }
    }, [loadAdminData]);

    // --- Permission handlers ---
    const loadProjectPermissions = useCallback(async (projectId) => {
        if (!projectId) { setProjectPermissions([]); return; }
        try {
            const response = await api.getProjectPermissions(projectId);
            setProjectPermissions(response.items || []);
        } catch (err) {
            alert(`권한 조회 실패: ${err.message}`);
            setProjectPermissions([]);
        }
    }, []);

    const handlePermissionProjectChange = useCallback(async (projectId) => {
        setSelectedPermissionProjectId(projectId);
        await loadProjectPermissions(projectId);
    }, [loadProjectPermissions]);

    const handleSubmitPermission = useCallback(async (e) => {
        e.preventDefault();
        if (!selectedPermissionProjectId || !selectedPermissionUserId) {
            alert('프로젝트와 사용자를 선택해 주세요.');
            return;
        }
        try {
            await api.setProjectPermission(selectedPermissionProjectId, selectedPermissionUserId, {
                permission: selectedPermissionLevel,
            });
            await loadProjectPermissions(selectedPermissionProjectId);
            setSelectedPermissionUserId('');
            setSelectedPermissionLevel('view');
            alert('권한이 저장되었습니다.');
        } catch (err) {
            alert(`권한 저장 실패: ${err.message}`);
        }
    }, [selectedPermissionProjectId, selectedPermissionUserId, selectedPermissionLevel, loadProjectPermissions]);

    const handleDeletePermission = useCallback(async (permissionRecord) => {
        if (!window.confirm('해당 사용자 권한을 삭제하시겠습니까?')) return;
        try {
            await api.removeProjectPermission(permissionRecord.project_id, permissionRecord.user_id);
            await loadProjectPermissions(selectedPermissionProjectId);
            alert('권한이 삭제되었습니다.');
        } catch (err) {
            alert(`권한 삭제 실패: ${err.message}`);
        }
    }, [selectedPermissionProjectId, loadProjectPermissions]);

    // --- Computed ---
    const adminTabLabelMap = { users: '사용자', organizations: '조직', permissions: '프로젝트 권한' };
    const adminCurrentTabLabel = adminTabLabelMap[adminTab] || '관리';

    return {
        // Panel state
        isAdminPanelOpen,
        adminTab,
        adminCurrentTabLabel,
        adminLoading,
        adminError,

        // User state
        adminUsers,
        adminEditingUser,
        adminUserForm,
        setAdminUserForm,

        // Organization state
        adminOrganizations,
        adminEditingOrganization,
        adminOrganizationForm,
        setAdminOrganizationForm,

        // Permission state
        adminPermissionCatalog,
        selectedPermissionProjectId,
        projectPermissions,
        selectedPermissionUserId,
        setSelectedPermissionUserId,
        selectedPermissionLevel,
        setSelectedPermissionLevel,

        // Panel actions
        openAdminPanel,
        closeAdminPanel,

        // User actions
        handleAdminUserSubmit,
        handleEditUser,
        handleDeactivateUser,
        handleDeleteUser,

        // Organization actions
        handleAdminOrganizationSubmit,
        handleEditOrganization,
        handleDeleteOrganization,

        // Permission actions
        handlePermissionProjectChange,
        handleSubmitPermission,
        handleDeletePermission,
    };
}
