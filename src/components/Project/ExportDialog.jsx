import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { MapContainer, TileLayer, useMap } from 'react-leaflet';
import { AlertTriangle, Download, FileOutput, HardDrive, History, Loader2, Trash2, X } from 'lucide-react';
import api from '../../api/client';
import { getTileConfig, MAP_CONFIG } from '../../config/mapConfig';
import { MapPanes, TiTilerOrthoLayer } from '../Dashboard/FootprintMap';
import SheetGridOverlay from './SheetGridOverlay';

const DEFAULT_GSD = 5;
const MAX_CLIP_SHEETS = 50;
const DEFAULT_SCALES = [
    { scale: 50000, label: '1:50,000' },
    { scale: 25000, label: '1:25,000' },
    { scale: 5000, label: '1:5,000' },
    { scale: 1000, label: '1:1,000' },
];

const STATUS_LABELS = {
    queued: '대기',
    processing: '처리 중',
    completed: '완료',
    error: '오류',
    cancelled: '취소',
};

function formatBytes(bytes) {
    if (!bytes) return '0 B';
    const units = ['B', 'KB', 'MB', 'GB', 'TB'];
    const index = Math.min(units.length - 1, Math.floor(Math.log(bytes) / Math.log(1024)));
    return `${(bytes / Math.pow(1024, index)).toFixed(1)} ${units[index]}`;
}

function formatCreatedAt(value) {
    if (!value) return '';
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? '' : date.toLocaleString('ko-KR', { hour12: false });
}

function outputExtension(format) {
    if (format === 'GeoTiff') return 'tif';
    if (format === 'JPG') return 'jpg';
    return format.toLowerCase();
}

function defaultSingleProjectFilename(project) {
    return [project?.region, project?.title, 'ortho']
        .map((value) => String(value || '').trim())
        .filter(Boolean)
        .join('_')
        .replace(/[^0-9A-Za-z가-힣._-]+/g, '_')
        .replace(/_+/g, '_')
        .replace(/^[._-]+|[._-]+$/g, '');
}

function previewClipFilename(filename, format) {
    const base = String(filename || 'export')
        .replace(/\.(?:tiff?|jpe?g|png|ecw|zip)$/i, '')
        .replace(/_clip$/i, '');
    return `${base}_clip.${outputExtension(format)}`;
}

function combineProjectBounds(projects) {
    const points = projects.flatMap((project) => (
        Array.isArray(project.bounds) ? project.bounds : []
    )).filter((point) => (
        Array.isArray(point)
        && point.length >= 2
        && Number.isFinite(Number(point[0]))
        && Number.isFinite(Number(point[1]))
    ));
    if (points.length === 0) return null;
    const latitudes = points.map((point) => Number(point[0]));
    const longitudes = points.map((point) => Number(point[1]));
    return [
        [Math.min(...latitudes), Math.min(...longitudes)],
        [Math.max(...latitudes), Math.max(...longitudes)],
    ];
}

function ExportMapFit({ bounds }) {
    const map = useMap();
    const signature = bounds ? JSON.stringify(bounds) : '';
    useEffect(() => {
        window.setTimeout(() => map.invalidateSize(), 0);
        if (bounds) map.fitBounds(bounds, { padding: [28, 28], maxZoom: 17 });
    }, [map, bounds, signature]);
    return null;
}

export default function ExportDialog({ isOpen, onClose, targetProjectIds, allProjects, onProjectsChanged }) {
    const [format, setFormat] = useState('GeoTiff');
    const [crs, setCrs] = useState('TM중부 (EPSG:5186)');
    const [gsd, setGsd] = useState(DEFAULT_GSD);
    const [filename, setFilename] = useState('');
    const [scale, setScale] = useState(5000);
    const [availableScales, setAvailableScales] = useState(DEFAULT_SCALES);
    const [selectedSheets, setSelectedSheets] = useState([]);
    const [loadedSheets, setLoadedSheets] = useState([]);
    const [clipHistory, setClipHistory] = useState([]);
    const [activeJob, setActiveJob] = useState(null);
    const [isExporting, setIsExporting] = useState(false);
    const [progress, setProgress] = useState(0);
    const [phase, setPhase] = useState('export');
    const [isDeleting, setIsDeleting] = useState(false);
    const [deletingClipJobId, setDeletingClipJobId] = useState(null);
    const [jobError, setJobError] = useState(null);
    const progressIntervalRef = useRef(null);
    const wasOpenRef = useRef(false);
    const abortControllerRef = useRef(null);
    const downloadedJobRef = useRef(null);

    const targets = useMemo(
        () => allProjects.filter((project) => targetProjectIds.includes(project.id)),
        [allProjects, targetProjectIds]
    );
    const resultGsd = targets[0]?.result_gsd || DEFAULT_GSD;
    const totalCogSize = targets.reduce((sum, project) => sum + (project.ortho_size || 0), 0);
    const projectBounds = useMemo(() => combineProjectBounds(targets), [targets]);
    const tileConfig = getTileConfig();
    const sortedLoadedSheets = useMemo(() => [...loadedSheets].sort((a, b) => {
        const aLat = a.bounds_wgs84?.[1]?.[0] ?? 0;
        const bLat = b.bounds_wgs84?.[1]?.[0] ?? 0;
        if (Math.abs(aLat - bLat) > 0.0001) return bLat - aLat;
        return (a.bounds_wgs84?.[0]?.[1] ?? 0) - (b.bounds_wgs84?.[0]?.[1] ?? 0);
    }), [loadedSheets]);

    const refreshClipHistory = useCallback(async () => {
        try {
            const result = await api.getClipExportHistory(10);
            setClipHistory(result.jobs || []);
        } catch (error) {
            console.error('Clip export history load failed:', error);
        }
    }, []);

    useEffect(() => {
        if (isOpen && !wasOpenRef.current) {
            setIsExporting(false);
            setProgress(0);
            setPhase('export');
            setIsDeleting(false);
            setDeletingClipJobId(null);
            setGsd(resultGsd);
            setScale(5000);
            setSelectedSheets([]);
            setLoadedSheets([]);
            setActiveJob(null);
            setJobError(null);
            downloadedJobRef.current = null;
            setFilename(targets.length === 1
                ? defaultSingleProjectFilename(targets[0])
                : `Bulk_Export_${new Date().toISOString().slice(0, 10)}`);
            api.getSheetScales()
                .then((result) => {
                    const scales = result.scales || [];
                    if (scales.length > 0) {
                        setAvailableScales([...scales].sort((a, b) => Number(b.scale) - Number(a.scale)));
                    }
                })
                .catch(() => setAvailableScales(DEFAULT_SCALES));
            refreshClipHistory();
        }
        wasOpenRef.current = isOpen;
    }, [isOpen, refreshClipHistory, resultGsd, targets]);

    useEffect(() => () => {
        if (progressIntervalRef.current) clearInterval(progressIntervalRef.current);
        if (abortControllerRef.current) abortControllerRef.current.abort();
    }, []);

    useEffect(() => {
        const handleKeyDown = (event) => {
            if (event.key === 'Escape' && !isExporting && !isDeleting) onClose();
        };
        if (isOpen) document.addEventListener('keydown', handleKeyDown);
        return () => document.removeEventListener('keydown', handleKeyDown);
    }, [isOpen, isExporting, isDeleting, onClose]);

    useEffect(() => {
        if (!activeJob?.job_id || !['queued', 'processing'].includes(activeJob.status)) return undefined;
        let cancelled = false;
        const poll = async () => {
            try {
                const job = await api.getClipExportJob(activeJob.job_id);
                if (cancelled) return;
                setActiveJob(job);
                setProgress(job.progress || 0);
                if (job.status === 'completed' && downloadedJobRef.current !== job.job_id) {
                    downloadedJobRef.current = job.job_id;
                    const download = await api.prepareClipExportDownload(job.job_id);
                    api.triggerDirectDownload(download.download_id);
                    setProgress(100);
                    setIsExporting(false);
                    setPhase(targets.some((project) => project.ortho_path) ? 'askDelete' : 'export');
                    refreshClipHistory();
                } else if (job.status === 'error' || job.status === 'cancelled') {
                    setIsExporting(false);
                    setJobError(job.error || (job.status === 'cancelled' ? {
                        message: '내보내기가 취소되었습니다.',
                        action: '필요하면 다시 실행해주세요.',
                    } : null));
                    refreshClipHistory();
                }
            } catch (error) {
                if (!cancelled) {
                    setIsExporting(false);
                    setJobError({ message: error.summary || error.message, action: error.action, reference_id: error.referenceId });
                }
            }
        };
        poll();
        const interval = window.setInterval(poll, 1000);
        return () => {
            cancelled = true;
            window.clearInterval(interval);
        };
    }, [activeJob?.job_id, activeJob?.status, refreshClipHistory, targets]);

    const handleWholeExport = async () => {
        setJobError(null);
        setIsExporting(true);
        setProgress(5);
        const controller = new AbortController();
        abortControllerRef.current = controller;
        let currentProgress = 5;
        progressIntervalRef.current = window.setInterval(() => {
            currentProgress = Math.min(95, currentProgress + 2);
            setProgress(currentProgress);
        }, 500);
        try {
            const result = await api.prepareBatchExport(targetProjectIds, {
                format,
                crs: crs.match(/EPSG:(\d+)/)?.[0] || 'EPSG:5186',
                gsd,
                custom_filename: filename || null,
            }, controller.signal);
            window.clearInterval(progressIntervalRef.current);
            api.triggerDirectDownload(result.download_id);
            setProgress(100);
            setIsExporting(false);
            setPhase(targets.some((project) => project.ortho_path) ? 'askDelete' : 'export');
        } catch (error) {
            window.clearInterval(progressIntervalRef.current);
            if (error.name !== 'AbortError') {
                setJobError({ message: error.summary || error.message, action: error.action, reference_id: error.referenceId });
            }
            setIsExporting(false);
            setProgress(0);
        } finally {
            abortControllerRef.current = null;
        }
    };

    const handleClipExport = async () => {
        if (selectedSheets.length === 0) return;
        setJobError(null);
        setIsExporting(true);
        setProgress(0);
        try {
            const job = await api.clipExport(targetProjectIds, selectedSheets, {
                scale,
                format,
                crs: crs.match(/EPSG:(\d+)/)?.[0] || 'EPSG:5186',
                gsd,
                custom_filename: filename || null,
            });
            setActiveJob(job);
            refreshClipHistory();
        } catch (error) {
            setJobError({ message: error.summary || error.message, action: error.action, reference_id: error.referenceId });
            setIsExporting(false);
        }
    };

    const toggleSelectedSheet = (sheetId) => {
        if (isExporting) return;
        setSelectedSheets((current) => {
            if (current.includes(sheetId)) return current.filter((item) => item !== sheetId);
            if (current.length >= MAX_CLIP_SHEETS) {
                setJobError({
                    message: `도엽은 최대 ${MAX_CLIP_SHEETS}개까지 선택할 수 있습니다.`,
                    action: '선택을 줄인 뒤 다시 시도해주세요.',
                });
                return current;
            }
            return [...current, sheetId];
        });
    };

    const handleExportCancel = async () => {
        if (activeJob?.job_id && ['queued', 'processing'].includes(activeJob.status)) {
            try {
                const cancelled = await api.cancelClipExport(activeJob.job_id);
                setActiveJob(cancelled);
                setJobError({ message: '내보내기가 취소되었습니다.', action: '필요하면 다시 실행해주세요.' });
            } catch (error) {
                setJobError({ message: error.summary || error.message, action: error.action, reference_id: error.referenceId });
            }
        } else if (abortControllerRef.current) {
            abortControllerRef.current.abort();
        }
        if (progressIntervalRef.current) window.clearInterval(progressIntervalRef.current);
        setIsExporting(false);
    };

    const handleHistoryDownload = async (jobId) => {
        try {
            const result = await api.prepareClipExportDownload(jobId);
            api.triggerDirectDownload(result.download_id);
        } catch (error) {
            setJobError({ message: error.summary || error.message, action: error.action, reference_id: error.referenceId });
        }
    };

    const handleClipResultDelete = async (job) => {
        if (!window.confirm(`서버에 보관된 클립 결과를 삭제하시겠습니까?\n${job.filename}`)) return;
        setDeletingClipJobId(job.job_id);
        setJobError(null);
        try {
            await api.deleteClipExportResult(job.job_id);
            await refreshClipHistory();
        } catch (error) {
            setJobError({ message: error.summary || error.message, action: error.action, reference_id: error.referenceId });
        } finally {
            setDeletingClipJobId(null);
        }
    };

    const handleDeleteCog = async () => {
        setIsDeleting(true);
        try {
            for (const project of targets.filter((item) => item.ortho_path)) {
                await api.deleteOrthoCog(project.id);
            }
            onProjectsChanged?.();
            onClose();
        } catch (error) {
            setJobError({ message: error.summary || error.message, action: error.action, reference_id: error.referenceId });
            setIsDeleting(false);
        }
    };

    if (!isOpen) return null;

    if (phase === 'askDelete') {
        return (
            <div className="fixed inset-0 z-[1000] flex items-center justify-center bg-black/60 backdrop-blur-sm">
                <div className="bg-white rounded-xl shadow-2xl w-[480px] overflow-hidden">
                    <div className="h-14 border-b border-slate-200 bg-amber-50 flex items-center px-6">
                        <h3 className="font-bold text-amber-800 flex items-center gap-2"><HardDrive size={20} /> 저장공간 관리</h3>
                    </div>
                    <div className="p-6 space-y-5">
                        <div className="bg-green-50 p-4 rounded-lg border border-green-200 text-center">
                            <p className="text-sm font-bold text-green-700">내보내기가 완료되었습니다</p>
                            <p className="text-xs text-green-600 mt-1">파일 다운로드가 시작되었습니다.</p>
                        </div>
                        <p className="text-sm text-slate-700 text-center">서버의 원본 정사영상을 삭제하시겠습니까?</p>
                        <div className="bg-slate-50 p-3 rounded-lg border border-slate-200">
                            {targets.filter((project) => project.ortho_path).map((project) => (
                                <div key={project.id} className="flex justify-between text-xs py-1">
                                    <span className="text-slate-600 truncate mr-2">{project.title}</span>
                                    <span className="text-slate-500 font-mono">{formatBytes(project.ortho_size)}</span>
                                </div>
                            ))}
                            <div className="flex justify-between text-xs pt-2 mt-2 border-t border-slate-200 font-bold">
                                <span>합계</span><span>{formatBytes(totalCogSize)}</span>
                            </div>
                        </div>
                        <div className="bg-red-50 p-3 rounded-lg border border-red-200 flex gap-2">
                            <AlertTriangle size={16} className="text-red-500 shrink-0" />
                            <p className="text-xs text-red-600">삭제하면 되돌릴 수 없으며 다시 보려면 재처리가 필요합니다.</p>
                        </div>
                    </div>
                    <div className="h-16 border-t border-slate-200 bg-slate-50 px-6 flex items-center justify-end gap-3">
                        <button onClick={onClose} disabled={isDeleting} className="px-5 py-2 bg-blue-600 text-white rounded-lg font-bold text-sm">보관</button>
                        <button onClick={handleDeleteCog} disabled={isDeleting} className="px-5 py-2 bg-red-500 text-white rounded-lg font-bold text-sm flex items-center gap-2 disabled:opacity-50">
                            <Trash2 size={14} /> {isDeleting ? '삭제 중...' : `삭제 (${formatBytes(totalCogSize)})`}
                        </button>
                    </div>
                </div>
            </div>
        );
    }

    return (
        <div className="fixed inset-0 z-[1000] flex items-center justify-center bg-black/60 backdrop-blur-sm p-4">
            <div className="bg-white rounded-xl shadow-2xl w-full max-w-[1180px] h-[min(860px,calc(100vh-32px))] overflow-hidden flex flex-col">
                <div className="h-14 border-b border-slate-200 bg-slate-50 flex items-center justify-between px-6 shrink-0">
                    <h3 className="font-bold text-slate-800 flex items-center gap-2"><Download size={20} className="text-blue-600" /> 정사영상 내보내기</h3>
                    {!isExporting && <button onClick={onClose}><X size={20} className="text-slate-400 hover:text-slate-600" /></button>}
                </div>

                <div className="p-5 border-b border-slate-200 bg-white shrink-0">
                    <div className="grid grid-cols-12 gap-3 items-end">
                        <div className="col-span-2 space-y-1">
                            <label className="text-xs font-bold text-slate-500">유형</label>
                            <select className="w-full border p-2 rounded text-sm bg-white" value={format} onChange={(event) => setFormat(event.target.value)} disabled={isExporting}>
                                <option value="GeoTiff">GeoTiff (*.tif)</option><option value="JPG">JPG (*.jpg)</option><option value="PNG">PNG (*.png)</option><option value="ECW" disabled>ECW (현재 변환기 미지원)</option>
                            </select>
                        </div>
                        <div className="col-span-3 space-y-1">
                            <label className="text-xs font-bold text-slate-500">좌표계</label>
                            <select className="w-full border p-2 rounded text-sm bg-white" value={crs} onChange={(event) => setCrs(event.target.value)} disabled={isExporting}>
                                <option value="TM중부 (EPSG:5186)">TM 중부 (EPSG:5186)</option><option value="TM서부 (EPSG:5185)">TM 서부 (EPSG:5185)</option><option value="TM동부 (EPSG:5187)">TM 동부 (EPSG:5187)</option><option value="TM동해 (EPSG:5188)">TM 동해 (EPSG:5188)</option><option value="UTM-K (EPSG:5179)">UTM-K (EPSG:5179)</option><option value="WGS84 (EPSG:4326)">WGS84 (EPSG:4326)</option>
                            </select>
                        </div>
                        <div className="col-span-2 space-y-1">
                            <label className="text-xs font-bold text-slate-500">해상도</label>
                            <div className="relative"><input type="number" min="0.01" className="border p-2 pr-16 rounded text-sm w-full" value={gsd} onChange={(event) => setGsd(Number(event.target.value))} disabled={isExporting} /><span className="absolute right-2 top-2 text-xs text-slate-400">cm/px</span></div>
                        </div>
                        <div className="col-span-5 space-y-1">
                            <label className="text-xs font-bold text-slate-500">이름</label>
                            <div className="flex items-center"><input type="text" className="border p-2 rounded-l text-sm w-full" value={filename} onChange={(event) => setFilename(event.target.value)} disabled={isExporting} /><span className="border border-l-0 bg-slate-50 p-2 rounded-r text-sm text-slate-400">.{outputExtension(format)}</span></div>
                        </div>
                    </div>
                </div>

                <div className="flex-1 min-h-0 grid grid-cols-[minmax(0,1fr)_320px]">
                    <div className="min-w-0 flex flex-col border-r border-slate-200">
                        <div className="h-11 px-4 border-b border-slate-200 bg-slate-50 flex items-center justify-between shrink-0">
                            <div><span className="text-xs font-bold text-slate-700">도엽 선택</span><span className="text-[11px] text-slate-400 ml-2">지도에서 도엽을 클릭해 클립 영역을 만드세요.</span></div>
                            <div className="flex gap-1">
                                {availableScales.map((item) => <button key={item.scale} onClick={() => { setScale(item.scale); setSelectedSheets([]); }} disabled={isExporting} className={`px-2 py-1 text-[10px] rounded font-bold ${scale === item.scale ? 'bg-amber-500 text-white' : 'bg-white border border-slate-200 text-slate-600'}`}>{item.label}</button>)}
                            </div>
                        </div>
                        <div className="flex-1 min-h-[360px] relative">
                            <MapContainer center={MAP_CONFIG.defaultCenter} zoom={MAP_CONFIG.defaultZoom} minZoom={MAP_CONFIG.minZoom} maxZoom={tileConfig.maxZoom} style={{ height: '100%', width: '100%' }}>
                                <TileLayer attribution={tileConfig.attribution} url={tileConfig.url} {...(tileConfig.subdomains ? { subdomains: tileConfig.subdomains } : {})} maxNativeZoom={tileConfig.maxNativeZoom} maxZoom={tileConfig.maxZoom} />
                                <MapPanes />
                                <ExportMapFit bounds={projectBounds} />
                                {targets.filter((project) => project.ortho_path).map((project) => (
                                    <TiTilerOrthoLayer key={project.id} projectId={project.id} visible={true} opacity={targets.length > 1 ? 0.75 : 1} projectBounds={project.bounds} showBasemap={true} />
                                ))}
                                <SheetGridOverlay visible={true} scale={scale} projectBounds={projectBounds} selectedSheets={selectedSheets} onToggleSheet={toggleSelectedSheet} onSheetsLoaded={setLoadedSheets} pane="sheet-grid" />
                            </MapContainer>
                        </div>
                    </div>

                    <aside className="min-h-0 flex flex-col bg-white">
                        <div className="p-3 border-b border-slate-200 shrink-0">
                            <div className="flex items-center justify-between mb-2"><span className="text-xs font-bold text-slate-700">선택 도엽 {selectedSheets.length}개 <span className="font-normal text-slate-400">(최대 {MAX_CLIP_SHEETS})</span></span><div className="flex gap-2">{selectedSheets.length === 0 && sortedLoadedSheets.length > 0 && <button onClick={() => setSelectedSheets(sortedLoadedSheets.slice(0, MAX_CLIP_SHEETS).map((sheet) => sheet.mapid))} className="text-[10px] text-blue-600 font-bold">전체 선택</button>}{selectedSheets.length > 0 && <button onClick={() => setSelectedSheets([])} className="text-[10px] text-red-500 font-bold">전체 해제</button>}</div></div>
                            <div className="min-h-16 max-h-28 overflow-y-auto flex flex-wrap content-start gap-1 p-2 bg-slate-50 rounded border border-slate-100">
                                {selectedSheets.length === 0 ? <span className="text-[11px] text-slate-400">선택된 도엽이 없습니다.</span> : selectedSheets.map((sheetId) => <button key={sheetId} onClick={() => toggleSelectedSheet(sheetId)} className="h-6 px-1.5 text-[10px] font-mono bg-blue-50 text-blue-700 border border-blue-200 rounded">{sheetId} ×</button>)}
                            </div>
                            {selectedSheets.length > 0 && <p className="mt-2 text-[10px] text-slate-500 break-all">결과: <span className="font-mono text-blue-700">{previewClipFilename(filename, format)}</span></p>}
                        </div>

                        {(isExporting || jobError) && <div className="p-3 border-b border-slate-200 shrink-0">
                            {isExporting && <div className="space-y-2"><div className="flex justify-between text-xs font-bold text-blue-600"><span className="flex items-center gap-1"><Loader2 size={13} className="animate-spin" /> {activeJob?.stage || '내보내기 준비 중'}</span><span>{progress}%</span></div><div className="w-full h-2 bg-slate-100 rounded-full overflow-hidden"><div className="h-full bg-blue-600 transition-all" style={{ width: `${progress}%` }} /></div></div>}
                            {jobError && <div className="text-xs bg-red-50 border border-red-200 rounded p-2 text-red-700"><div className="font-bold">{jobError.message || '내보내기를 완료하지 못했습니다.'}</div>{jobError.action && <div className="mt-1">{jobError.action}</div>}{jobError.reference_id && <div className="mt-1 font-mono">오류 참조번호: {jobError.reference_id}</div>}</div>}
                        </div>}

                        <div className="flex-1 min-h-0 overflow-y-auto p-3">
                            <div className="flex items-center justify-between mb-2"><span className="text-xs font-bold text-slate-700 flex items-center gap-1"><History size={13} /> 최근 클립 이력</span><button onClick={refreshClipHistory} className="text-[10px] text-blue-600">새로고침</button></div>
                            <div className="space-y-2">
                                {clipHistory.length === 0 && <p className="text-[11px] text-slate-400">클립 이력이 없습니다.</p>}
                                {clipHistory.map((job) => <div key={job.job_id} className="border border-slate-200 rounded p-2 text-[10px]"><div className="flex items-start justify-between gap-2"><span className="font-bold text-slate-700 break-all">{job.filename}</span><span className={`shrink-0 px-1.5 py-0.5 rounded ${job.status === 'completed' ? 'bg-green-50 text-green-700' : job.status === 'error' ? 'bg-red-50 text-red-700' : 'bg-slate-100 text-slate-600'}`}>{STATUS_LABELS[job.status] || job.status}</span></div><div className="mt-1 text-slate-400">{formatCreatedAt(job.created_at)} · 도엽 {job.sheet_ids?.length || 0}개</div><div className="mt-1 max-h-10 overflow-y-auto font-mono text-slate-500 break-all">{(job.sheet_ids || []).join(', ')}</div>{job.download_available ? <div className="mt-1 flex items-center gap-3"><button onClick={() => handleHistoryDownload(job.job_id)} className="text-blue-600 font-bold">다시 다운로드</button><button onClick={() => handleClipResultDelete(job)} disabled={deletingClipJobId === job.job_id} className="text-red-500 font-bold disabled:opacity-40">{deletingClipJobId === job.job_id ? '삭제 중' : '서버 결과 삭제'}</button></div> : job.status === 'completed' && <div className="mt-1 text-slate-400">서버 결과 없음</div>}</div>)}
                            </div>
                        </div>
                    </aside>
                </div>

                <div className="h-16 border-t border-slate-200 bg-slate-50 px-5 flex items-center justify-between gap-3 shrink-0">
                    <div className="text-xs text-slate-500">대상 {targets.length}개 프로젝트 · 선택 도엽은 하나의 영역과 하나의 결과 파일로 처리됩니다.</div>
                    {!isExporting ? <div className="flex gap-2"><button onClick={onClose} className="px-4 py-2 text-slate-500 font-bold hover:bg-slate-200 rounded-lg text-sm">취소</button><button onClick={handleWholeExport} className="px-4 py-2 bg-slate-700 text-white rounded-lg font-bold text-sm flex items-center gap-2"><FileOutput size={16} /> 전체 내보내기</button><button onClick={handleClipExport} disabled={selectedSheets.length === 0} className="px-5 py-2 bg-blue-600 text-white rounded-lg font-bold text-sm flex items-center gap-2 disabled:opacity-40"><FileOutput size={16} /> 선택 도엽 클립</button></div> : <button onClick={handleExportCancel} className="px-4 py-2 text-red-600 font-bold hover:bg-red-50 rounded-lg text-sm">작업 취소</button>}
                </div>
            </div>
        </div>
    );
}
