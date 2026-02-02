import React, { useEffect, useRef, useMemo } from 'react';
import { UploadCloud, CheckCircle2, AlertTriangle, Loader2, X } from 'lucide-react';

export default function UploadProgressPanel({ uploads, onAbortAll, onRestore }) {
    const hasNotified = useRef(false);

    // 모든 hooks는 early return 전에 호출되어야 함 (React hooks 규칙)
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
                // 약간의 지연 후 알림 표시 (UI 업데이트 완료 후)
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

    // 프로젝트 이름 추출 (있는 경우)
    const projectTitle = uploads[0]?.projectTitle;

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
                        {projectTitle && (
                            <div className="text-[10px] text-white/70 truncate">{projectTitle}</div>
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

            <div className="max-h-64 overflow-y-auto p-2 bg-slate-50">
                {uploads.map((upload, idx) => (
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
                ))}
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
