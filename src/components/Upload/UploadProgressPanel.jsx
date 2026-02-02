import React, { useEffect, useRef, useMemo } from 'react';
import { UploadCloud, CheckCircle2, AlertTriangle, Loader2, X, ChevronDown, ChevronRight } from 'lucide-react';

export default function UploadProgressPanel({ uploads, onAbortAll, onRestore }) {
    const hasNotified = useRef(false);
    const [collapsedProjects, setCollapsedProjects] = React.useState(new Set());

    // 프로젝트별로 업로드 그룹화
    const uploadsByProject = useMemo(() => {
        if (!uploads || uploads.length === 0) return {};
        return uploads.reduce((acc, upload) => {
            const projectId = upload.projectId || 'unknown';
            if (!acc[projectId]) {
                acc[projectId] = {
                    projectId,
                    projectTitle: upload.projectTitle || '알 수 없는 프로젝트',
                    uploads: []
                };
            }
            acc[projectId].uploads.push(upload);
            return acc;
        }, {});
    }, [uploads]);

    const projectGroups = useMemo(() => Object.values(uploadsByProject), [uploadsByProject]);
    const isMultiProject = projectGroups.length > 1;

    // 전체 통계
    const uploadStats = useMemo(() => {
        if (!uploads || uploads.length === 0) {
            return {
                completedCount: 0,
                errorCount: 0,
                interruptedCount: 0,
                isAllDone: true,
                totalProgress: 0,
                hasErrors: false,
                hasInterrupted: false,
            };
        }
        const completedCount = uploads.filter(u => u.status === 'completed').length;
        const errorCount = uploads.filter(u => u.status === 'error').length;
        const interruptedCount = uploads.filter(u => u.status === 'interrupted').length;
        const isAllDone = completedCount + errorCount + interruptedCount === uploads.length;
        const totalProgress = uploads.reduce((acc, u) => acc + (u.progress || 0), 0) / uploads.length;

        return {
            completedCount,
            errorCount,
            interruptedCount,
            isAllDone,
            totalProgress,
            hasErrors: errorCount > 0,
            hasInterrupted: interruptedCount > 0,
        };
    }, [uploads]);

    const { completedCount, errorCount, interruptedCount, isAllDone, totalProgress, hasErrors, hasInterrupted } = uploadStats;

    // 업로드 완료 시 실패한 이미지가 있으면 알림 표시
    useEffect(() => {
        if (!uploads || uploads.length === 0) return;

        if (isAllDone && !hasNotified.current) {
            hasNotified.current = true;
            if (errorCount > 0) {
                setTimeout(() => {
                    alert(
                        `업로드가 완료되었습니다.\n\n` +
                        `✅ 성공: ${completedCount}개\n` +
                        `❌ 실패: ${errorCount}개\n\n` +
                        `실패한 이미지는 처리에서 제외됩니다.\n` +
                        `${completedCount}개의 이미지만으로 처리를 진행할 수 있습니다.`
                    );
                }, 500);
            }
        }
    }, [uploads, isAllDone, errorCount, completedCount]);

    // uploads가 리셋되면 알림 상태도 리셋
    useEffect(() => {
        if (!uploads || uploads.length === 0) {
            hasNotified.current = false;
        }
    }, [uploads]);

    // Early return은 모든 hooks 이후에
    if (!uploads || uploads.length === 0) return null;

    const headerBgClass = isAllDone
        ? (hasErrors ? "bg-red-600" : (hasInterrupted ? "bg-amber-600" : "bg-green-600"))
        : "bg-slate-900";

    const toggleProjectCollapse = (projectId) => {
        setCollapsedProjects(prev => {
            const next = new Set(prev);
            if (next.has(projectId)) {
                next.delete(projectId);
            } else {
                next.add(projectId);
            }
            return next;
        });
    };

    // 프로젝트별 통계 계산
    const getProjectStats = (projectUploads) => {
        const completed = projectUploads.filter(u => u.status === 'completed').length;
        const errors = projectUploads.filter(u => u.status === 'error').length;
        const total = projectUploads.length;
        const progress = projectUploads.reduce((acc, u) => acc + (u.progress || 0), 0) / total;
        const isDone = completed + errors === total;
        return { completed, errors, total, progress, isDone };
    };

    return (
        <div className="fixed bottom-6 right-6 z-[2000] w-96 bg-white rounded-xl shadow-2xl border border-slate-200 overflow-hidden animate-in slide-in-from-bottom-5">
            <div className={`${headerBgClass} px-4 py-3 flex items-center justify-between`}>
                <div className="flex items-center gap-2 text-white min-w-0">
                    {isAllDone ? (
                        hasErrors ? (
                            <AlertTriangle size={18} className="text-white shrink-0" />
                        ) : (
                            <CheckCircle2 size={18} className="text-white shrink-0" />
                        )
                    ) : (
                        <UploadCloud size={18} className="animate-pulse text-blue-400 shrink-0" />
                    )}
                    <div className="min-w-0">
                        {isMultiProject ? (
                            <div className="text-[10px] text-white/70">{projectGroups.length}개 프로젝트</div>
                        ) : projectGroups[0]?.projectTitle && (
                            <div className="text-[10px] text-white/70 truncate">{projectGroups[0].projectTitle}</div>
                        )}
                        <span className="font-bold text-sm">
                            {isAllDone
                                ? (hasErrors
                                    ? `업로드 완료 (${errorCount}개 실패)`
                                    : (hasInterrupted
                                        ? `업로드 중단됨 (${interruptedCount}개)`
                                        : `업로드 완료 (${completedCount}개)`))
                                : `이미지 업로드 중 (${completedCount}/${uploads.length})`
                            }
                        </span>
                    </div>
                </div>
                <div className="flex items-center gap-2">
                    {!isAllDone && (
                        <button
                            onClick={onAbortAll}
                            className="text-xs text-slate-400 hover:text-white transition-colors"
                        >
                            전체취소
                        </button>
                    )}
                    <button onClick={onRestore} className="text-white hover:bg-white/10 p-1 rounded">
                        <X size={16} />
                    </button>
                </div>
            </div>

            {/* 업로드 완료 후 에러가 있으면 요약 표시 */}
            {isAllDone && hasErrors && (
                <div className="bg-red-50 px-4 py-2 border-b border-red-200">
                    <div className="text-xs text-red-800">
                        <span className="font-semibold">⚠️ {errorCount}개 이미지 업로드 실패</span>
                        <p className="mt-1 text-red-700">
                            실패한 이미지는 처리에서 제외됩니다.
                        </p>
                    </div>
                </div>
            )}

            {/* 업로드 중단됨 메시지 */}
            {isAllDone && hasInterrupted && !hasErrors && (
                <div className="bg-amber-50 px-4 py-2 border-b border-amber-200">
                    <div className="text-xs text-amber-800">
                        <span className="font-semibold">⚠️ 페이지 새로고침으로 업로드가 중단되었습니다</span>
                        <p className="mt-1 text-amber-700">
                            {completedCount > 0
                                ? `${completedCount}개 완료됨. 나머지 이미지는 다시 업로드해야 합니다.`
                                : '이미지를 다시 업로드해 주세요.'}
                        </p>
                    </div>
                </div>
            )}

            <div className="max-h-80 overflow-y-auto p-2 bg-slate-50">
                {isMultiProject ? (
                    // 멀티 프로젝트 모드: 프로젝트별로 그룹화하여 표시
                    projectGroups.map((group) => {
                        const stats = getProjectStats(group.uploads);
                        const isCollapsed = collapsedProjects.has(group.projectId);

                        return (
                            <div key={group.projectId} className="mb-2 last:mb-0">
                                {/* 프로젝트 헤더 */}
                                <button
                                    onClick={() => toggleProjectCollapse(group.projectId)}
                                    className="w-full bg-white p-2 rounded-lg border border-slate-200 flex items-center gap-2 hover:bg-slate-50"
                                >
                                    {isCollapsed ? (
                                        <ChevronRight size={14} className="text-slate-400" />
                                    ) : (
                                        <ChevronDown size={14} className="text-slate-400" />
                                    )}
                                    <div className="flex-1 text-left min-w-0">
                                        <div className="text-xs font-semibold text-slate-700 truncate">
                                            {group.projectTitle}
                                        </div>
                                        <div className="text-[10px] text-slate-500">
                                            {stats.completed}/{stats.total} 완료
                                            {stats.errors > 0 && <span className="text-red-500 ml-1">({stats.errors} 실패)</span>}
                                        </div>
                                    </div>
                                    {stats.isDone ? (
                                        stats.errors > 0 ? (
                                            <AlertTriangle size={14} className="text-amber-500 shrink-0" />
                                        ) : (
                                            <CheckCircle2 size={14} className="text-green-500 shrink-0" />
                                        )
                                    ) : (
                                        <div className="flex items-center gap-2">
                                            <span className="text-[10px] text-blue-600 font-medium">{Math.round(stats.progress)}%</span>
                                            <Loader2 size={14} className="text-blue-500 animate-spin shrink-0" />
                                        </div>
                                    )}
                                </button>

                                {/* 개별 파일 목록 (접힌 상태가 아닐 때만) */}
                                {!isCollapsed && (
                                    <div className="mt-1 ml-4 space-y-1">
                                        {group.uploads.map((upload, idx) => (
                                            <div key={idx} className="bg-white p-2 rounded border border-slate-100">
                                                <div className="flex items-center justify-between gap-2">
                                                    <div className="text-[10px] text-slate-600 truncate flex-1">{upload.name}</div>
                                                    {upload.status === 'completed' && <CheckCircle2 size={12} className="text-green-500 shrink-0" />}
                                                    {upload.status === 'error' && <AlertTriangle size={12} className="text-red-500 shrink-0" />}
                                                    {upload.status === 'uploading' && (
                                                        <span className="text-[10px] text-blue-600">{upload.progress || 0}%</span>
                                                    )}
                                                    {upload.status === 'waiting' && <Loader2 size={12} className="text-slate-300 animate-spin shrink-0" />}
                                                </div>
                                                {upload.status === 'uploading' && (
                                                    <div className="mt-1 h-1 w-full bg-slate-100 rounded-full overflow-hidden">
                                                        <div
                                                            className="h-full bg-blue-500 transition-all duration-300"
                                                            style={{ width: `${upload.progress || 0}%` }}
                                                        />
                                                    </div>
                                                )}
                                            </div>
                                        ))}
                                    </div>
                                )}
                            </div>
                        );
                    })
                ) : (
                    // 단일 프로젝트 모드: 기존 방식대로 표시
                    uploads.map((upload, idx) => (
                        <div key={idx} className="bg-white p-3 rounded-lg border border-slate-200 mb-2 last:mb-0">
                            <div className="flex items-start justify-between gap-2 mb-2">
                                <div className="flex-1 min-w-0">
                                    <div className="text-xs font-semibold text-slate-700 truncate">{upload.name}</div>
                                    {upload.status === 'uploading' && (
                                        <div className="text-[10px] text-slate-500 flex gap-2">
                                            <span>{upload.speed || '0 KB/s'}</span>
                                            <span>•</span>
                                            <span>ETA {upload.eta || '--:--'}</span>
                                        </div>
                                    )}
                                </div>
                                {upload.status === 'completed' && <CheckCircle2 size={14} className="text-green-500 shrink-0" />}
                                {upload.status === 'error' && <AlertTriangle size={14} className="text-red-500 shrink-0" />}
                                {upload.status === 'interrupted' && <AlertTriangle size={14} className="text-amber-500 shrink-0" />}
                                {upload.status === 'waiting' && <Loader2 size={14} className="text-slate-300 animate-spin shrink-0" />}
                            </div>

                            <div className="relative h-1.5 w-full bg-slate-100 rounded-full overflow-hidden">
                                <div
                                    className={`absolute top-0 left-0 h-full transition-all duration-300 ${upload.status === 'error' ? 'bg-red-500' :
                                        upload.status === 'completed' ? 'bg-green-500' :
                                        upload.status === 'interrupted' ? 'bg-amber-500' : 'bg-blue-500'
                                        }`}
                                    style={{ width: `${upload.progress || 0}%` }}
                                />
                            </div>
                        </div>
                    ))
                )}
            </div>

            {!isAllDone && (
                <div className="bg-white px-4 py-2 border-t border-slate-100">
                    <div className="flex items-center justify-between mb-1">
                        <span className="text-[10px] font-medium text-slate-500 uppercase tracking-wider">Overall Progress</span>
                        <span className="text-xs font-bold text-blue-600">{Math.round(totalProgress)}%</span>
                    </div>
                    <div className="h-1 w-full bg-slate-100 rounded-full overflow-hidden">
                        <div
                            className="h-full bg-blue-500 transition-all duration-500"
                            style={{ width: `${totalProgress}%` }}
                        />
                    </div>
                </div>
            )}
        </div>
    );
}
