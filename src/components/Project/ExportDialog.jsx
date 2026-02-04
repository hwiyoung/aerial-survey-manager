import React, { useState, useEffect, useMemo } from 'react';
import { X, Download, FileOutput } from 'lucide-react';
import api from '../../api/client';

// result_gsd가 없을 때 사용할 기본 GSD (cm/pixel)
const DEFAULT_GSD = 5;

export default function ExportDialog({ isOpen, onClose, targetProjectIds, allProjects }) {
    const [format, setFormat] = useState('GeoTiff');
    const [crs, setCrs] = useState('GRS80 (EPSG:5186)');
    const [gsd, setGsd] = useState(DEFAULT_GSD);
    const [filename, setFilename] = useState('');
    const [isExporting, setIsExporting] = useState(false);
    const [progress, setProgress] = useState(0);
    const progressIntervalRef = React.useRef(null);

    const targets = useMemo(() => {
        return allProjects.filter(p => targetProjectIds.includes(p.id));
    }, [allProjects, targetProjectIds]);

    // Metashape build orthomosaic의 result_gsd 값을 직접 사용
    const resultGsd = useMemo(() => {
        if (targets.length === 1) {
            const project = targets[0];
            // result_gsd: Metashape에서 실제로 생성된 정사영상의 GSD
            return project.result_gsd || DEFAULT_GSD;
        }
        // 다중 프로젝트의 경우 첫 번째 프로젝트의 GSD 또는 기본값
        if (targets.length > 1 && targets[0].result_gsd) {
            return targets[0].result_gsd;
        }
        return DEFAULT_GSD;
    }, [targets]);

    useEffect(() => {
        if (isOpen) {
            setIsExporting(false);
            setProgress(0);
            // Metashape result_gsd로 초기화
            setGsd(resultGsd);
            if (targets.length === 1) {
                setFilename(`${targets[0].title}_ortho`);
            } else {
                setFilename(`Bulk_Export_${new Date().toISOString().slice(0, 10)}`);
            }
        }
    }, [isOpen, targets, resultGsd]);

    // ESC 키로 창 닫기
    useEffect(() => {
        const handleKeyDown = (e) => {
            if (e.key === 'Escape' && !isExporting) {
                onClose();
            }
        };
        if (isOpen) {
            document.addEventListener('keydown', handleKeyDown);
        }
        return () => document.removeEventListener('keydown', handleKeyDown);
    }, [isOpen, isExporting, onClose]);

    const handleExportStart = async () => {
        setIsExporting(true);
        setProgress(5);

        // 진행률 시뮬레이션 (5% ~ 99%까지, 절대 100%는 안됨)
        let currentProgress = 5;
        progressIntervalRef.current = setInterval(() => {
            currentProgress += Math.random() * 3 + 1;
            if (currentProgress >= 99) {
                currentProgress = 99; // 최대 99%까지만
            }
            setProgress(Math.floor(currentProgress));
        }, 200);

        try {
            // 1. 파일 준비 (서버에서 변환 및 임시 저장)
            const result = await api.prepareBatchExport(targetProjectIds, {
                format: format,
                crs: crs.includes('5186') ? 'EPSG:5186' : crs.includes('4326') ? 'EPSG:4326' : 'EPSG:32652',
                gsd: gsd,
                custom_filename: filename || null,
            });

            // 인터벌 정리
            clearInterval(progressIntervalRef.current);

            // 2. 다운로드 트리거 (브라우저 메모리 사용 안함)
            api.triggerDirectDownload(result.download_id);

            // 3. 100% 표시 후 다이얼로그 닫기
            setProgress(100);
            onClose();

        } catch (err) {
            clearInterval(progressIntervalRef.current);
            console.error('Batch export failed:', err);
            alert('내보내기 실패: ' + err.message);
            setIsExporting(false);
            setProgress(0);
        }
    };

    if (!isOpen) return null;

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
                                    <option>GRS80 (EPSG:5186)</option>
                                    <option>WGS84 (EPSG:4326)</option>
                                    <option>UTM52N (EPSG:32652)</option>
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
                        <button disabled className="px-6 py-2 bg-slate-300 text-white rounded-lg font-bold text-sm cursor-wait">
                            처리 중...
                        </button>
                    )}
                </div>
            </div>
        </div>
    );
}
