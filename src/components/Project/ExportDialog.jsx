import React, { useState, useEffect, useRef, useMemo } from 'react';
import { X, Download, FileOutput, Trash2, AlertTriangle, HardDrive } from 'lucide-react';
import api from '../../api/client';

// result_gsd가 없을 때 사용할 기본 GSD (cm/pixel)
const DEFAULT_GSD = 5;

function formatBytes(bytes) {
    if (!bytes || bytes === 0) return '0 B';
    const units = ['B', 'KB', 'MB', 'GB', 'TB'];
    const i = Math.floor(Math.log(bytes) / Math.log(1024));
    return `${(bytes / Math.pow(1024, i)).toFixed(1)} ${units[i]}`;
}

export default function ExportDialog({ isOpen, onClose, targetProjectIds, allProjects, onProjectsChanged }) {
    const [format, setFormat] = useState('GeoTiff');
    const [crs, setCrs] = useState('TM중부 (EPSG:5186)');
    const [gsd, setGsd] = useState(DEFAULT_GSD);
    const [filename, setFilename] = useState('');
    const [isExporting, setIsExporting] = useState(false);
    const [progress, setProgress] = useState(0);
    const [phase, setPhase] = useState('export'); // 'export' | 'askDelete'
    const [isDeleting, setIsDeleting] = useState(false);
    const progressIntervalRef = useRef(null);
    const wasOpenRef = useRef(false);
    const abortControllerRef = useRef(null);

    const targets = useMemo(() => {
        return allProjects.filter(p => targetProjectIds.includes(p.id));
    }, [allProjects, targetProjectIds]);

    // Metashape build orthomosaic의 result_gsd 값을 직접 사용
    const resultGsd = useMemo(() => {
        if (targets.length === 1) {
            const project = targets[0];
            return project.result_gsd || DEFAULT_GSD;
        }
        if (targets.length > 1 && targets[0].result_gsd) {
            return targets[0].result_gsd;
        }
        return DEFAULT_GSD;
    }, [targets]);

    const totalCogSize = useMemo(() => {
        return targets.reduce((sum, p) => sum + (p.ortho_size || 0), 0);
    }, [targets]);

    useEffect(() => {
        if (isOpen && !wasOpenRef.current) {
            // closed → open 전환 시에만 초기화 (WebSocket allProjects 업데이트로 재실행 방지)
            setIsExporting(false);
            setProgress(0);
            setPhase('export');
            setIsDeleting(false);
            setGsd(resultGsd);
            if (targets.length === 1) {
                setFilename(`${targets[0].title}_ortho`);
            } else {
                setFilename(`Bulk_Export_${new Date().toISOString().slice(0, 10)}`);
            }
        }
        wasOpenRef.current = isOpen;
    }, [isOpen, targets, resultGsd]);

    // 컴포넌트 언마운트 시 interval 및 abort 정리
    useEffect(() => {
        return () => {
            if (progressIntervalRef.current) {
                clearInterval(progressIntervalRef.current);
            }
            if (abortControllerRef.current) {
                abortControllerRef.current.abort();
            }
        };
    }, []);

    // ESC 키로 창 닫기
    useEffect(() => {
        const handleKeyDown = (e) => {
            if (e.key === 'Escape' && !isExporting && !isDeleting) {
                onClose();
            }
        };
        if (isOpen) {
            document.addEventListener('keydown', handleKeyDown);
        }
        return () => document.removeEventListener('keydown', handleKeyDown);
    }, [isOpen, isExporting, isDeleting, onClose]);

    const handleExportStart = async () => {
        setIsExporting(true);
        setProgress(5);

        const controller = new AbortController();
        abortControllerRef.current = controller;

        let currentProgress = 5;
        progressIntervalRef.current = setInterval(() => {
            currentProgress += Math.random() * 3 + 1;
            if (currentProgress >= 99) {
                currentProgress = 99;
            }
            setProgress(Math.floor(currentProgress));
        }, 200);

        try {
            const result = await api.prepareBatchExport(targetProjectIds, {
                format: format,
                crs: crs.match(/EPSG:(\d+)/)?.[0] || 'EPSG:5186',
                gsd: gsd,
                custom_filename: filename || null,
            }, controller.signal);

            clearInterval(progressIntervalRef.current);
            api.triggerDirectDownload(result.download_id);
            setProgress(100);

            // 내보내기 완료 → COG 삭제 확인 단계로 전환
            const hasCog = targets.some(p => p.ortho_path);
            if (hasCog) {
                setPhase('askDelete');
                setIsExporting(false);
            } else {
                onClose();
            }
        } catch (err) {
            clearInterval(progressIntervalRef.current);
            if (err.name === 'AbortError') {
                setIsExporting(false);
                setProgress(0);
                return;
            }
            console.error('Batch export failed:', err);
            alert('내보내기 실패: ' + err.message);
            setIsExporting(false);
            setProgress(0);
        } finally {
            abortControllerRef.current = null;
        }
    };

    const handleExportCancel = () => {
        if (abortControllerRef.current) {
            abortControllerRef.current.abort();
        }
        if (progressIntervalRef.current) {
            clearInterval(progressIntervalRef.current);
        }
    };

    const handleDeleteCog = async () => {
        setIsDeleting(true);
        try {
            const cogTargets = targets.filter(p => p.ortho_path);
            for (const project of cogTargets) {
                await api.deleteOrthoCog(project.id);
            }
            if (onProjectsChanged) onProjectsChanged();
            onClose();
        } catch (err) {
            console.error('COG deletion failed:', err);
            alert('정사영상 삭제 실패:' + err.message);
            setIsDeleting(false);
        }
    };

    const handleKeepCog = () => {
        onClose();
    };

    if (!isOpen) return null;

    // COG 삭제 확인 화면
    if (phase === 'askDelete') {
        return (
            <div className="fixed inset-0 z-[1000] flex items-center justify-center bg-black/60 backdrop-blur-sm animate-in fade-in duration-200">
                <div className="bg-white rounded-xl shadow-2xl w-[480px] overflow-hidden">
                    <div className="h-14 border-b border-slate-200 bg-amber-50 flex items-center justify-between px-6">
                        <h3 className="font-bold text-amber-800 flex items-center gap-2">
                            <HardDrive size={20} className="text-amber-600" />
                            저장공간 관리
                        </h3>
                    </div>
                    <div className="p-6 space-y-5">
                        <div className="bg-green-50 p-4 rounded-lg border border-green-200 text-center">
                            <p className="text-sm font-bold text-green-700">내보내기가 완료되었습니다</p>
                            <p className="text-xs text-green-600 mt-1">파일 다운로드가 시작되었습니다.</p>
                        </div>

                        <div className="text-center space-y-2">
                            <p className="text-sm text-slate-700">
                                저장공간 절약을 위해 서버의 원본 정사영상을 삭제하시겠습니까?
                            </p>
                            <div className="bg-slate-50 p-3 rounded-lg border border-slate-200">
                                {targets.filter(p => p.ortho_path).map(p => (
                                    <div key={p.id} className="flex justify-between text-xs py-1">
                                        <span className="text-slate-600 truncate mr-2">{p.title}</span>
                                        <span className="text-slate-500 font-mono whitespace-nowrap">{formatBytes(p.ortho_size)}</span>
                                    </div>
                                ))}
                                {targets.filter(p => p.ortho_path).length > 1 && (
                                    <div className="flex justify-between text-xs pt-2 mt-2 border-t border-slate-200 font-bold">
                                        <span className="text-slate-700">합계</span>
                                        <span className="text-slate-700 font-mono">{formatBytes(totalCogSize)}</span>
                                    </div>
                                )}
                            </div>
                        </div>

                        <div className="bg-red-50 p-3 rounded-lg border border-red-200 flex gap-2">
                            <AlertTriangle size={16} className="text-red-500 mt-0.5 flex-shrink-0" />
                            <p className="text-xs text-red-600">
                                삭제하면 되돌릴 수 없습니다. 지도에서 정사영상이 더 이상 표시되지 않으며, 다시 보려면 재처리가 필요합니다.
                            </p>
                        </div>
                    </div>
                    <div className="h-16 border-t border-slate-200 bg-slate-50 px-6 flex items-center justify-end gap-3">
                        {!isDeleting ? (
                            <>
                                <button onClick={handleKeepCog} className="px-5 py-2 bg-blue-600 text-white rounded-lg font-bold hover:bg-blue-700 text-sm">
                                    보관
                                </button>
                                <button onClick={handleDeleteCog} className="px-5 py-2 bg-red-500 text-white rounded-lg font-bold hover:bg-red-600 text-sm flex items-center gap-2">
                                    <Trash2 size={14} /> 삭제 ({formatBytes(totalCogSize)})
                                </button>
                            </>
                        ) : (
                            <button disabled className="px-6 py-2 bg-slate-300 text-white rounded-lg font-bold text-sm cursor-wait">
                                삭제 중...
                            </button>
                        )}
                    </div>
                </div>
            </div>
        );
    }

    // 내보내기 설정 화면 (기존)
    return (
        <div className="fixed inset-0 z-[1000] flex items-center justify-center bg-black/60 backdrop-blur-sm animate-in fade-in duration-200">
            <div className="bg-white rounded-xl shadow-2xl w-[500px] overflow-hidden">
                <div className="h-14 border-b border-slate-200 bg-slate-50 flex items-center justify-between px-6">
                    <h3 className="font-bold text-slate-800 flex items-center gap-2">
                        <Download size={20} className="text-blue-600" />
                        정사영상 내보내기 설정
                    </h3>
                    {!isExporting && <button onClick={onClose}><X size={20} className="text-slate-400 hover:text-slate-600" /></button>}
                </div>
                <div className="p-6 space-y-6">
                    <div className="bg-blue-50 p-4 rounded-lg border border-blue-100 flex justify-between items-center">
                        <span className="text-sm font-bold text-blue-800">내보내기 대상</span>
                        <span className="text-xs bg-white px-2 py-1 rounded border border-blue-200 text-blue-600 font-bold">
                            총 {targets.length}개 프로젝트
                        </span>
                    </div>
                    <div className="space-y-4">
                        <div className="grid grid-cols-2 gap-4">
                            <div className="space-y-1">
                                <label className="text-xs font-bold text-slate-500">포맷 (Format)</label>
                                <select className="w-full border p-2 rounded text-sm bg-white" value={format} onChange={e => setFormat(e.target.value)}>
                                    <option value="GeoTiff">GeoTiff (*.tif)</option>
                                    <option value="JPG">JPG (*.jpg)</option>
                                    <option value="PNG">PNG (*.png)</option>
                                    <option value="ECW">ECW (*.ecw)</option>
                                </select>
                            </div>
                            <div className="space-y-1">
                                <label className="text-xs font-bold text-slate-500">좌표계 (CRS)</label>
                                <select className="w-full border p-2 rounded text-sm bg-white" value={crs} onChange={e => setCrs(e.target.value)}>
                                    <option value="TM중부 (EPSG:5186)">TM 중부 (EPSG:5186)</option>
                                    <option value="TM서부 (EPSG:5185)">TM 서부 (EPSG:5185)</option>
                                    <option value="TM동부 (EPSG:5187)">TM 동부 (EPSG:5187)</option>
                                    <option value="TM동해 (EPSG:5188)">TM 동해 (EPSG:5188)</option>
                                    <option value="UTM-K (EPSG:5179)">UTM-K (EPSG:5179)</option>
                                    <option value="WGS84 (EPSG:4326)">WGS84 (EPSG:4326)</option>
                                </select>
                            </div>
                        </div>
                        <div className="space-y-1">
                            <label className="text-xs font-bold text-slate-500">해상도 (GSD)</label>
                            <div className="flex gap-2">
                                <input type="number" className="border p-2 rounded text-sm w-full" value={gsd} onChange={e => setGsd(Number(e.target.value))} />
                                <span className="text-sm text-slate-500 self-center whitespace-nowrap">cm/pixel</span>
                            </div>
                        </div>
                        <div className="space-y-1">
                            <label className="text-xs font-bold text-slate-500">파일 이름</label>
                            <div className="flex gap-2 items-center">
                                <input type="text" className="border p-2 rounded text-sm w-full" value={filename} onChange={e => setFilename(e.target.value)} />
                                <span className="text-sm text-slate-400">.{format === 'GeoTiff' ? 'tif' : format.toLowerCase()}</span>
                            </div>
                            {targets.length > 1 && <p className="text-[10px] text-slate-400">* 다중 파일인 경우 순번(_001)이 자동 부여됩니다.</p>}
                        </div>
                    </div>
                    {isExporting && (
                        <div className="space-y-2 animate-in fade-in">
                            <div className="flex justify-between text-xs font-bold text-blue-600">
                                <span>Exporting...</span>
                                <span>{progress}%</span>
                            </div>
                            <div className="w-full h-2 bg-slate-100 rounded-full overflow-hidden">
                                <div className="h-full bg-blue-600 transition-all duration-200" style={{ width: `${progress}%` }} />
                            </div>
                        </div>
                    )}
                </div>
                <div className="h-16 border-t border-slate-200 bg-slate-50 px-6 flex items-center justify-end gap-3">
                    {!isExporting ? (
                        <>
                            <button onClick={onClose} className="px-4 py-2 text-slate-500 font-bold hover:bg-slate-200 rounded-lg text-sm">취소</button>
                            <button onClick={handleExportStart} className="px-6 py-2 bg-blue-600 text-white rounded-lg font-bold hover:bg-blue-700 text-sm flex items-center gap-2">
                                <FileOutput size={16} /> 내보내기
                            </button>
                        </>
                    ) : (
                        <>
                            <button onClick={handleExportCancel} className="px-4 py-2 text-red-500 font-bold hover:bg-red-50 rounded-lg text-sm">취소</button>
                            <button disabled className="px-6 py-2 bg-slate-300 text-white rounded-lg font-bold text-sm cursor-wait">
                                처리 중...
                            </button>
                        </>
                    )}
                </div>
            </div>
        </div>
    );
}
