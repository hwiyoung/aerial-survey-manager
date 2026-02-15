import React from 'react';
import { X } from 'lucide-react';
import { ADMIN_ROLE_OPTIONS, getAdminRoleLabel } from '../../hooks/useAdminPanel';

/**
 * AdminPanel — Modal component for admin management (Users, Organizations, Permissions).
 * All state and handlers are provided via props from useAdminPanel hook.
 */
export default function AdminPanel({
    // Panel state
    adminTab,
    adminCurrentTabLabel,
    adminLoading,
    adminError,
    // Permissions
    canManageUsers,
    canManageOrganizations,
    canManagePermissions,
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
    // Data for permission tab
    projects,
}) {
    return (
        <div className="fixed inset-0 z-[1000] bg-black/60 backdrop-blur-sm flex items-center justify-center p-4" onClick={closeAdminPanel}>
            <div className="bg-white rounded-xl shadow-2xl w-full max-w-5xl max-h-[88vh] overflow-hidden" onClick={(e) => e.stopPropagation()}>
                <div className="h-14 border-b border-slate-200 bg-slate-50 flex items-center justify-between px-6">
                    <h3 className="font-bold text-slate-800 flex items-center gap-2">
                        관리 메뉴
                        <span className="text-slate-500 font-medium">- {adminCurrentTabLabel}</span>
                    </h3>
                    <button onClick={closeAdminPanel}><X size={20} className="text-slate-400 hover:text-slate-600" /></button>
                </div>
                <div className="px-6 py-3 border-b border-slate-200 flex gap-2 flex-wrap">
                    <button
                        onClick={() => openAdminPanel('users')}
                        title={!canManageUsers ? '권한이 없어 접근 가능한 첫 탭으로 이동합니다.' : '사용자 탭'}
                        className={`px-3 py-2 rounded-md text-sm font-medium ${adminTab === 'users' ? 'bg-blue-600 text-white' : 'bg-slate-100 text-slate-700'} ${!canManageUsers ? 'opacity-50 cursor-not-allowed' : ''}`}
                    >
                        사용자
                    </button>
                    <button
                        onClick={() => openAdminPanel('organizations')}
                        title={!canManageOrganizations ? '권한이 없어 접근 가능한 첫 탭으로 이동합니다.' : '조직 탭'}
                        className={`px-3 py-2 rounded-md text-sm font-medium ${adminTab === 'organizations' ? 'bg-blue-600 text-white' : 'bg-slate-100 text-slate-700'} ${!canManageOrganizations ? 'opacity-50 cursor-not-allowed' : ''}`}
                    >
                        조직
                    </button>
                    <button
                        onClick={() => openAdminPanel('permissions')}
                        title={!canManagePermissions ? '권한이 없어 접근 가능한 첫 탭으로 이동합니다.' : '프로젝트 권한 탭'}
                        className={`px-3 py-2 rounded-md text-sm font-medium ${adminTab === 'permissions' ? 'bg-blue-600 text-white' : 'bg-slate-100 text-slate-700'} ${!canManagePermissions ? 'opacity-50 cursor-not-allowed' : ''}`}
                    >
                        프로젝트 권한
                    </button>
                </div>
                <div className="p-6 overflow-y-auto max-h-[calc(88vh-3.5rem-3.75rem)] space-y-4">
                    {adminError && (
                        <div className="bg-red-50 text-red-600 text-sm p-3 rounded-md border border-red-200">
                            {adminError}
                        </div>
                    )}
                    {adminLoading && <div className="text-sm text-slate-500">데이터를 불러오는 중입니다.</div>}

                    {/* Users Tab */}
                    {adminTab === 'users' && canManageUsers && (
                        <div className="space-y-5">
                            <form onSubmit={handleAdminUserSubmit} className="grid grid-cols-1 md:grid-cols-4 gap-3">
                                <input
                                    required
                                    type="email"
                                    value={adminUserForm.email}
                                    onChange={(e) => setAdminUserForm(prev => ({ ...prev, email: e.target.value }))}
                                    className="h-10 border border-slate-200 rounded-md px-3 text-sm"
                                    placeholder="이메일"
                                />
                                <input
                                    required={!adminEditingUser && !adminUserForm.inviteUser}
                                    minLength={8}
                                    type="password"
                                    value={adminUserForm.password}
                                    onChange={(e) => setAdminUserForm(prev => ({ ...prev, password: e.target.value }))}
                                    className="h-10 border border-slate-200 rounded-md px-3 text-sm"
                                    placeholder={adminEditingUser ? '변경 시 입력(선택)' : adminUserForm.inviteUser ? '초대 모드: 임시 비밀번호 자동 생성' : '비밀번호(필수 8자 이상)'}
                                />
                                {!adminEditingUser && (
                                    <label className="flex items-center gap-2 text-xs text-slate-600 md:col-span-1">
                                        <input
                                            type="checkbox"
                                            checked={adminUserForm.inviteUser}
                                            onChange={(e) => setAdminUserForm(prev => ({ ...prev, inviteUser: e.target.checked }))}
                                            className="w-4 h-4"
                                        />
                                        초대 모드(임시 비밀번호 자동 생성)
                                    </label>
                                )}
                                <input
                                    type="text"
                                    value={adminUserForm.name}
                                    onChange={(e) => setAdminUserForm(prev => ({ ...prev, name: e.target.value }))}
                                    className="h-10 border border-slate-200 rounded-md px-3 text-sm"
                                    placeholder="이름"
                                />
                                <select
                                    value={adminUserForm.role}
                                    onChange={(e) => setAdminUserForm(prev => ({ ...prev, role: e.target.value }))}
                                    className="h-10 border border-slate-200 rounded-md px-3 text-sm"
                                >
                                    {(adminPermissionCatalog.roles.length > 0 ? adminPermissionCatalog.roles : ADMIN_ROLE_OPTIONS).map(role => (
                                        <option key={role.value} value={role.value}>{role.label}</option>
                                    ))}
                                </select>
                                <select
                                    value={adminUserForm.organizationId}
                                    onChange={(e) => setAdminUserForm(prev => ({ ...prev, organizationId: e.target.value }))}
                                    className="h-10 border border-slate-200 rounded-md px-3 text-sm md:col-span-2"
                                >
                                    <option value="">소속 조직 없음</option>
                                    {adminOrganizations.map((org) => (
                                        <option key={org.id} value={org.id}>{org.name}</option>
                                    ))}
                                </select>
                                <button
                                    type="submit"
                                    className="h-10 bg-blue-600 hover:bg-blue-700 text-white rounded-md text-sm font-bold md:col-span-2"
                                >
                                    {adminEditingUser
                                        ? '사용자 수정'
                                        : (adminUserForm.inviteUser ? '사용자 초대' : '사용자 생성')}
                                </button>
                            </form>
                            <div className="border rounded-xl overflow-hidden">
                                <div className="max-h-72 overflow-y-auto">
                                    {adminUsers.map((userItem) => (
                                        <div key={userItem.id} className="grid grid-cols-12 gap-2 items-center px-3 py-2 border-b text-sm last:border-b-0">
                                            <div className="col-span-3 truncate">{userItem.email}</div>
                                            <div className="col-span-3 truncate">{userItem.name || '-'}</div>
                                            <div className="col-span-2">{getAdminRoleLabel(userItem.role)}</div>
                                            <div className="col-span-2">{adminOrganizations.find(org => org.id === userItem.organization_id)?.name || '미배정'}</div>
                                            <div className="col-span-2">
                                                {userItem.is_active ? (
                                                    <span className="text-emerald-600 text-[11px] px-2 py-0.5 rounded bg-emerald-50">활성</span>
                                                ) : (
                                                    <span className="text-slate-600 text-[11px] px-2 py-0.5 rounded bg-slate-100">비활성</span>
                                                )}
                                            </div>
                                            <div className="col-span-2 flex gap-2 justify-end">
                                                <button onClick={() => handleEditUser(userItem)} className="px-2 py-1 bg-slate-100 rounded text-slate-700">수정</button>
                                                {userItem.is_active
                                                    ? <button onClick={() => handleDeactivateUser(userItem)} className="px-2 py-1 bg-amber-100 rounded text-amber-700">비활성</button>
                                                    : <button onClick={() => handleDeleteUser(userItem)} className="px-2 py-1 bg-red-100 rounded text-red-700">삭제</button>}
                                            </div>
                                        </div>
                                    ))}
                                    {adminUsers.length === 0 && <div className="p-3 text-sm text-slate-500">사용자 데이터가 없습니다.</div>}
                                </div>
                            </div>
                        </div>
                    )}
                    {adminTab === 'users' && !canManageUsers && (
                        <div className="text-sm text-slate-500">
                            사용자 관리 권한이 없어 사용자 탭을 표시할 수 없습니다.
                        </div>
                    )}

                    {/* Organizations Tab */}
                    {adminTab === 'organizations' && canManageOrganizations && (
                        <div className="space-y-5">
                            <form onSubmit={handleAdminOrganizationSubmit} className="grid grid-cols-1 md:grid-cols-4 gap-3">
                                <input
                                    required
                                    type="text"
                                    value={adminOrganizationForm.name}
                                    onChange={(e) => setAdminOrganizationForm(prev => ({ ...prev, name: e.target.value }))}
                                    className="h-10 border border-slate-200 rounded-md px-3 text-sm"
                                    placeholder="조직명"
                                />
                                <input
                                    required
                                    type="number"
                                    min="0"
                                    value={adminOrganizationForm.quota_storage_gb}
                                    onChange={(e) => setAdminOrganizationForm(prev => ({ ...prev, quota_storage_gb: e.target.value }))}
                                    className="h-10 border border-slate-200 rounded-md px-3 text-sm"
                                    placeholder="스토리지(GB)"
                                />
                                <input
                                    required
                                    type="number"
                                    min="0"
                                    value={adminOrganizationForm.quota_projects}
                                    onChange={(e) => setAdminOrganizationForm(prev => ({ ...prev, quota_projects: e.target.value }))}
                                    className="h-10 border border-slate-200 rounded-md px-3 text-sm"
                                    placeholder="프로젝트 한도"
                                />
                                <button
                                    type="submit"
                                    className="h-10 bg-blue-600 hover:bg-blue-700 text-white rounded-md text-sm font-bold"
                                >
                                    {adminEditingOrganization ? '조직 수정' : '조직 생성'}
                                </button>
                            </form>
                            <div className="border rounded-xl overflow-hidden">
                                <div className="max-h-72 overflow-y-auto">
                                    {adminOrganizations.map((org) => (
                                        <div key={org.id} className="grid grid-cols-12 gap-2 items-center px-3 py-2 border-b text-sm last:border-b-0">
                                            <div className="col-span-4 truncate">{org.name}</div>
                                            <div className="col-span-3">스토리지: {org.quota_storage_gb}GB</div>
                                            <div className="col-span-3">프로젝트: {org.quota_projects}</div>
                                            <div className="col-span-2 flex gap-2 justify-end">
                                                <button onClick={() => handleEditOrganization(org)} className="px-2 py-1 bg-slate-100 rounded text-slate-700">수정</button>
                                                <button onClick={() => handleDeleteOrganization(org)} className="px-2 py-1 bg-red-100 rounded text-red-700">삭제</button>
                                            </div>
                                        </div>
                                    ))}
                                    {adminOrganizations.length === 0 && <div className="p-3 text-sm text-slate-500">조직 데이터가 없습니다.</div>}
                                </div>
                            </div>
                        </div>
                    )}
                    {adminTab === 'organizations' && !canManageOrganizations && (
                        <div className="text-sm text-slate-500">
                            조직 관리 권한이 없어 조직 탭을 표시할 수 없습니다.
                        </div>
                    )}

                    {/* Permissions Tab */}
                    {adminTab === 'permissions' && canManagePermissions && (
                        <div className="space-y-5">
                            <form onSubmit={handleSubmitPermission} className="grid grid-cols-1 md:grid-cols-5 gap-3">
                                <select
                                    value={selectedPermissionProjectId}
                                    onChange={(e) => handlePermissionProjectChange(e.target.value)}
                                    disabled={projects.length === 0}
                                    className="h-10 border border-slate-200 rounded-md px-3 text-sm md:col-span-2"
                                >
                                    <option value="">프로젝트 선택</option>
                                    {projects.map((project) => (
                                        <option key={project.id} value={project.id}>{project.title}</option>
                                    ))}
                                </select>
                                <select
                                    value={selectedPermissionUserId}
                                    onChange={(e) => setSelectedPermissionUserId(e.target.value)}
                                    disabled={adminUsers.length === 0}
                                    className="h-10 border border-slate-200 rounded-md px-3 text-sm md:col-span-2"
                                >
                                    <option value="">사용자 선택</option>
                                    {adminUsers.map((userData) => (
                                        <option key={userData.id} value={userData.id}>{userData.email}</option>
                                    ))}
                                </select>
                                <select
                                    value={selectedPermissionLevel}
                                    onChange={(e) => setSelectedPermissionLevel(e.target.value)}
                                    className="h-10 border border-slate-200 rounded-md px-3 text-sm"
                                >
                                    {(adminPermissionCatalog.project_permissions.length > 0 ? adminPermissionCatalog.project_permissions : [
                                        { value: 'view', label: 'View' },
                                        { value: 'edit', label: 'Edit' },
                                        { value: 'admin', label: 'Admin' },
                                    ]).map((permission) => (
                                        <option key={permission.value} value={permission.value}>{permission.label}</option>
                                    ))}
                                </select>
                                <button
                                    type="submit"
                                    disabled={!selectedPermissionProjectId || !selectedPermissionUserId}
                                    className="h-10 bg-blue-600 hover:bg-blue-700 disabled:bg-blue-300 disabled:cursor-not-allowed text-white rounded-md text-sm font-bold"
                                >
                                    권한 저장
                                </button>
                            </form>
                            {projects.length === 0 && (
                                <div className="rounded-md bg-amber-50 border border-amber-200 px-3 py-2 text-xs text-amber-700">
                                    권한을 부여할 프로젝트가 없습니다.
                                </div>
                            )}
                            {adminUsers.length === 0 && (
                                <div className="rounded-md bg-amber-50 border border-amber-200 px-3 py-2 text-xs text-amber-700">
                                    권한을 부여할 사용자가 없습니다.
                                </div>
                            )}
                            <div className="border rounded-xl overflow-hidden">
                                <div className="max-h-72 overflow-y-auto">
                                    {projectPermissions.map((permission) => (
                                        <div key={permission.id} className="grid grid-cols-12 gap-2 items-center px-3 py-2 border-b text-sm last:border-b-0">
                                            <div className="col-span-4 truncate">{permission.user_email || permission.user_id}</div>
                                            <div className="col-span-3 uppercase">{permission.permission}</div>
                                            <div className="col-span-2 text-slate-500">{new Date(permission.granted_at).toLocaleDateString()}</div>
                                            <div className="col-span-3 flex gap-2 justify-end">
                                                <button onClick={() => handleDeletePermission(permission)} className="px-2 py-1 bg-red-100 rounded text-red-700">권한 삭제</button>
                                            </div>
                                        </div>
                                    ))}
                                    {projectPermissions.length === 0 && (
                                        <div className="p-3 text-sm text-slate-500">
                                            {selectedPermissionProjectId ? '해당 프로젝트에 등록된 권한이 없습니다.' : '프로젝트를 먼저 선택하세요.'}
                                        </div>
                                    )}
                                </div>
                            </div>
                        </div>
                    )}
                    {adminTab === 'permissions' && !canManagePermissions && (
                        <div className="text-sm text-slate-500">
                            프로젝트 권한 관리 권한이 없어 권한 탭을 표시할 수 없습니다.
                        </div>
                    )}
                </div>
            </div>
        </div>
    );
}
