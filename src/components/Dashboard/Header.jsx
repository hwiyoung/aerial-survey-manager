import React from 'react';
import { Bell, User, LogOut, Shield, ChevronDown } from 'lucide-react';
import { useAuth } from '../../contexts/AuthContext';

export default function Header({
    onLogoClick,
    onOpenAdminMenu,
    canManageUsers,
    canManageOrganizations,
    canManagePermissions,
}) {
    const { user, role, isAdmin, isManager, logout } = useAuth();
    const hasAdminMenu = canManageUsers || canManageOrganizations || canManagePermissions;
    const roleLabel =
        role === 'admin' ? '관리자' : role === 'editor' ? '편집자' : '뷰어';
    const roleClass = isAdmin
        ? 'bg-rose-100 text-rose-700'
        : isManager
            ? 'bg-sky-100 text-sky-700'
            : 'bg-slate-100 text-slate-700';

    return (
        <header className="h-14 bg-white border-b border-slate-200 flex items-center justify-between px-4 z-20 shadow-sm shrink-0">
            <div
                className="flex items-center gap-2 cursor-pointer hover:opacity-80 transition-opacity"
                onClick={() => {
                    if (onLogoClick) {
                        // 상태 기반 네비게이션으로 대시보드 복귀
                        onLogoClick();
                    } else {
                        // 폴백: URL 파라미터 초기화하여 깨끗한 상태로 메인 페이지 복귀
                        window.history.pushState({}, '', window.location.pathname);
                        window.location.reload();
                    }
                }}
                title="메인 페이지로 이동"
            >
                <img src="/siqms_mark.png" alt="SIQMS" className="w-[64px] h-[64px] object-contain" />
                <h1 className="font-bold text-lg text-slate-800 tracking-tight">
                    공간정보품질관리원 <span className="font-normal text-slate-500">| AI 기반 품질검증 지원 시스템 - 실감정사영상 생성 플랫폼</span>
                </h1>
            </div>
            <div className="flex items-center gap-4">
                {hasAdminMenu && (
                    <button
                        onClick={() => onOpenAdminMenu?.('users')}
                        className="h-10 px-3 rounded-lg border border-slate-200 bg-slate-50 hover:bg-slate-100 text-xs font-bold text-slate-700 flex items-center gap-1.5"
                        title="관리 메뉴 열기"
                    >
                        <Shield size={14} />
                        <span>관리</span>
                        <ChevronDown size={12} className="text-slate-500" />
                    </button>
                )}
                <button className="p-2 text-slate-500 hover:bg-slate-100 rounded-full relative">
                    <Bell size={18} />
                </button>
                <div className="flex items-center gap-2 pl-4 border-l border-slate-200">
                <div className="w-8 h-8 bg-slate-200 rounded-full flex items-center justify-center text-slate-600">
                    <User size={16} />
                </div>
                    <div className="leading-tight hidden md:block">
                        <div className="text-sm font-medium text-slate-700">
                        {user?.name || user?.email || '사용자'}님
                        </div>
                        <div className={`inline-flex mt-0.5 px-2 py-0.5 rounded-full text-[10px] font-bold ${roleClass}`}>
                            {roleLabel}
                        </div>
                    </div>
                    <button
                        onClick={logout}
                        className="p-2 text-slate-400 hover:text-red-500 hover:bg-red-50 rounded-full transition-colors"
                        title="로그아웃"
                    >
                        <LogOut size={16} />
                    </button>
                </div>
            </div>
        </header>
    );
}
