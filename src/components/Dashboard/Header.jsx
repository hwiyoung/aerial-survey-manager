import React from 'react';
import { Map, Bell, User, LogOut } from 'lucide-react';
import { useAuth } from '../../contexts/AuthContext';

export default function Header() {
    const { user, logout } = useAuth();

    return (
        <header className="h-14 bg-white border-b border-slate-200 flex items-center justify-between px-4 z-20 shadow-sm shrink-0">
            <div
                className="flex items-center gap-2 cursor-pointer hover:opacity-80 transition-opacity"
                onClick={() => {
                    // URL 파라미터 초기화하여 깨끗한 상태로 메인 페이지 복귀
                    window.history.pushState({}, '', window.location.pathname);
                    window.location.reload();
                }}
                title="메인 페이지로 이동"
            >
                <div className="bg-blue-600 p-1.5 rounded text-white"><Map size={20} /></div>
                <h1 className="font-bold text-lg text-slate-800 tracking-tight">InnoPAM <span className="font-normal text-slate-500 text-sm hidden sm:inline">| 실감정사영상 생성 플랫폼</span></h1>
            </div>
            <div className="flex items-center gap-4">
                <button className="p-2 text-slate-500 hover:bg-slate-100 rounded-full relative">
                    <Bell size={18} />
                </button>
                <div className="flex items-center gap-2 pl-4 border-l border-slate-200">
                    <div className="w-8 h-8 bg-slate-200 rounded-full flex items-center justify-center text-slate-600">
                        <User size={16} />
                    </div>
                    <span className="text-sm font-medium text-slate-700 hidden md:block">
                        {user?.name || user?.email || '사용자'}님
                    </span>
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
