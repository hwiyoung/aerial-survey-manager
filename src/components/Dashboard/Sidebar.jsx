import { useState, useMemo, useRef, useEffect } from 'react';
import {
    UploadCloud, FolderPlus, Search, CheckSquare, Square,
    ChevronRight, ChevronDown, MoreHorizontal, Edit2, Trash2,
    Play, Download, FileImage, Eye, Loader2, Clock,
    Activity, HardDrive, MapPinned
} from 'lucide-react';
import api from '../../api/client';
import { formatKstDateTime, formatKstTime, parseBackendDate } from '../../utils/dateTime';

// Export Raster는 COG 변환에 합쳐서 표시 (내부 동작은 별개이나 UI에서는 하나로)
const DISPLAY_STEPS = [
    { key: 'Align Photos',      label: '이미지 정렬' },
    { key: 'Build Depth Maps',  label: '깊이 맵' },
    { key: 'Build DEM',         label: 'DEM 생성' },
    { key: 'Build Orthomosaic', label: '정사모자이크' },
    { key: 'Convert COG',       label: 'COG 변환', mergeKeys: ['Export Raster', 'Convert COG'] },
];
const RESOURCE_POLL_MS = 1000;

function mergedProgress(stepStatus, keys) {
    const values = keys.map(k => stepStatus[k]).filter(v => v !== undefined);
    if (values.length === 0) return 0;
    if (values.some(v => v >= 1000)) return 1000; // 하나라도 에러면 에러
    if (values.every(v => v >= 99.9)) return 100;  // 모두 완료
    // 진행 중인 값 중 최대값 반환
    return Math.max(...values);
}

function ProcessingSteps({ projectId }) {
    const [stepStatus, setStepStatus] = useState(null);

    useEffect(() => {
        let cancelled = false;
        const fetch = () => {
            api.getProcessingStatus(projectId)
                .then(data => { if (!cancelled && data?.step_status) setStepStatus(data.step_status); })
                .catch(() => {});
        };
        fetch();
        const id = setInterval(fetch, 5000);
        return () => { cancelled = true; clearInterval(id); };
    }, [projectId]);

    if (!stepStatus || Object.keys(stepStatus).length === 0) return null;

    return (
        <div className="mt-1.5 space-y-0.5">
            {DISPLAY_STEPS.map(({ key, label, mergeKeys }) => {
                const progress = mergeKeys
                    ? mergedProgress(stepStatus, mergeKeys)
                    : (stepStatus[key] ?? 0);
                const isDone = progress >= 99.9 && progress < 1000;
                const isError = progress >= 1000;
                const isActive = progress > 0 && progress < 99.9 && !isError;
                return (
                    <div key={key} className="flex items-center gap-1.5">
                        <div className={`w-1.5 h-1.5 rounded-full shrink-0 ${
                            isError ? 'bg-red-400' :
                            isDone ? 'bg-green-400' :
                            isActive ? 'bg-blue-400 animate-pulse' :
                            'bg-slate-200'
                        }`} />
                        <span className={`text-[10px] flex-1 ${
                            isError ? 'text-red-500' :
                            isDone ? 'text-green-600' :
                            isActive ? 'text-blue-600 font-medium' :
                            'text-slate-400'
                        }`}>{label}</span>
                        {isActive && (
                            <span className="text-[9px] text-blue-500">{Math.round(progress)}%</span>
                        )}
                        {isDone && (
                            <span className="text-[9px] text-green-500">✓</span>
                        )}
                    </div>
                );
            })}
        </div>
    );
}

function formatPercent(value) {
    if (value === null || value === undefined || Number.isNaN(Number(value))) return '-';
    return `${Math.round(Number(value))}%`;
}

function formatBytes(value) {
    if (value === null || value === undefined || Number.isNaN(Number(value))) return '-';
    const units = ['B', 'KB', 'MB', 'GB', 'TB'];
    let size = Number(value);
    let unitIndex = 0;
    while (size >= 1024 && unitIndex < units.length - 1) {
        size /= 1024;
        unitIndex += 1;
    }
    const digits = size >= 100 || unitIndex === 0 ? 0 : 1;
    return `${size.toFixed(digits)}${units[unitIndex]}`;
}

function formatDateTime(value) {
    return formatKstDateTime(value, { withYear: false }) || '-';
}

function formatSidebarTime(value) {
    const date = parseBackendDate(value);
    if (!date) return '';
    return date.toLocaleTimeString('ko-KR', {
        timeZone: 'Asia/Seoul',
        hour12: false,
        hour: '2-digit',
        minute: '2-digit',
    });
}

function kstDateKey(value) {
    const date = parseBackendDate(value);
    if (!date) return '';
    return date.toLocaleDateString('en-CA', {
        timeZone: 'Asia/Seoul',
        year: 'numeric',
        month: '2-digit',
        day: '2-digit',
    });
}

function formatProcessingRange(project) {
    const startedAt = project.processingStartedAt || project.processing_started_at;
    const completedAt = project.processingCompletedAt || project.processing_completed_at;
    if (!startedAt && !completedAt) return '';

    if (startedAt && completedAt) {
        const startLabel = project.processingStartedAtDisplay || formatDateTime(startedAt);
        const completedLabel = kstDateKey(startedAt) === kstDateKey(completedAt)
            ? formatSidebarTime(completedAt)
            : (project.processingCompletedAtDisplay || formatDateTime(completedAt));
        return `시작 ${startLabel} · 완료 ${completedLabel}`;
    }

    if (startedAt) return `시작 ${project.processingStartedAtDisplay || formatDateTime(startedAt)}`;
    return `완료 ${project.processingCompletedAtDisplay || formatDateTime(completedAt)}`;
}

function getProcessingImageCount(project) {
    const count = project?.processingImageCount
        ?? project?.processing_image_count
        ?? project?.upload_completed_count
        ?? project?.imageCount
        ?? project?.image_count
        ?? 0;
    const numericCount = Number(count);
    return Number.isFinite(numericCount) ? numericCount : 0;
}

function statusClasses(status) {
    switch (status) {
        case 'ok':
            return 'bg-emerald-50 text-emerald-700 border-emerald-100';
        case 'warning':
            return 'bg-amber-50 text-amber-700 border-amber-100';
        case 'critical':
            return 'bg-red-50 text-red-700 border-red-100';
        default:
            return 'bg-slate-50 text-slate-500 border-slate-100';
    }
}

function statusDotClass(status) {
    switch (status) {
        case 'ok':
            return 'bg-emerald-500';
        case 'warning':
            return 'bg-amber-500';
        case 'critical':
            return 'bg-red-500';
        default:
            return 'bg-slate-300';
    }
}

function compactGpuName(name) {
    if (!name) return 'GPU';
    return name
        .replace(/^NVIDIA\s+/i, '')
        .replace(/^GeForce\s+/i, '')
        .replace(/\s+/g, ' ')
        .trim();
}

function summarizeGpu(devices = []) {
    if (!Array.isArray(devices) || devices.length === 0) {
        return { value: '확인중', detail: 'GPU 상태 대기' };
    }
    const names = devices.map((device) => compactGpuName(device.name));
    const uniqueNames = [...new Set(names)];
    const value = uniqueNames.length === 1
        ? `${devices.length}x ${uniqueNames[0]}`
        : `${devices.length} GPU`;
    const totalMemory = devices.reduce((sum, device) => sum + (Number(device.memory_total_bytes) || 0), 0);
    const usedMemory = devices.reduce((sum, device) => sum + (Number(device.memory_used_bytes) || 0), 0);
    const utilizations = devices
        .map((device) => Number(device.utilization_percent))
        .filter((value) => !Number.isNaN(value));
    const temperatures = devices
        .map((device) => Number(device.temperature_c))
        .filter((value) => !Number.isNaN(value));
    const avgUtilization = utilizations.length
        ? utilizations.reduce((sum, value) => sum + value, 0) / utilizations.length
        : null;
    const maxTemperature = temperatures.length ? Math.max(...temperatures) : null;
    const detailParts = [];
    if (avgUtilization !== null) detailParts.push(`사용 ${formatPercent(avgUtilization)}`);
    if (totalMemory > 0) detailParts.push(`VRAM ${formatBytes(usedMemory)} / ${formatBytes(totalMemory)}`);
    if (maxTemperature !== null) detailParts.push(`${Math.round(maxTemperature)}°C`);
    const detail = detailParts.length ? detailParts.join(' · ') : uniqueNames.join(', ');
    return { value, detail };
}

function ResourceStatusTile({ icon: Icon, label, value, detail, status, title }) {
    return (
        <div className={`min-w-0 rounded-md border px-2 py-1.5 ${statusClasses(status)}`} title={title}>
            <div className="flex items-center gap-1.5">
                <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${statusDotClass(status)}`} />
                <Icon size={13} className="shrink-0" />
                <span className="text-[10px] font-semibold truncate">{label}</span>
            </div>
            <div className="mt-0.5 text-[11px] font-bold leading-tight truncate">{value}</div>
            {detail && <div className="text-[10px] leading-tight opacity-80 truncate">{detail}</div>}
        </div>
    );
}

function ResourceStatusPanel() {
    const [status, setStatus] = useState(null);
    const [error, setError] = useState(false);
    const [refreshing, setRefreshing] = useState(false);
    const inFlightRef = useRef(false);

    useEffect(() => {
        let cancelled = false;

        const fetchStatus = () => {
            if (inFlightRef.current) return;
            inFlightRef.current = true;
            if (!cancelled) setRefreshing(true);
            api.getSystemResources()
                .then((data) => {
                    if (cancelled) return;
                    setStatus(data);
                    setError(false);
                })
                .catch(() => {
                    if (cancelled) return;
                    setError(true);
                })
                .finally(() => {
                    inFlightRef.current = false;
                    if (!cancelled) setRefreshing(false);
                });
        };

        fetchStatus();
        const intervalId = setInterval(fetchStatus, RESOURCE_POLL_MS);
        return () => {
            cancelled = true;
            clearInterval(intervalId);
        };
    }, []);

    const storageSummary = useMemo(() => {
        const entries = status?.storage || [];
        if (entries.length === 0) return null;
        const ranked = entries
            .filter((entry) => typeof entry.available_bytes === 'number')
            .sort((a, b) => a.available_bytes - b.available_bytes);
        return ranked[0] || entries[0];
    }, [status]);

    if (error && !status) {
        return (
            <div className="rounded-md border border-slate-200 bg-slate-50 px-3 py-2 text-xs text-slate-500">
                시스템 상태 확인 실패
            </div>
        );
    }

    const gpu = status?.gpu || {};
    const gpuSummary = gpu.status === 'critical' && (!gpu.devices || gpu.devices.length === 0)
        ? { value: '오류', detail: gpu.message || 'nvidia-smi 실패' }
        : gpu.available === false
            ? { value: '미감지', detail: gpu.message || 'GPU 상태 확인 불가' }
        : summarizeGpu(gpu.devices);
    const storageValue = `여유 ${formatBytes(storageSummary?.available_bytes)}`;
    const storageDetail = storageSummary ? `${storageSummary.label} ${formatPercent(storageSummary.available_percent)}` : null;
    const updatedAt = formatKstTime(status?.timestamp);
    const gpuStatus = gpu.stale ? 'warning' : gpu.status;
    const gpuTitle = [
        gpu.message || 'GPU 상태',
        gpu.source ? `source: ${gpu.source}` : null,
        gpu.checked_at ? `checked: ${formatKstTime(gpu.checked_at)}` : null,
        gpu.stale ? 'stale' : null,
    ].filter(Boolean).join(' / ');

    return (
        <div className="space-y-2">
            <div className="flex items-center justify-between text-[10px] text-slate-400">
                <span>리소스 상태</span>
                <span>{refreshing ? '갱신 중' : '1초 갱신'} · {updatedAt}</span>
            </div>
            <div className="grid grid-cols-2 gap-1.5">
                <ResourceStatusTile
                    icon={Activity}
                    label="GPU"
                    value={gpuSummary.value}
                    detail={gpuSummary.detail}
                    status={gpuStatus}
                    title={gpuTitle}
                />
                <ResourceStatusTile
                    icon={HardDrive}
                    label="저장"
                    value={storageValue}
                    detail={storageDetail}
                    status={storageSummary?.status}
                    title="저장공간 상태"
                />
            </div>
            {error && (
                <div className="text-[10px] text-amber-600">최근 상태 갱신에 실패했습니다.</div>
            )}
        </div>
    );
}

const REGIONS = [
    '수도권북부 권역',
    '수도권남부 권역',
    '강원 권역',
    '충청 권역',
    '전라동부 권역',
    '전라서부 권역',
    '경북 권역',
    '경남 권역'
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
        case 'cancelled':
        case '취소':
            return { text: '취소', style: 'bg-slate-100 text-slate-600 border-slate-200', icon: null };
        case 'pending':
        case '대기':
        default:
            return { text: '대기', style: 'bg-slate-50 text-slate-500 border-slate-100', icon: null };
    }
}

function getProjectRawStatus(project) {
    return String(project?.rawStatus || project?.status || '').toLowerCase();
}

function isCrsCorrectionCandidate(project) {
    const rawStatus = getProjectRawStatus(project);
    const displayStatus = project?.status;
    return (
        ['processing', 'queued', 'scheduled', 'running'].includes(rawStatus) ||
        displayStatus === '진행중'
    );
}

export function ProjectItem({
    project,
    isSelected,
    isChecked,
    sizeMode = 'normal',
    onSelect,
    onOpenInspector,
    onToggle,
    onDelete,
    onRename,
    onOpenProcessing,
    onOpenExport,
    onOpenCrsCorrection,
    canStartProcessing = true,
    canExportProject = true,
    canEditProject = true,
    canDeleteProject = true,
    draggable = false
}) {
    const [isEditing, setIsEditing] = useState(false);
    const [editValue, setEditValue] = useState(project.title);
    const clickTimeoutRef = useRef(null);
    const CLICK_DELAY = 250;
    const processingImageCount = getProcessingImageCount(project);

    const handleDragStart = (e) => {
        if (!draggable) return;
        e.dataTransfer.setData('projectId', project.id);
        e.dataTransfer.effectAllowed = 'move';
    };

    const handleClick = () => {
        if (clickTimeoutRef.current) {
            clearTimeout(clickTimeoutRef.current);
            clickTimeoutRef.current = null;
        }
        clickTimeoutRef.current = setTimeout(() => {
            onSelect();
            clickTimeoutRef.current = null;
        }, CLICK_DELAY);
    };

    const handleDoubleClick = () => {
        if (clickTimeoutRef.current) {
            clearTimeout(clickTimeoutRef.current);
            clickTimeoutRef.current = null;
        }
        onSelect();
        onOpenInspector();
    };

    const handleDelete = (e) => {
        e.stopPropagation();
        if (!onDelete) return;
        if (window.confirm(`"${project.title}" 프로젝트를 삭제하시겠습니까?\n\n이 작업은 되돌릴 수 없으며, 모든 이미지 및 관련 데이터가 삭제됩니다.`)) {
            onDelete();
        }
    };

    const handleRenameSubmit = async (e) => {
        e.stopPropagation();
        if (!onRename) return;
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
        if (!onOpenProcessing || !canStartProcessing) return;
        onOpenProcessing();
    };

    const handleExport = (e) => {
        e.stopPropagation();
        if (!onOpenExport || !canExportProject) return;
        onOpenExport();
    };

    const handleCrsCorrection = (e) => {
        e.stopPropagation();
        if (!onOpenCrsCorrection || !canEditProject || !isCrsCorrectionCandidate(project)) return;
        onOpenCrsCorrection();
    };

    const processingDisabledReason = canStartProcessing && onOpenProcessing
        ? '프로젝트 처리 화면으로 이동'
        : '프로젝트 처리 권한이 없습니다.';
    const exportDisabledReason = (() => {
        if (!canExportProject || !onOpenExport) return '프로젝트 내보내기 권한이 없습니다.';
        if (project.status !== '완료') return '완료된 프로젝트만 내보내기가 가능합니다.';
        return '정사영상 내보내기';
    })();
    const canOpenCrsCorrection = Boolean(onOpenCrsCorrection) && canEditProject && isCrsCorrectionCandidate(project);
    const crsCorrectionDisabledReason = (() => {
        if (!onOpenCrsCorrection || !canEditProject) return '프로젝트 수정 권한이 없습니다.';
        if (!isCrsCorrectionCandidate(project)) return '처리 중인 프로젝트에서만 좌표계 변경이 가능합니다.';
        return '좌표계 변경';
    })();

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
                <span className="text-[10px] text-slate-400 flex items-center gap-0.5 shrink-0"><FileImage size={10} /> {processingImageCount}</span>
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
                    <button
                        onClick={handleProcessing}
                        disabled={!canStartProcessing || !onOpenProcessing}
                        className="p-1.5 rounded transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
                        title={processingDisabledReason}
                    >
                        <Play size={14} className={canStartProcessing && onOpenProcessing ? 'text-blue-600' : 'text-slate-400'} />
                    </button>
                    <button
                        onClick={handleExport}
                        disabled={!canExportProject || !onOpenExport || project.status !== '완료'}
                        className="p-1.5 rounded transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
                        title={exportDisabledReason}
                    >
                        <Download size={14} className={canExportProject && onOpenExport && project.status === '완료' ? 'text-slate-500' : 'text-slate-300'} />
                    </button>
                    <button
                        onClick={handleCrsCorrection}
                        disabled={!canOpenCrsCorrection}
                        className="p-1.5 rounded transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
                        title={crsCorrectionDisabledReason}
                    >
                        <MapPinned size={14} className={canOpenCrsCorrection ? 'text-amber-600' : 'text-slate-300'} />
                    </button>
                </div>
                
            </div>
        );
    }

    if (sizeMode === 'expanded') {
        const processingRangeLabel = formatProcessingRange(project);
        return (
            <div onClick={handleClick} onDoubleClick={handleDoubleClick} draggable={draggable} onDragStart={handleDragStart} className={`relative p-3 rounded-lg cursor-pointer transition-all border group ${isSelected ? "bg-blue-50 border-blue-200 shadow-sm z-10" : "bg-white hover:bg-slate-50 border-transparent"}`}>
                <div className="flex items-center gap-3">
                    <div onClick={(e) => { e.stopPropagation(); onToggle(); }} className="text-slate-400 hover:text-blue-600 cursor-pointer shrink-0">{isChecked ? <CheckSquare size={18} className="text-blue-600" /> : <Square size={18} />}</div>
                    {isEditing ? (
                        <input autoFocus value={editValue} onClick={e => e.stopPropagation()} onChange={e => setEditValue(e.target.value)} onKeyDown={e => { if (e.key === 'Enter') handleRenameSubmit(e); if (e.key === 'Escape') handleRenameCancel(e); }} onBlur={handleRenameSubmit} className="text-sm font-bold border rounded px-1 flex-1 min-w-0" />
                    ) : (
                        <h4 className="text-sm font-bold text-slate-800 truncate min-w-[120px] max-w-[220px]" title={project.title}>{project.title}</h4>
                    )}
                    <div className="flex items-center gap-2 text-xs text-slate-500 flex-wrap min-w-0">
                        <span className="bg-slate-100 px-1.5 py-0.5 rounded">{project.region}</span>
                        <span className="text-slate-300">|</span>
                        <span className="flex items-center gap-1"><FileImage size={12} /> {processingImageCount}장</span>
                        {project.area && <><span className="text-slate-300">|</span><span className="font-bold text-blue-600"> {project.area.toFixed(2)} km²</span></>}
                        {processingRangeLabel && (
                            <>
                                <span className="text-slate-300">|</span>
                                <span className="flex items-center gap-1 whitespace-nowrap">
                                    <Clock size={12} /> {processingRangeLabel}
                                </span>
                            </>
                        )}
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
                        {canEditProject && <button onClick={(e) => { e.stopPropagation(); setIsEditing(true); }} className="p-1 text-slate-400 hover:text-blue-600 hover:bg-blue-50 rounded" title="이름 변경"><Edit2 size={14} /></button>}
                        {canDeleteProject && <button onClick={handleDelete} className="p-1 text-slate-400 hover:text-red-500 hover:bg-red-50 rounded transition-all shrink-0" title="프로젝트 삭제"><Trash2 size={14} /></button>}
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
                        <ProcessingSteps projectId={project.id} />
                    </div>
                )}
                {(project.status === '오류' || project.status === 'error') && project.error_message && (
                    <div className="mt-2 ml-8 p-2 bg-red-50 border border-red-200 rounded-lg">
                        <div className="flex items-start gap-2">
                            <span className="text-red-500 text-xs">⚠</span>
                            <div className="text-[11px] text-red-700 leading-relaxed whitespace-pre-line">
                                {project.error_code && (
                                    <span className="mb-1 inline-flex rounded border border-red-200 bg-red-100 px-1.5 py-0.5 font-mono text-[9px] font-medium tracking-tight text-red-700">
                                        오류 코드: {project.error_code}
                                    </span>
                                )}
                                <p className={project.error_code ? "font-medium" : undefined}>{project.error_message}</p>
                                {project.error_action && <p className="mt-1">{project.error_action}</p>}
                                {project.error_reference && (
                                    <p className="mt-1 font-mono text-[10px]">오류 참조번호: {project.error_reference}</p>
                                )}
                            </div>
                        </div>
                    </div>
                )}
                {(project.status === '취소' || project.status === 'cancelled') && (
                    <div className="mt-2 ml-8 rounded-lg border border-slate-200 bg-slate-50 p-2">
                        <div className="flex items-start gap-2">
                            <span className="text-xs text-slate-500">ℹ</span>
                            <div className="text-[11px] leading-relaxed text-slate-600">
                                <p className="font-medium">처리가 취소되었습니다.</p>
                                <p className="mt-1">필요하면 처리 버튼을 눌러 다시 시작할 수 있습니다.</p>
                            </div>
                        </div>
                    </div>
                )}
                <div className="flex gap-2 mt-2 ml-8">
                    <button
                        onClick={handleProcessing}
                        disabled={!canStartProcessing || !onOpenProcessing}
                        className="flex items-center justify-center gap-1 px-3 py-1.5 text-xs font-medium rounded transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
                        title={processingDisabledReason}
                    >
                        <Play size={12} className={canStartProcessing && onOpenProcessing ? 'text-blue-700' : 'text-slate-400'} />
                        처리
                    </button>
                    <button
                        onClick={handleExport}
                        disabled={!canExportProject || !onOpenExport || project.status !== '완료'}
                        className="flex items-center justify-center gap-1 px-3 py-1.5 text-xs font-medium bg-slate-100 hover:bg-slate-200 text-slate-700 rounded transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
                        title={exportDisabledReason}
                    >
                        <Download size={12} className={canExportProject && onOpenExport && project.status === '완료' ? 'text-slate-700' : 'text-slate-400'} />
                        내보내기
                    </button>
                    <button
                        onClick={handleCrsCorrection}
                        disabled={!canOpenCrsCorrection}
                        className="flex items-center justify-center gap-1 px-3 py-1.5 text-xs font-medium bg-amber-50 hover:bg-amber-100 text-amber-700 rounded transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
                        title={crsCorrectionDisabledReason}
                    >
                        <MapPinned size={12} className={canOpenCrsCorrection ? 'text-amber-700' : 'text-slate-400'} />
                        좌표계 변경
                    </button>
                </div>
            </div>
        );
    }

    return (
        <div onClick={handleClick} onDoubleClick={handleDoubleClick} draggable={draggable} onDragStart={handleDragStart} className={`relative flex flex-col gap-2 p-3 rounded-lg cursor-pointer transition-all border group ${isSelected ? "bg-blue-50 border-blue-200 shadow-sm z-10" : "bg-white hover:bg-slate-50 border-transparent"}`}>
            <div className="flex items-start gap-3">
                <div onClick={(e) => { e.stopPropagation(); onToggle(); }} className="mt-1 text-slate-400 hover:text-blue-600 cursor-pointer">{isChecked ? <CheckSquare size={18} className="text-blue-600" /> : <Square size={18} />}</div>
                <div className="flex-1 min-w-0">
                    <div className="flex justify-between items-start gap-2">
                        {isEditing ? (
                            <input autoFocus value={editValue} onClick={e => e.stopPropagation()} onChange={e => setEditValue(e.target.value)} onKeyDown={e => { if (e.key === 'Enter') handleRenameSubmit(e); if (e.key === 'Escape') handleRenameCancel(e); }} onBlur={handleRenameSubmit} className="text-sm font-bold border rounded px-1 flex-1 min-w-0 mr-2" />
                        ) : (
                            <h4 className="text-sm font-bold text-slate-800 leading-snug flex-1 min-w-0 break-words [overflow-wrap:anywhere]" title={project.title}>{project.title}</h4>
                        )}
                        <div className="flex items-center gap-1 shrink-0">
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
                            {canEditProject && <button onClick={(e) => { e.stopPropagation(); setIsEditing(true); }} className="opacity-0 group-hover:opacity-100 p-1 text-slate-400 hover:text-blue-600 hover:bg-blue-50 rounded" title="이름 변경"><Edit2 size={14} /></button>}
                            {canDeleteProject && <button onClick={handleDelete} className="opacity-0 group-hover:opacity-100 p-1 text-slate-400 hover:text-red-500 hover:bg-red-50 rounded transition-all" title="프로젝트 삭제"><Trash2 size={14} /></button>}
                        </div>
                    </div>
                    <div className="flex items-center gap-2 text-xs text-slate-500 mt-1"><span className="bg-slate-100 px-1.5 rounded">{project.region}</span></div>
                </div>
            </div>
            <div className={`flex gap-2 pl-7 ${isSelected ? 'opacity-100' : 'opacity-0 group-hover:opacity-100'} transition-opacity`}>
                    <button
                        onClick={handleProcessing}
                        disabled={!canStartProcessing || !onOpenProcessing}
                        className="flex-1 flex items-center justify-center gap-1 px-2 py-1.5 text-xs font-medium rounded transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
                        title={processingDisabledReason}
                    >
                        <Play size={12} className={canStartProcessing && onOpenProcessing ? 'text-blue-700' : 'text-slate-400'} />
                        처리
                    </button>
                    <button
                        onClick={handleExport}
                        disabled={!canExportProject || !onOpenExport || project.status !== '완료'}
                        className="flex-1 flex items-center justify-center gap-1 px-2 py-1.5 text-xs font-medium bg-slate-100 hover:bg-slate-200 text-slate-700 rounded transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
                        title={exportDisabledReason}
                    >
                        <Download size={12} className={canExportProject && onOpenExport && project.status === '완료' ? 'text-slate-700' : 'text-slate-400'} />
                        내보내기
                    </button>
                    <button
                        onClick={handleCrsCorrection}
                        disabled={!canOpenCrsCorrection}
                        className="flex-1 flex items-center justify-center gap-1 px-2 py-1.5 text-xs font-medium bg-amber-50 hover:bg-amber-100 text-amber-700 rounded transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
                        title={crsCorrectionDisabledReason}
                    >
                        <MapPinned size={12} className={canOpenCrsCorrection ? 'text-amber-700' : 'text-slate-400'} />
                        좌표계 변경
                    </button>
                </div>
        </div>
    );
}

function GroupItem({
    group,
    projects,
    isExpanded,
    onToggle,
    onDrop,
    onEdit,
    onDelete,
    canEditGroup = true,
    canDeleteGroup = true,
    onRenameProject,
    selectedProjectId,
    onSelectProject,
    onOpenInspector,
    checkedProjectIds,
    onSelectMultiple,
    onToggleCheck,
    sizeMode,
    onOpenProcessing,
    canStartProcessing = true,
    onOpenExport,
    onOpenCrsCorrection,
    canExportProject = true,
    onExportGroupProjects,
    onDeleteProject,
    canEditProject = true,
    canDeleteProject = true,
    canEditProjectItem = null,
    canDeleteProjectItem = null,
    canStartProcessingItem = null,
    onDeleteGroupProjects,
    onFilter,
    isActive
}) {
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

    const groupProjectIds = groupProjects.map(p => p.id);
    const areAllGroupProjectsSelected = groupProjectIds.length > 0 && groupProjectIds.every(id => checkedProjectIds.has(id));
    const hasGroupProjects = groupProjectIds.length > 0;
    const resolveProjectPermission = (resolver, fallback, project) => (
        typeof resolver === 'function' ? Boolean(resolver(project)) : fallback
    );
    const hasDeletableGroupProjects = groupProjects.some(project =>
        resolveProjectPermission(canDeleteProjectItem, canDeleteProject, project)
    );
    const canDeleteGroupProjects =
        canDeleteProject && Boolean(onDeleteGroupProjects) && hasDeletableGroupProjects;
    const canUseGroupMenu =
        canEditGroup ||
        canDeleteGroup ||
        (canExportProject && Boolean(onExportGroupProjects)) ||
        canDeleteGroupProjects;

    const handleDragOver = (e) => { e.preventDefault(); setIsDragOver(true); };
    const handleDragLeave = () => setIsDragOver(false);
    const handleDrop = (e) => {
        e.preventDefault();
        setIsDragOver(false);
        const projectId = e.dataTransfer.getData('projectId');
        if (projectId && onDrop) {
            onDrop(projectId, group.id);
        }
    };

    return (
        <div className="mb-1">
            <div className={`flex items-center gap-2 px-2 py-1.5 rounded-md cursor-pointer transition-colors group ${isDragOver ? 'bg-blue-100 ring-2 ring-blue-400' : isActive ? 'bg-blue-50 ring-1 ring-blue-300' : 'hover:bg-slate-100'}`} onDragOver={handleDragOver} onDragLeave={handleDragLeave} onDrop={handleDrop}>
                <button onClick={onToggle} className="p-0.5 hover:bg-slate-200 rounded">{isExpanded ? <ChevronDown size={14} className="text-slate-500" /> : <ChevronRight size={14} className="text-slate-500" />}</button>
                <div className="w-4 h-4 rounded flex-shrink-0" style={{ backgroundColor: group.color || '#94a3b8' }} />
                <span className={`text-sm font-medium flex-1 truncate cursor-pointer hover:text-blue-600 ${isActive ? 'text-blue-600' : 'text-slate-700'}`} onClick={(e) => { e.stopPropagation(); onFilter && onFilter(group.id); }}>{group.name}</span>
                <span className="text-xs text-slate-400">{groupProjects.length}</span>
                {canUseGroupMenu && (
                    <div className="relative" ref={menuRef}>
                        <button onClick={(e) => { e.stopPropagation(); setShowMenu(!showMenu); }} className="p-1 hover:bg-slate-200 rounded opacity-0 group-hover:opacity-100"><MoreHorizontal size={14} className="text-slate-400" /></button>
                        {showMenu && (
                            <div className="absolute right-0 top-6 bg-white border border-slate-200 rounded-md shadow-lg z-50 py-1 min-w-[120px]">
                                <button
                                    onClick={(e) => {
                                        e.stopPropagation();
                                        if (!onSelectMultiple) return;
                                        onSelectMultiple(groupProjectIds, !areAllGroupProjectsSelected);
                                        setShowMenu(false);
                                    }}
                                    className="w-full px-3 py-1.5 text-left text-sm hover:bg-slate-100 flex items-center gap-2"
                                    disabled={!hasGroupProjects}
                                >
                                    <CheckSquare size={14} /> {areAllGroupProjectsSelected ? '그룹 선택 해제' : '그룹 전체 선택'}
                                </button>
                                {canExportProject && onExportGroupProjects && (
                                    <button
                                        onClick={(e) => {
                                            e.stopPropagation();
                                            if (onExportGroupProjects) onExportGroupProjects(group.id);
                                            setShowMenu(false);
                                        }}
                                        className="w-full px-3 py-1.5 text-left text-sm hover:bg-slate-100 flex items-center gap-2"
                                        disabled={!hasGroupProjects}
                                    >
                                        <Download size={14} /> 그룹 내보내기
                                    </button>
                                )}
                                {canEditGroup && <button onClick={(e) => { e.stopPropagation(); onEdit && onEdit(group); setShowMenu(false); }} className="w-full px-3 py-1.5 text-left text-sm hover:bg-slate-100 flex items-center gap-2"><Edit2 size={14} /> 수정</button>}
                                {canDeleteGroup && <button onClick={(e) => { e.stopPropagation(); onDelete && onDelete(group.id); setShowMenu(false); }} className="w-full px-3 py-1.5 text-left text-sm hover:bg-red-50 text-red-600 flex items-center gap-2"><Trash2 size={14} /> 삭제</button>}
                                {canDeleteGroupProjects && (
                                    <button
                                        onClick={(e) => {
                                            e.stopPropagation();
                                            if (onDeleteGroupProjects) onDeleteGroupProjects(group.id);
                                            setShowMenu(false);
                                        }}
                                        className="w-full px-3 py-1.5 text-left text-sm hover:bg-red-50 text-red-600 flex items-center gap-2"
                                    >
                                        <Trash2 size={14} /> 그룹 프로젝트 삭제
                                    </button>
                                )}
                            </div>
                        )}
                    </div>
                )}
            </div>
            {isExpanded && groupProjects.length > 0 && (
                <div className="pl-6 space-y-1 mt-1">
                    {groupProjects.map((project) => {
                        const projectCanEdit = resolveProjectPermission(
                            canEditProjectItem,
                            canEditProject,
                            project
                        );
                        const projectCanDelete = resolveProjectPermission(
                            canDeleteProjectItem,
                            canDeleteProject,
                            project
                        );
                        const projectCanStartProcessing = resolveProjectPermission(
                            canStartProcessingItem,
                            canStartProcessing,
                            project
                        );

                        return (
                            <ProjectItem
                                key={project.id}
                                project={project}
                                isSelected={project.id === selectedProjectId}
                                isChecked={checkedProjectIds.has(project.id)}
                                sizeMode={sizeMode}
                                onSelect={() => onSelectProject(project.id)}
                                onOpenInspector={() => onOpenInspector(project.id)}
                                onToggle={() => onToggleCheck(project.id)}
                                onDelete={onDeleteProject ? () => onDeleteProject(project.id) : null}
                                onRename={onRenameProject ? (newName) => onRenameProject(project.id, newName) : null}
                                onOpenProcessing={onOpenProcessing ? () => onOpenProcessing(project.id) : null}
                                onOpenExport={onOpenExport ? () => onOpenExport(project.id) : null}
                                onOpenCrsCorrection={onOpenCrsCorrection ? () => onOpenCrsCorrection(project.id) : null}
                                canStartProcessing={projectCanStartProcessing}
                                canExportProject={canExportProject}
                                canEditProject={projectCanEdit}
                                canDeleteProject={projectCanDelete}
                                draggable
                            />
                        );
                    })}
                </div>
            )}
        </div>
    );
}

export default function Sidebar({
    width,
    isResizing = false,
    projects,
    selectedProjectId,
    checkedProjectIds,
    onSelectProject,
    onOpenInspector,
    onToggleCheck,
    onOpenUpload,
    onBulkExport,
    onSelectMultiple,
    onDeleteProject,
    onRenameProject,
    onBulkDelete,
    onOpenProcessing,
            onOpenExport,
            onOpenCrsCorrection,
            groups = [],
            expandedGroupIds = new Set(),
            onToggleGroupExpand,
            onMoveProjectToGroup,
            onCreateGroup,
    onEditGroup,
    onDeleteGroup,
    activeGroupId = null,
    onFilterGroup,
    onExportGroupProjects,
    onBulkDeleteGroupProjects,
    searchTerm,
            onSearchTermChange,
            regionFilter,
            onRegionFilterChange,
            canCreateProject = false,
            canCreateGroup = false,
            canEditProject = false,
            canDeleteProject = false,
            canEditGroup = false,
            canDeleteGroup = false,
            canEditProjectItem = null,
            canDeleteProjectItem = null,
            canStartProcessingItem = null,
            canStartProcessing = false,
            canExportProject = false,
}) {
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
                {canCreateProject && onOpenUpload && <button onClick={onOpenUpload} className="flex-1 bg-blue-600 hover:bg-blue-700 text-white py-3 rounded-lg flex items-center justify-center gap-2 font-bold shadow-md transition-all active:scale-95"><UploadCloud size={20} /><span>새 프로젝트</span></button>}
                {canCreateGroup && onCreateGroup && <button onClick={onCreateGroup} className="px-3 bg-slate-100 hover:bg-slate-200 text-slate-600 rounded-lg flex items-center justify-center transition-all" title="새 폴더"><FolderPlus size={20} /></button>}
            </div>
            <div className="p-4 pt-2 border-b border-slate-200 space-y-3">
                <div className="relative"><Search className="absolute left-3 top-2.5 text-slate-400" size={16} /><input type="text" placeholder="검색..." className="w-full pl-9 pr-3 py-2 bg-slate-50 border border-slate-200 rounded-md text-sm" value={searchTerm} onChange={(e) => onSearchTermChange(e.target.value)} /></div>
                <select className="w-full p-2 bg-slate-50 border border-slate-200 rounded-md text-sm text-slate-600" value={regionFilter} onChange={(e) => onRegionFilterChange(e.target.value)} >
                    <option value="ALL">전체 권역</option>
                    {REGIONS.map(r => <option key={r} value={r}>{r}</option>)}
                </select>
                <ResourceStatusPanel />
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
                        <GroupItem
                            key={group.id}
                            group={group}
                            projects={filteredProjects}
                            isExpanded={expandedGroupIds.has(group.id)}
                            onToggle={() => onToggleGroupExpand && onToggleGroupExpand(group.id)}
                            onDrop={onMoveProjectToGroup}
                            onEdit={onEditGroup}
                            onDelete={onDeleteGroup}
                            canEditGroup={canEditGroup}
                            canDeleteGroup={canDeleteGroup}
                            onRenameProject={onRenameProject}
                            selectedProjectId={selectedProjectId}
                            onSelectProject={onSelectProject}
                            onOpenInspector={onOpenInspector}
                            checkedProjectIds={checkedProjectIds}
                            onSelectMultiple={onSelectMultiple}
                            onToggleCheck={onToggleCheck}
                            sizeMode={sizeMode}
                            onOpenProcessing={onOpenProcessing}
                            canStartProcessing={canStartProcessing}
                            onOpenExport={onOpenExport}
                            onOpenCrsCorrection={onOpenCrsCorrection}
                            canExportProject={canExportProject}
                            onExportGroupProjects={onExportGroupProjects}
                            onDeleteProject={onDeleteProject}
                            canEditProject={canEditProject}
                            canDeleteProject={canDeleteProject}
                            canEditProjectItem={canEditProjectItem}
                            canDeleteProjectItem={canDeleteProjectItem}
                            canStartProcessingItem={canStartProcessingItem}
                            onDeleteGroupProjects={onBulkDeleteGroupProjects}
                            onFilter={onFilterGroup}
                            isActive={activeGroupId === group.id}
                        />
                    ))}
                    {ungroupedProjects.length > 0 && (
                        <div className={`mt-2 pt-2 border-t border-dashed border-slate-200 ${isDragOverUngrouped ? 'bg-blue-50 ring-2 ring-blue-300 rounded' : ''}`} onDragOver={handleDragOverUngrouped} onDragLeave={handleDragLeaveUngrouped} onDrop={handleDropUngrouped} >
                            {groups.length > 0 && <div className="text-xs text-slate-400 px-2 py-1 font-medium">미분류 프로젝트</div>}
                            {ungroupedProjects.map((project) => {
                                const projectCanEdit = typeof canEditProjectItem === 'function'
                                    ? Boolean(canEditProjectItem(project))
                                    : canEditProject;
                                const projectCanDelete = typeof canDeleteProjectItem === 'function'
                                    ? Boolean(canDeleteProjectItem(project))
                                    : canDeleteProject;
                                const projectCanStartProcessing = typeof canStartProcessingItem === 'function'
                                    ? Boolean(canStartProcessingItem(project))
                                    : canStartProcessing;

                                return (
                                    <ProjectItem
                                        key={project.id}
                                        project={project}
                                        isSelected={project.id === selectedProjectId}
                                        isChecked={checkedProjectIds.has(project.id)}
                                        sizeMode={sizeMode}
                                        draggable={true}
                                        onSelect={() => onSelectProject(project.id)}
                                        onOpenInspector={() => onOpenInspector(project.id)}
                                        onToggle={() => onToggleCheck(project.id)}
                                        onDelete={onDeleteProject ? () => onDeleteProject(project.id) : null}
                                        onRename={onRenameProject ? (newName) => onRenameProject(project.id, newName) : null}
                                        onOpenProcessing={onOpenProcessing ? () => onOpenProcessing(project.id) : null}
                                        onOpenExport={onOpenExport ? () => onOpenExport(project.id) : null}
                                        onOpenCrsCorrection={onOpenCrsCorrection ? () => onOpenCrsCorrection(project.id) : null}
                                        canStartProcessing={projectCanStartProcessing}
                                        canExportProject={canExportProject}
                                        canEditProject={projectCanEdit}
                                        canDeleteProject={projectCanDelete}
                                    />
                                );
                            })}
                        </div>
                    )}
                    {filteredProjects.length === 0 && <div className="text-center text-slate-400 py-8 text-sm">프로젝트가 없습니다</div>}
                </div>
            </div>
            {checkedProjectIds.size > 0 && (canExportProject || canDeleteProject) && (
                <div className="p-4 border-t border-slate-200 bg-slate-50 animate-in slide-in-from-bottom duration-200 space-y-2">
                    {canExportProject && onBulkExport && <button onClick={onBulkExport} className="w-full flex items-center justify-center gap-2 bg-slate-800 hover:bg-slate-900 text-white py-2.5 rounded-lg text-sm font-bold shadow-md transition-all"><Download size={16} className="text-white" /><span>선택한 {checkedProjectIds.size}건 정사영상 내보내기</span></button>}
                    {canDeleteProject && onBulkDelete && <button onClick={onBulkDelete} className="w-full flex items-center justify-center gap-2 bg-red-600 hover:bg-red-700 text-white py-2.5 rounded-lg text-sm font-bold shadow-md transition-all"><Trash2 size={16} className="text-white" /><span>선택한 {checkedProjectIds.size}건 삭제</span></button>}
                </div>
            )}
        </aside>
    );
}
