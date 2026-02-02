import React, { useState, useEffect } from 'react';
import { FileImage, Download, Loader2, X, AlertTriangle, CheckCircle2 } from 'lucide-react';
import api from '../../api/client';
import { useProcessingProgress } from '../../hooks/useProcessingProgress';

export default function InspectorPanel({ project, image, qcData, onQcUpdate, onCloseImage, onExport }) {
    const [isImageLoaded, setIsImageLoaded] = useState(false);
    const [isCancelling, setIsCancelling] = useState(false);

    // Real-time progress tracking
    const { progress: procProgress, status: procStatus, message: procMessage } = useProcessingProgress(
        (project?.status === '진행중' || project?.status === 'processing') ? project.id : null
    );

    useEffect(() => {
        setIsImageLoaded(false);
        if (image) {
            const t = setTimeout(() => setIsImageLoaded(true), 600);
            return () => clearTimeout(t);
        }
    }, [image]);

    const handleCancel = async () => {
        if (!window.confirm('정말 처리를 중단하시겠습니까?')) return;
        setIsCancelling(true);
        try {
            await api.cancelProcessing(project.id);
        } catch (err) {
            alert('중단 요청 실패: ' + err.message);
        } finally {
            setIsCancelling(false);
        }
    };

    if (!project) return <div className="flex h-full items-center justify-center bg-slate-50 text-slate-400">프로젝트를 선택하세요</div>;

    if (!image) {
        return (
            <div className="flex h-full w-full bg-white text-slate-800">
                <div className="w-1/3 min-w-[300px] border-r border-slate-200 p-6 overflow-y-auto">
                    <div className="flex items-center gap-2 mb-2"><span className="px-2 py-0.5 rounded text-[10px] font-bold bg-slate-100 text-slate-600 border border-slate-200">BLOCK</span><span className="text-xs text-slate-400 font-mono">{project.id}</span></div>
                    <h2 className="text-2xl font-bold leading-tight mb-6">{project.title}</h2>
                    <div className="space-y-4 text-sm">
                        <div className="flex justify-between border-b pb-2"><span className="text-slate-500">권역/업체</span><span className="font-medium">{project.region}/{project.company}</span></div>
                        <div className="flex justify-between border-b pb-2"><span className="text-slate-500">상태</span><span className={`font-bold ${project.status === '완료' || project.status === 'completed' ? 'text-emerald-600' : project.status === '오류' || project.status === 'error' ? 'text-red-600' : 'text-blue-600'}`}>{project.status === 'completed' ? '완료' : project.status}</span></div>
                        <div className="flex justify-between border-b pb-2"><span className="text-slate-500">원본사진</span><span className="font-medium">{project.image_count || project.imageCount || 0}장</span></div>
                        {project.source_size && (
                            <div className="flex justify-between border-b pb-2">
                                <span className="text-slate-500">원본 총 용량</span>
                                <span className="font-medium">{(project.source_size / (1024 * 1024 * 1024)).toFixed(2)} GB</span>
                            </div>
                        )}
                        {project.ortho_size && (
                            <div className="flex justify-between border-b pb-2">
                                <span className="text-slate-500">정사영상 용량</span>
                                <span className="font-medium">{(project.ortho_size / (1024 * 1024 * 1024)).toFixed(2)} GB</span>
                            </div>
                        )}
                        {project.area && (
                            <div className="flex justify-between border-b pb-2">
                                <span className="text-slate-500">정사영상 면적</span>
                                <span className="font-medium text-blue-600 font-bold">{project.area.toFixed(3)} km²</span>
                            </div>
                        )}
                        {project.startDate && <div className="flex justify-between border-b pb-2"><span className="text-slate-500">촬영일</span><span className="font-medium">{project.startDate}</span></div>}
                    </div>
                </div>
                <div className="flex-1 p-6 bg-slate-50 overflow-y-auto">
                    {project.orthoResult ? (
                        <div className="bg-white border border-slate-200 rounded-xl p-5 shadow-sm flex flex-wrap items-center justify-between gap-4">
                            <div className="flex items-center gap-4 min-w-0">
                                <div className="p-3 bg-blue-50 text-blue-600 rounded-lg shrink-0">
                                    <FileImage size={24} />
                                </div>
                                <div className="min-w-0">
                                    <div className="font-bold text-slate-800 truncate">Result_Ortho.tif</div>
                                    <div className="text-xs text-slate-500">{project.orthoResult.fileSize}</div>
                                </div>
                            </div>
                            <button
                                onClick={onExport}
                                disabled={project.status !== '완료' && project.status !== 'completed'}
                                className="bg-slate-800 hover:bg-slate-900 disabled:bg-slate-300 text-white px-4 py-2 rounded text-sm flex items-center gap-2 transition-colors font-bold shadow-sm whitespace-nowrap ml-auto sm:ml-0"
                            >
                                <Download size={16} /> 정사영상 내보내기
                            </button>
                        </div>
                    ) : (
                        <div className="flex flex-col items-center justify-center min-h-[160px] border-2 border-dashed border-slate-300 rounded-xl text-slate-400 gap-4 p-6 bg-white shadow-inner">
                            <div className="relative">
                                <Loader2 size={32} className={(project.status === '진행중' || project.status === 'processing') ? "animate-spin text-blue-500" : ""} />
                                {(procProgress > 0) && (
                                    <div className="absolute inset-0 flex items-center justify-center text-[8px] font-bold text-blue-700">
                                        {procProgress}%
                                    </div>
                                )}
                            </div>
                            <div className="text-center">
                                <p className="text-lg font-bold text-slate-600">
                                    {(project.status === '진행중' || project.status === 'processing') ? '데이터 처리 중입니다' : '정사영상 결과가 없습니다'}
                                </p>
                                {(project.status === '진행중' || project.status === 'processing') && (
                                    <div className="mt-4 space-y-3">
                                        <p className="text-sm text-blue-500 font-medium">현재 단계: {procMessage || '초기화 중...'}</p>
                                        <div className="w-64 h-2 bg-slate-100 rounded-full overflow-hidden mx-auto">
                                            <div className="h-full bg-blue-500 transition-all duration-500" style={{ width: `${procProgress}%` }} />
                                        </div>
                                        <button
                                            onClick={handleCancel}
                                            disabled={isCancelling}
                                            className="text-xs text-red-500 hover:text-red-700 font-bold px-3 py-1 bg-red-50 rounded-full border border-red-100 transition-colors disabled:opacity-50"
                                        >
                                            {isCancelling ? '중단 중...' : '작업 중단 (Stop)'}
                                        </button>
                                    </div>
                                )}
                            </div>
                        </div>
                    )}
                </div>
            </div>
        );
    }

    return (
        <div className="flex flex-col h-full bg-white">
            <div className="h-14 border-b border-slate-200 px-6 flex items-center justify-between bg-slate-50 shrink-0">
                <div className="flex items-center gap-3">
                    <button onClick={onCloseImage} className="p-1 hover:bg-slate-200 rounded text-slate-500"><X size={20} /></button>
                    <h3 className="font-bold text-slate-800">이미지 조사기: {image.name}</h3>
                </div>
            </div>
            <div className="flex-1 flex overflow-hidden">
                <div className="flex-1 bg-slate-900 flex items-center justify-center relative group p-10">
                    {!isImageLoaded ? (
                        <div className="flex flex-col items-center gap-3 text-white/50"><Loader2 size={40} className="animate-spin" /><span className="text-sm font-medium">Loading High Resolution Image...</span></div>
                    ) : (
                        <div className="relative w-full h-full flex items-center justify-center">
                            <img src={image.thumbnail_url} alt={image.name} className="max-w-full max-h-full object-contain shadow-2xl transition-transform duration-500 hover:scale-[1.02]" />
                            <div className="absolute inset-x-0 bottom-0 p-8 bg-gradient-to-t from-black/80 to-transparent opacity-0 group-hover:opacity-100 transition-opacity">
                                <div className="flex gap-10 text-white">
                                    <div><span className="text-[10px] text-white/50 block font-bold uppercase tracking-widest mb-1">Coordinates</span><span className="font-mono text-sm">{image.wy.toFixed(6)}, {image.wx.toFixed(6)}</span></div>
                                    <div><span className="text-[10px] text-white/50 block font-bold uppercase tracking-widest mb-1">Altitude</span><span className="font-mono text-sm">{image.z}m</span></div>
                                    <div><span className="text-[10px] text-white/50 block font-bold uppercase tracking-widest mb-1">Rotation (ω/φ/κ)</span><span className="font-mono text-sm">{image.omega.toFixed(2)}° / {image.phi.toFixed(2)}° / {image.kappa.toFixed(2)}°</span></div>
                                </div>
                            </div>
                        </div>
                    )}
                </div>
                <div className="w-80 border-l border-slate-200 p-6 overflow-y-auto bg-white space-y-8">
                    <section>
                        <h4 className="text-[10px] font-bold text-slate-400 uppercase tracking-widest mb-4">Quality Control (QC)</h4>
                        <div className="space-y-4">
                            <div className="flex items-center justify-between p-3 bg-slate-50 rounded-lg border border-slate-200">
                                <span className="text-sm font-medium">초점 (Focus)</span>
                                <button onClick={() => onQcUpdate && onQcUpdate({ ...qcData, focus: !qcData.focus })} className={`w-12 h-6 rounded-full relative transition-colors ${qcData.focus ? 'bg-emerald-500' : 'bg-slate-300'}`}><div className={`absolute top-1 w-4 h-4 bg-white rounded-full transition-all ${qcData.focus ? 'right-1' : 'left-1'}`} /></button>
                            </div>
                            <div className="flex items-center justify-between p-3 bg-slate-50 rounded-lg border border-slate-200">
                                <span className="text-sm font-medium">노출 (Exposure)</span>
                                <button onClick={() => onQcUpdate && onQcUpdate({ ...qcData, exposure: !qcData.exposure })} className={`w-12 h-6 rounded-full relative transition-colors ${qcData.exposure ? 'bg-emerald-500' : 'bg-slate-300'}`}><div className={`absolute top-1 w-4 h-4 bg-white rounded-full transition-all ${qcData.exposure ? 'right-1' : 'left-1'}`} /></button>
                            </div>
                        </div>
                    </section>
                    <section>
                        <h4 className="text-[10px] font-bold text-slate-400 uppercase tracking-widest mb-4">Remarks</h4>
                        <textarea placeholder="조사 내용을 입력하세요..." className="w-full h-32 p-3 border border-slate-200 rounded-lg text-sm bg-slate-50 resize-none focus:ring-2 focus:ring-blue-500 transition-all shadow-inner" />
                        <button className="w-full mt-4 py-3 bg-slate-800 text-white rounded-lg text-sm font-bold shadow-md hover:bg-slate-900 transition-all">조사 완료 저장</button>
                    </section>
                </div>
            </div>
        </div>
    );
}
