import React, { useState, useMemo, useRef, useEffect } from 'react';
import {
    UploadCloud, FolderPlus, Search, CheckSquare, Square,
    ChevronRight, ChevronDown, MoreHorizontal, Edit2, Trash2,
    Play, Download, FileImage, Eye, Loader2
} from 'lucide-react';

const REGIONS = [
    '수도권북부 권역',
    '수도권남부 권역',
    '강원 권역',
    '충청 권역',
    '전라동부 권역',
    '전라서부 권역',
    '경북 권역',
    '경남 권역',
    '제주 권역'
];

// 프로젝트 상태 표시 헬퍼 함수
function getProjectStatusDisplay(project) {
    const status = project.status;
    const imageCount = project.imageCount || project.image_count || 0;
    const uploadCompleted = project.upload_completed_count ?? imageCount;
    const uploadInProgress = project.upload_in_progress ?? false;

    // 업로드 진행 중
    if (uploadInProgress || (status === 'pending' && uploadCompleted < imageCount && imageCount > 0)) {
        return {
            text: `업로드 중 (${uploadCompleted}/${imageCount})`,
            style: 'bg-amber-50 text-amber-600 border-amber-200',
            icon: 'uploading'
        };
    }

    // 상태별 표시
    switch (status) {
        case 'completed':
        case '완료':
            return { text: '완료', style: 'bg-emerald-50 text-emerald-600 border-emerald-100', icon: null };
        case 'processing':
        case 'queued':
        case '진행중':
            return { text: '진행중', style: 'bg-blue-50 text-blue-600 border-blue-100', icon: null };
        case 'error':
        case '오류':
            return { text: '오류', style: 'bg-red-50 text-red-600 border-red-100', icon: null };
        case 'pending':
        case '대기':
        default:
            return { text: '대기', style: 'bg-slate-50 text-slate-500 border-slate-100', icon: null };
    }
}

export function ProjectItem({ project, isSelected, isChecked, sizeMode = 'normal', onSelect, onOpenInspector, onToggle, onDelete, onRename, onOpenProcessing, onOpenExport, draggable = false }) {
    const [isEditing, setIsEditing] = useState(false);
    const [editValue, setEditValue] = useState(project.title);
    const clickTimeoutRef = useRef(null);
    const CLICK_DELAY = 250;

    const handleDragStart = (e) => {
        if (!draggable) return;
        e.dataTransfer.setData('projectId', project.id);
        e.dataTransfer.effectAllowed = 'move';
    };

    const handleClick = (e) => {
        if (clickTimeoutRef.current) {
            clearTimeout(clickTimeoutRef.current);
            clickTimeoutRef.current = null;
        }
        clickTimeoutRef.current = setTimeout(() => {
            onSelect();
            clickTimeoutRef.current = null;
        }, CLICK_DELAY);
    };

    const handleDoubleClick = (e) => {
        if (clickTimeoutRef.current) {
            clearTimeout(clickTimeoutRef.current);
            clickTimeoutRef.current = null;
        }
        onSelect();
        onOpenInspector();
    };

    const handleDelete = (e) => {
        e.stopPropagation();
        if (window.confirm(`"${project.title}" 프로젝트를 삭제하시겠습니까?\n\n이 작업은 되돌릴 수 없으며, 모든 이미지 및 관련 데이터가 삭제됩니다.`)) {
            onDelete();
        }
    };

    const handleRenameSubmit = async (e) => {
        e.stopPropagation();
        if (editValue.trim() && editValue !== project.title) {
            await onRename(editValue);
        }
        setIsEditing(false);
    };

    const handleRenameCancel = (e) => {
        e.stopPropagation();
        setEditValue(project.title);
        setIsEditing(false);
    };

    const handleProcessing = (e) => {
        e.stopPropagation();
        onOpenProcessing();
    };

    const handleExport = (e) => {
        e.stopPropagation();
        onOpenExport();
    };

    useEffect(() => {
        return () => {
            if (clickTimeoutRef.current) {
                clearTimeout(clickTimeoutRef.current);
            }
        };
    }, []);

    if (sizeMode === 'compact') {
        return (
            <div onClick={handleClick} onDoubleClick={handleDoubleClick} draggable={draggable} onDragStart={handleDragStart} className={`relative flex items-center gap-2 p-2 rounded-lg cursor-pointer transition-all border group ${isSelected ? "bg-blue-50 border-blue-200 shadow-sm" : "bg-white hover:bg-slate-50 border-transparent"}`}>
                <div onClick={(e) => { e.stopPropagation(); onToggle(); }} className="text-slate-400 hover:text-blue-600 cursor-pointer shrink-0">{isChecked ? <CheckSquare size={16} className="text-blue-600" /> : <Square size={16} />}</div>
                {isEditing ? (
                    <input autoFocus value={editValue} onClick={e => e.stopPropagation()} onChange={e => setEditValue(e.target.value)} onKeyDown={e => { if (e.key === 'Enter') handleRenameSubmit(e); if (e.key === 'Escape') handleRenameCancel(e); }} onBlur={handleRenameSubmit} className="text-sm font-bold border rounded px-1 flex-1 min-w-0" />
                ) : (
                    <h4 className="text-sm font-bold text-slate-800 truncate flex-1 min-w-0">{project.title}</h4>
                )}
                <span className="text-[10px] text-slate-400 flex items-center gap-0.5 shrink-0"><FileImage size={10} /> {project.imageCount || project.image_count || 0}</span>
                {(() => {
                    const statusInfo = getProjectStatusDisplay(project);
                    return (
                        <span className={`text-[10px] px-1.5 py-0.5 rounded-full font-medium border shrink-0 flex items-center gap-1 ${statusInfo.style}`}>
                            {statusInfo.icon === 'uploading' && <Loader2 size={10} className="animate-spin" />}
                            {statusInfo.text}
                        </span>
                    );
                })()}
                <div className="opacity-0 group-hover:opacity-100 flex items-center gap-1 transition-opacity">
                    <button onClick={handleProcessing} className="p-1.5 text-blue-600 hover:bg-blue-100 rounded transition-colors" title="처리 시작"><Play size={14} /></button>
                    <button onClick={handleExport} disabled={project.status !== '완료'} className="p-1.5 text-slate-500 hover:bg-slate-100 rounded transition-colors disabled:opacity-30" title="내보내기"><Download size={14} /></button>
                </div>
            </div>
        );
    }

    if (sizeMode === 'expanded') {
        return (
            <div onClick={handleClick} onDoubleClick={handleDoubleClick} draggable={draggable} onDragStart={handleDragStart} className={`relative p-3 rounded-lg cursor-pointer transition-all border group ${isSelected ? "bg-blue-50 border-blue-200 shadow-sm z-10" : "bg-white hover:bg-slate-50 border-transparent"}`}>
                <div className="flex items-center gap-3">
                    <div onClick={(e) => { e.stopPropagation(); onToggle(); }} className="text-slate-400 hover:text-blue-600 cursor-pointer shrink-0">{isChecked ? <CheckSquare size={18} className="text-blue-600" /> : <Square size={18} />}</div>
                    {isEditing ? (
                        <input autoFocus value={editValue} onClick={e => e.stopPropagation()} onChange={e => setEditValue(e.target.value)} onKeyDown={e => { if (e.key === 'Enter') handleRenameSubmit(e); if (e.key === 'Escape') handleRenameCancel(e); }} onBlur={handleRenameSubmit} className="text-sm font-bold border rounded px-1 flex-1 min-w-0" />
                    ) : (
                        <h4 className="text-sm font-bold text-slate-800 truncate min-w-0 max-w-[200px]">{project.title}</h4>
                    )}
                    <div className="flex items-center gap-2 text-xs text-slate-500 flex-wrap">
                        <span className="bg-slate-100 px-1.5 py-0.5 rounded">{project.region}</span>
                        <span className="text-slate-300">|</span>
                        <span className="truncate max-w-[100px]">{project.company}</span>
                        <span className="text-slate-300">|</span>
                        <span className="flex items-center gap-1"><FileImage size={12} /> {project.imageCount || 0}장</span>
                        {project.area && <><span className="text-slate-300">|</span><span className="font-bold text-blue-600"> {project.area.toFixed(2)} km²</span></>}
                        {project.startDate && <><span className="text-slate-300">|</span><span>📅 {project.startDate}</span></>}
                    </div>
                    <div className="flex-1" />
                    {(() => {
                        const statusInfo = getProjectStatusDisplay(project);
                        return (
                            <span className={`text-[10px] px-1.5 py-0.5 rounded-full font-medium border shrink-0 flex items-center gap-1 ${statusInfo.style}`}>
                                {statusInfo.icon === 'uploading' && <Loader2 size={10} className="animate-spin" />}
                                {statusInfo.text}
                            </span>
                        );
                    })()}
                    <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-all">
                        <button onClick={(e) => { e.stopPropagation(); setIsEditing(true); }} className="p-1 text-slate-400 hover:text-blue-600 hover:bg-blue-50 rounded" title="이름 변경">
                            <Edit2 size={14} />
                        </button>
                        <button onClick={handleDelete} className="p-1 text-slate-400 hover:text-red-500 hover:bg-red-50 rounded transition-all shrink-0" title="프로젝트 삭제">
                            <Trash2 size={14} />
                        </button>
                    </div>
                </div>
                {(project.status === '진행중' || project.status === 'processing') && (
                    <div className="mt-2 ml-8">
                        <div className="flex justify-between text-[10px] text-slate-500 mb-0.5">
                            <span>처리 중...</span>
                            <span>{project.progress || 0}%</span>
                        </div>
                        <div className="h-1.5 bg-slate-200 rounded-full overflow-hidden">
                            <div className="h-full bg-blue-500 rounded-full transition-all duration-500" style={{ width: `${project.progress || 0}%` }} />
                        </div>
                    </div>
                )}
                {(project.status === '오류' || project.status === 'error') && project.error_message && (
                    <div className="mt-2 ml-8 p-2 bg-red-50 border border-red-200 rounded-lg">
                        <div className="flex items-start gap-2">
                            <span className="text-red-500 text-xs">⚠</span>
                            <p className="text-[11px] text-red-700 leading-relaxed">{project.error_message}</p>
                        </div>
                    </div>
                )}
                <div className="flex gap-2 mt-2 ml-8">
                    <button onClick={handleProcessing} className="flex items-center justify-center gap-1 px-3 py-1.5 text-xs font-medium bg-blue-100 hover:bg-blue-200 text-blue-700 rounded transition-colors" title="처리 옵션 설정"><Play size={12} /> 처리</button>
                    <button onClick={handleExport} disabled={project.status !== '완료'} className="flex items-center justify-center gap-1 px-3 py-1.5 text-xs font-medium bg-slate-100 hover:bg-slate-200 text-slate-700 rounded transition-colors disabled:opacity-40 disabled:cursor-not-allowed" title="정사영상 내보내기"><Download size={12} /> 내보내기</button>
                </div>
            </div>
        );
    }

    return (
        <div onClick={handleClick} onDoubleClick={handleDoubleClick} draggable={draggable} onDragStart={handleDragStart} className={`relative flex flex-col gap-2 p-3 rounded-lg cursor-pointer transition-all border group ${isSelected ? "bg-blue-50 border-blue-200 shadow-sm z-10" : "bg-white hover:bg-slate-50 border-transparent"}`}>
            <div className="flex items-start gap-3">
                <div onClick={(e) => { e.stopPropagation(); onToggle(); }} className="mt-1 text-slate-400 hover:text-blue-600 cursor-pointer">{isChecked ? <CheckSquare size={18} className="text-blue-600" /> : <Square size={18} />}</div>
                <div className="flex-1 min-w-0">
                    <div className="flex justify-between items-start">
                        {isEditing ? (
                            <input autoFocus value={editValue} onClick={e => e.stopPropagation()} onChange={e => setEditValue(e.target.value)} onKeyDown={e => { if (e.key === 'Enter') handleRenameSubmit(e); if (e.key === 'Escape') handleRenameCancel(e); }} onBlur={handleRenameSubmit} className="text-sm font-bold border rounded px-1 flex-1 min-w-0 mr-2" />
                        ) : (
                            <h4 className="text-sm font-bold text-slate-800 truncate">{project.title}</h4>
                        )}
                        <div className="flex items-center gap-1">
                            {(() => {
                                const statusInfo = getProjectStatusDisplay(project);
                                return (
                                    <span className={`text-[10px] px-1.5 py-0.5 rounded-full font-medium border shrink-0 flex items-center gap-1 ${statusInfo.style}`}>
                                        {statusInfo.icon === 'uploading' && <Loader2 size={10} className="animate-spin" />}
                                        {statusInfo.text}
                                    </span>
                                );
                            })()}
                            {(project.status === '완료' || project.status === 'completed') && (
                                <span className="flex items-center gap-1 text-[9px] font-bold bg-emerald-500 text-white px-1.5 py-0.5 rounded shadow-sm animate-pulse whitespace-nowrap"><Eye size={10} /> 결과</span>
                            )}
                            <button onClick={(e) => { e.stopPropagation(); setIsEditing(true); }} className="opacity-0 group-hover:opacity-100 p-1 text-slate-400 hover:text-blue-600 hover:bg-blue-50 rounded" title="이름 변경"><Edit2 size={14} /></button>
                            <button onClick={handleDelete} className="opacity-0 group-hover:opacity-100 p-1 text-slate-400 hover:text-red-500 hover:bg-red-50 rounded transition-all" title="프로젝트 삭제"><Trash2 size={14} /></button>
                        </div>
                    </div>
                    <div className="flex items-center gap-2 text-xs text-slate-500 mt-1"><span className="bg-slate-100 px-1.5 rounded">{project.region}</span><span className="text-slate-300">|</span><span>{project.company}</span></div>
                </div>
            </div>
            <div className={`flex gap-2 pl-7 ${isSelected ? 'opacity-100' : 'opacity-0 group-hover:opacity-100'} transition-opacity`}>
                <button onClick={handleProcessing} className="flex-1 flex items-center justify-center gap-1 px-2 py-1.5 text-xs font-medium bg-blue-100 hover:bg-blue-200 text-blue-700 rounded transition-colors" title="처리 옵션 설정"><Play size={12} /> 처리</button>
                <button onClick={handleExport} disabled={project.status !== '완료'} className="flex-1 flex items-center justify-center gap-1 px-2 py-1.5 text-xs font-medium bg-slate-100 hover:bg-slate-200 text-slate-700 rounded transition-colors disabled:opacity-40 disabled:cursor-not-allowed" title="정사영상 내보내기"><Download size={12} /> 내보내기</button>
            </div>
        </div>
    );
}

function GroupItem({ group, projects, isExpanded, onToggle, onDrop, onEdit, onDelete, onRenameProject, selectedProjectId, onSelectProject, onOpenInspector, checkedProjectIds, onToggleCheck, sizeMode, onOpenProcessing, onOpenExport, onDeleteProject, onFilter, isActive }) {
    const [isDragOver, setIsDragOver] = useState(false);
    const menuRef = useRef(null);
    const [showMenu, setShowMenu] = useState(false);
    const groupProjects = projects.filter(p => p.group_id === group.id);

    useEffect(() => {
        if (!showMenu) return;
        const handleClickOutside = (e) => {
            if (menuRef.current && !menuRef.current.contains(e.target)) {
                setShowMenu(false);
            }
        };
        document.addEventListener('mousedown', handleClickOutside);
        return () => document.removeEventListener('mousedown', handleClickOutside);
    }, [showMenu]);

    const handleDragOver = (e) => { e.preventDefault(); setIsDragOver(true); };
    const handleDragLeave = () => setIsDragOver(false);
    const handleDrop = (e) => {
        e.preventDefault();
        setIsDragOver(false);
        const projectId = e.dataTransfer.getData('projectId');
        if (projectId) onDrop(projectId, group.id);
    };

    return (
        <div className="mb-1">
            <div className={`flex items-center gap-2 px-2 py-1.5 rounded-md cursor-pointer transition-colors group ${isDragOver ? 'bg-blue-100 ring-2 ring-blue-400' : isActive ? 'bg-blue-50 ring-1 ring-blue-300' : 'hover:bg-slate-100'}`} onDragOver={handleDragOver} onDragLeave={handleDragLeave} onDrop={handleDrop}>
                <button onClick={onToggle} className="p-0.5 hover:bg-slate-200 rounded">{isExpanded ? <ChevronDown size={14} className="text-slate-500" /> : <ChevronRight size={14} className="text-slate-500" />}</button>
                <div className="w-4 h-4 rounded flex-shrink-0" style={{ backgroundColor: group.color || '#94a3b8' }} />
                <span className={`text-sm font-medium flex-1 truncate cursor-pointer hover:text-blue-600 ${isActive ? 'text-blue-600' : 'text-slate-700'}`} onClick={(e) => { e.stopPropagation(); onFilter && onFilter(group.id); }}>{group.name}</span>
                <span className="text-xs text-slate-400">{groupProjects.length}</span>
                <div className="relative" ref={menuRef}>
                    <button onClick={(e) => { e.stopPropagation(); setShowMenu(!showMenu); }} className="p-1 hover:bg-slate-200 rounded opacity-0 group-hover:opacity-100"><MoreHorizontal size={14} className="text-slate-400" /></button>
                    {showMenu && (
                        <div className="absolute right-0 top-6 bg-white border border-slate-200 rounded-md shadow-lg z-50 py-1 min-w-[120px]">
                            <button onClick={(e) => { e.stopPropagation(); onEdit(group); setShowMenu(false); }} className="w-full px-3 py-1.5 text-left text-sm hover:bg-slate-100 flex items-center gap-2"><Edit2 size={14} /> 수정</button>
                            <button onClick={(e) => { e.stopPropagation(); onDelete(group); setShowMenu(false); }} className="w-full px-3 py-1.5 text-left text-sm hover:bg-red-50 text-red-600 flex items-center gap-2"><Trash2 size={14} /> 삭제</button>
                        </div>
                    )}
                </div>
            </div>
            {isExpanded && groupProjects.length > 0 && (
                <div className="pl-6 space-y-1 mt-1">
                    {groupProjects.map(project => (
                        <ProjectItem key={project.id} project={project} isSelected={project.id === selectedProjectId} isChecked={checkedProjectIds.has(project.id)} sizeMode={sizeMode} onSelect={() => onSelectProject(project.id)} onOpenInspector={() => onOpenInspector(project.id)} onToggle={() => onToggleCheck(project.id)} onDelete={() => onDeleteProject(project.id)} onRename={(newName) => onRenameProject(project.id, newName)} onOpenProcessing={() => onOpenProcessing(project.id)} onOpenExport={() => onOpenExport(project.id)} draggable />
                    ))}
                </div>
            )}
        </div>
    );
}

export default function Sidebar({ width, isResizing = false, projects, selectedProjectId, checkedProjectIds, onSelectProject, onOpenInspector, onToggleCheck, onOpenUpload, onBulkExport, onSelectMultiple, onDeleteProject, onRenameProject, onBulkDelete, onOpenProcessing, onOpenExport, groups = [], expandedGroupIds = new Set(), onToggleGroupExpand, onMoveProjectToGroup, onCreateGroup, onEditGroup, onDeleteGroup, activeGroupId = null, onFilterGroup, searchTerm, onSearchTermChange, regionFilter, onRegionFilterChange }) {
    const [isDragOverUngrouped, setIsDragOverUngrouped] = useState(false);
    const sizeMode = useMemo(() => {
        if (width < 400) return 'compact';
        if (width < 600) return 'normal';
        return 'expanded';
    }, [width]);

    const filteredProjects = projects.filter(p => {
        const matchText = p.title.toLowerCase().includes(searchTerm.toLowerCase()) || p.company.includes(searchTerm);
        const matchRegion = regionFilter === 'ALL' || p.region === regionFilter;
        return matchText && matchRegion;
    });

    const ungroupedProjects = filteredProjects.filter(p => !p.group_id);
    const isAllSelected = filteredProjects.length > 0 && filteredProjects.every(p => checkedProjectIds.has(p.id));

    const handleToggleAll = () => {
        const ids = filteredProjects.map(p => p.id);
        onSelectMultiple(ids, !isAllSelected);
    };

    const handleDragOverUngrouped = (e) => { e.preventDefault(); setIsDragOverUngrouped(true); };
    const handleDragLeaveUngrouped = () => setIsDragOverUngrouped(false);
    const handleDropUngrouped = (e) => {
        e.preventDefault();
        setIsDragOverUngrouped(false);
        const projectId = e.dataTransfer.getData('projectId');
        if (projectId && onMoveProjectToGroup) onMoveProjectToGroup(projectId, null);
    };

    return (
        <aside className={`bg-white border-r border-slate-200 flex flex-col h-full z-10 shadow-sm shrink-0 relative ${isResizing ? '' : 'transition-[width] duration-150 ease-out'}`} style={{ width: width, willChange: isResizing ? 'width' : 'auto' }}>
            <div className="p-4 pb-2 flex gap-2">
                <button onClick={onOpenUpload} className="flex-1 bg-blue-600 hover:bg-blue-700 text-white py-3 rounded-lg flex items-center justify-center gap-2 font-bold shadow-md transition-all active:scale-95"><UploadCloud size={20} /><span>새 프로젝트</span></button>
                {onCreateGroup && <button onClick={onCreateGroup} className="px-3 bg-slate-100 hover:bg-slate-200 text-slate-600 rounded-lg flex items-center justify-center transition-all" title="새 폴더"><FolderPlus size={20} /></button>}
            </div>
            <div className="p-4 pt-2 border-b border-slate-200 space-y-3">
                <div className="relative"><Search className="absolute left-3 top-2.5 text-slate-400" size={16} /><input type="text" placeholder="검색..." className="w-full pl-9 pr-3 py-2 bg-slate-50 border border-slate-200 rounded-md text-sm" value={searchTerm} onChange={(e) => onSearchTermChange(e.target.value)} /></div>
                <select className="w-full p-2 bg-slate-50 border border-slate-200 rounded-md text-sm text-slate-600" value={regionFilter} onChange={(e) => onRegionFilterChange(e.target.value)} >
                    <option value="ALL">전체 권역</option>
                    {REGIONS.map(r => <option key={r} value={r}>{r}</option>)}
                </select>
            </div>
            <div className="px-4 py-2 border-b border-slate-100 flex items-center gap-2 bg-slate-50 text-xs font-bold text-slate-500">
                <button onClick={handleToggleAll} className="flex items-center gap-2 hover:text-blue-600 transition-colors">
                    {isAllSelected ? <CheckSquare size={16} className="text-blue-600" /> : <Square size={16} />}
                    <span>전체 선택 ({filteredProjects.length}개)</span>
                </button>
            </div>
            <div className="flex-1 overflow-y-auto custom-scrollbar">
                <div className="p-2 space-y-1">
                    {groups.map(group => (
                        <GroupItem key={group.id} group={group} projects={filteredProjects} isExpanded={expandedGroupIds.has(group.id)} onToggle={() => onToggleGroupExpand && onToggleGroupExpand(group.id)} onDrop={onMoveProjectToGroup} onEdit={onEditGroup} onDelete={() => onDeleteGroup && onDeleteGroup(group.id)} onRenameProject={onRenameProject} selectedProjectId={selectedProjectId} onSelectProject={onSelectProject} onOpenInspector={onOpenInspector} checkedProjectIds={checkedProjectIds} onToggleCheck={onToggleCheck} sizeMode={sizeMode} onOpenProcessing={onOpenProcessing} onOpenExport={onOpenExport} onDeleteProject={onDeleteProject} onFilter={onFilterGroup} isActive={activeGroupId === group.id} />
                    ))}
                    {ungroupedProjects.length > 0 && (
                        <div className={`mt-2 pt-2 border-t border-dashed border-slate-200 ${isDragOverUngrouped ? 'bg-blue-50 ring-2 ring-blue-300 rounded' : ''}`} onDragOver={handleDragOverUngrouped} onDragLeave={handleDragLeaveUngrouped} onDrop={handleDropUngrouped} >
                            {groups.length > 0 && <div className="text-xs text-slate-400 px-2 py-1 font-medium">미분류 프로젝트</div>}
                            {ungroupedProjects.map(project => (
                                <ProjectItem key={project.id} project={project} isSelected={project.id === selectedProjectId} isChecked={checkedProjectIds.has(project.id)} sizeMode={sizeMode} draggable={true} onSelect={() => onSelectProject(project.id)} onOpenInspector={() => onOpenInspector(project.id)} onToggle={() => onToggleCheck(project.id)} onDelete={() => onDeleteProject(project.id)} onRename={(newName) => onRenameProject(project.id, newName)} onOpenProcessing={() => onOpenProcessing(project.id)} onOpenExport={() => onOpenExport(project.id)} />
                            ))}
                        </div>
                    )}
                    {filteredProjects.length === 0 && <div className="text-center text-slate-400 py-8 text-sm">프로젝트가 없습니다</div>}
                </div>
            </div>
            {checkedProjectIds.size > 0 && (
                <div className="p-4 border-t border-slate-200 bg-slate-50 animate-in slide-in-from-bottom duration-200 space-y-2">
                    <button onClick={onBulkExport} className="w-full flex items-center justify-center gap-2 bg-slate-800 hover:bg-slate-900 text-white py-2.5 rounded-lg text-sm font-bold shadow-md transition-all">
                        <Download size={16} className="text-white" />
                        <span>선택한 {checkedProjectIds.size}건 정사영상 내보내기</span>
                    </button>
                    <button onClick={onBulkDelete} className="w-full flex items-center justify-center gap-2 bg-red-600 hover:bg-red-700 text-white py-2.5 rounded-lg text-sm font-bold shadow-md transition-all">
                        <Trash2 size={16} className="text-white" />
                        <span>선택한 {checkedProjectIds.size}건 삭제</span>
                    </button>
                </div>
            )}
        </aside>
    );
}
