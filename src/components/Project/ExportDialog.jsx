import React, { useState, useEffect, useMemo } from 'react';
import { X, Download, FileOutput } from 'lucide-react';
import api from '../../api/client';

// 처리 모드별 GSD 배율 (원본 GSD 기준)
const MULTIPLIER_BY_MODE = {
    'Preview': 16,  // 원본 GSD × 16 (저해상도)
    'Normal': 4,    // 원본 GSD × 4 (중간 해상도)
    'High': 1,      // 원본 GSD × 1 (원본 해상도)
};

// result_gsd가 없을 때 사용할 기본 원본 GSD (cm/pixel)
const DEFAULT_BASE_GSD = 3;

export default function ExportDialog({ isOpen, onClose, targetProjectIds, allProjects }) {
    const [format, setFormat] = useState('GeoTiff');
    const [crs, setCrs] = useState('GRS80 (EPSG:5186)');
    const [gsd, setGsd] = useState(6);  // 기본값을 Normal 모드 기준으로 변경
    const [filename, setFilename] = useState('');
    const [isExporting, setIsExporting] = useState(false);
    const [progress, setProgress] = useState(0);
    const progressIntervalRef = React.useRef(null);

    const targets = useMemo(() => {
        return allProjects.filter(p => targetProjectIds.includes(p.id));
    }, [allProjects, targetProjectIds]);

    // 프로젝트의 처리 모드와 실제 GSD에 따른 권장 내보내기 GSD 계산
    const { recommendedGsd, baseGsd } = useMemo(() => {
        if (targets.length === 1) {
            const project = targets[0];
            // 실제 처리 결과 GSD 사용 (없으면 기본값)
            const resultGsd = project.result_gsd || DEFAULT_BASE_GSD;
            // 프로젝트에 저장된 처리 모드 사용
            const mode = project.process_mode ||
                         project.processing_options?.process_mode ||
                         project.last_processing_options?.process_mode ||
                         'Normal';
            const multiplier = MULTIPLIER_BY_MODE[mode] || 4;
            // 권장 GSD = 원본 GSD × 배율
            const recommended = Math.round(resultGsd * multiplier * 100) / 100;
            return { recommendedGsd: recommended, baseGsd: resultGsd };
        }
        // 다중 프로젝트의 경우 기본값 (Normal 기준, 기본 GSD × 4)
        return { recommendedGsd: DEFAULT_BASE_GSD * 4, baseGsd: DEFAULT_BASE_GSD };
    }, [targets]);

    // 단일 프로젝트의 처리 모드 표시용
    const processMode = useMemo(() => {
        if (targets.length === 1) {
            const project = targets[0];
            return project.process_mode ||
                   project.processing_options?.process_mode ||
                   project.last_processing_options?.process_mode ||
                   null;
        }
        return null;
    }, [targets]);

    useEffect(() => {
        if (isOpen) {
            setIsExporting(false);
            setProgress(0);
            // 권장 GSD로 초기화
            setGsd(recommendedGsd);
            if (targets.length === 1) {
                setFilename(`${targets[0].title}_ortho`);
            } else {
                setFilename(`Bulk_Export_${new Date().toISOString().slice(0, 10)}`);
            }
        }
    }, [isOpen, targets, recommendedGsd]);

    const handleExportStart = async () => {
        setIsExporting(true);
        setProgress(5);

        // 자연스러운 진행률 시뮬레이션 (5% ~ 85%까지 점진적 증가)
        let currentProgress = 5;
        progressIntervalRef.current = setInterval(() => {
            currentProgress += Math.random() * 3 + 1; // 1~4% 랜덤 증가
            if (currentProgress >= 85) {
                currentProgress = 85;
                clearInterval(progressIntervalRef.current);
            }
            setProgress(Math.floor(currentProgress));
        }, 200);

        try {
            const blob = await api.batchExport(targetProjectIds, {
                format: format,
                crs: crs.includes('5186') ? 'EPSG:5186' : crs.includes('4326') ? 'EPSG:4326' : 'EPSG:32652',
                gsd: gsd,
                custom_filename: filename || null,
            });

            // API 완료 후 인터벌 정리
            clearInterval(progressIntervalRef.current);
            setProgress(90);

            const count = targetProjectIds.length;
            const ext = count === 1 ? 'tif' : 'zip';
            const name = filename || (count === 1 && targets[0] ? `${targets[0].title}_ortho` : 'batch_export');
            const downloadFilename = name.toLowerCase().endsWith('.' + ext) ? name : `${name}.${ext}`;

            api.downloadBlob(blob, downloadFilename);

            setProgress(100);
            setTimeout(() => {
                alert(`${targets.length}개 프로젝트 내보내기가 완료되었습니다.`);
                onClose();
            }, 300);

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
                            <label className="text-xs font-bold text-slate-500">
                                해상도 (GSD)
                                {processMode && (
                                    <span className="text-blue-500 ml-2 font-normal">
                                        처리 모드: {processMode}
                                    </span>
                                )}
                            </label>
                            <div className="flex gap-2">
                                <input type="number" className="border p-2 rounded text-sm w-full" value={gsd} onChange={e => setGsd(Number(e.target.value))} />
                                <span className="text-sm text-slate-500 self-center whitespace-nowrap">cm/pixel</span>
                            </div>
                            <p className="text-[10px] text-slate-400">
                                권장: {recommendedGsd} cm/pixel
                                {processMode && ` (원본 ${baseGsd}cm × ${MULTIPLIER_BY_MODE[processMode] || 4}, ${processMode} 모드)`}
                            </p>
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
