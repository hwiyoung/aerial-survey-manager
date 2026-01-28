import React, { useState, useEffect } from 'react';
import { Settings, ArrowLeft, Loader2, X, CheckCircle2, AlertTriangle, Bookmark, Save, Trash2, Play } from 'lucide-react';
import api from '../../api/client';
import { useProcessingProgress } from '../../hooks/useProcessingProgress';

export default function ProcessingSidebar({ width, project, onCancel, onStartProcessing, onComplete, activeUploads = [] }) {
    const [isStarting, setIsStarting] = useState(false);
    const [presets, setPresets] = useState([]);
    const [defaultPresets, setDefaultPresets] = useState([]);
    const [selectedPresetId, setSelectedPresetId] = useState(null);
    const [loadingPresets, setLoadingPresets] = useState(true);
    const [isSaveModalOpen, setIsSaveModalOpen] = useState(false);
    const [newPresetName, setNewPresetName] = useState('');
    const [newPresetDesc, setNewPresetDesc] = useState('');

    // Processing options state
    const [options, setOptions] = useState({
        engine: 'odm',
        gsd: 5.0,
        output_crs: 'EPSG:5186',
        output_format: 'GeoTiff'
    });

    // Real-time processing progress via WebSocket
    const { progress: wsProgress, status: wsStatus, message: wsMessage, isConnected } = useProcessingProgress(
        project?.id || null  // Use project.id for WebSocket connection
    );

    // Load presets on mount
    useEffect(() => {
        const loadPresets = async () => {
            setLoadingPresets(true);
            try {
                const [userPresetsRes, defaultPresetsRes] = await Promise.all([
                    api.getPresets().catch(() => ({ items: [] })),
                    api.getDefaultPresets().catch(() => ({ items: [] }))
                ]);
                setPresets(userPresetsRes.items || []);
                setDefaultPresets(defaultPresetsRes.items || []);
            } catch (err) {
                console.error('Failed to load presets:', err);
            } finally {
                setLoadingPresets(false);
            }
        };
        loadPresets();
    }, []);

    // Trigger refresh when processing complete
    useEffect(() => {
        if ((wsStatus === 'complete' || wsStatus === 'completed') && onComplete) {
            onComplete();
        }
    }, [wsStatus, onComplete]);

    // Reset isStarting when statuses reflect actual progress
    useEffect(() => {
        if (isStarting && (
            wsStatus === 'processing' ||
            wsStatus === 'queued' ||
            project?.status === 'processing' ||
            project?.status === '진행중' ||
            project?.status === 'completed' ||
            project?.status === '완료'
        )) {
            setIsStarting(false);
        }
    }, [isStarting, wsStatus, project?.status]);

    // Apply preset options when selected
    const handlePresetSelect = (presetId) => {
        setSelectedPresetId(presetId);
        if (!presetId) return;

        const allPresets = [...presets, ...defaultPresets];
        const preset = allPresets.find(p => p.id === presetId);
        if (preset?.options) {
            setOptions({
                engine: preset.options.engine || 'odm',
                gsd: preset.options.gsd || 5.0,
                output_crs: preset.options.output_crs || 'EPSG:5186',
                output_format: preset.options.output_format || 'GeoTiff'
            });
        }
    };

    // Save current settings as new preset
    const handleSavePreset = async () => {
        if (!newPresetName.trim()) {
            alert('프리셋 이름을 입력하세요.');
            return;
        }
        try {
            const created = await api.createPreset({
                name: newPresetName.trim(),
                description: newPresetDesc.trim() || null,
                options: options,
                is_default: false
            });
            setPresets(prev => [...prev, created]);
            setSelectedPresetId(created.id);
            setIsSaveModalOpen(false);
            setNewPresetName('');
            setNewPresetDesc('');
            alert('프리셋이 저장되었습니다.');
        } catch (err) {
            console.error('Failed to save preset:', err);
            alert('프리셋 저장 실패: ' + err.message);
        }
    };

    // Delete a user preset
    const handleDeletePreset = async (presetId) => {
        if (!window.confirm('이 프리셋을 삭제하시겠습니까?')) return;
        try {
            await api.deletePreset(presetId);
            setPresets(prev => prev.filter(p => p.id !== presetId));
            if (selectedPresetId === presetId) setSelectedPresetId(null);
        } catch (err) {
            console.error('Failed to delete preset:', err);
            alert('삭제 실패: ' + err.message);
        }
    };

    // Start processing with current options
    const handleStart = async () => {
        setIsStarting(true);
        try {
            await onStartProcessing(options);
            // We set it to false here, but also rely on the useEffect for status-based reset
            setIsStarting(false);
        } catch (error) {
            console.error('Failed to start processing:', error);
            setIsStarting(false);
        }
    };

    return (
        <aside
            className="bg-white border-r border-slate-200 flex flex-col h-full z-10 shadow-xl shrink-0 relative overflow-hidden smooth-transition will-change-width"
            style={{
                width: width,
                animation: 'slideInFromLeft 0.35s cubic-bezier(0.4, 0, 0.2, 1) forwards'
            }}
        >
            <div className="p-5 border-b border-slate-200 bg-slate-50">
                <div className="flex items-center gap-3">
                    <button
                        onClick={onCancel}
                        className="p-1.5 rounded-lg hover:bg-slate-200 text-slate-500 transition-colors"
                        title="뒤로가기"
                    >
                        <ArrowLeft size={20} />
                    </button>
                    <div>
                        <h3 className="font-bold text-lg text-slate-800 flex items-center gap-2"><Settings className="text-blue-600" size={20} />처리 옵션 설정</h3>
                        <p className="text-xs text-slate-500 mt-1">프로젝트: {project?.title}</p>
                    </div>
                </div>
            </div>

            {/* Processing Progress Bar (shown when job is running) */}
            {(wsStatus === 'processing' || wsStatus === 'queued' || (wsStatus === 'connecting' && (project?.status === 'processing' || project?.status === '진행중'))) &&
                wsStatus !== 'complete' && wsStatus !== 'completed' && (
                    <div className="px-5 py-3 bg-blue-50 border-b border-blue-100">
                        <div className="flex justify-between items-center text-sm mb-2">
                            <span className="font-medium text-blue-800 flex items-center gap-2">
                                <Loader2 size={14} className="animate-spin" />
                                {wsStatus === 'connecting' ? '연결 중...' : '처리 진행 중'}
                            </span>
                            <span className="font-bold text-blue-600">{wsProgress}%</span>
                        </div>
                        <div className="h-2 bg-blue-100 rounded-full overflow-hidden">
                            <div
                                className="h-full bg-blue-600 transition-all duration-500 ease-out"
                                style={{ width: `${wsProgress}%` }}
                            />
                        </div>
                        {wsMessage && (
                            <p className="text-xs text-blue-600 mt-1 truncate font-medium">{wsMessage}</p>
                        )}

                        {/* Stop Button - Moved here for visibility */}
                        {(wsStatus === 'processing' || wsStatus === 'queued') && (
                            <div className="mt-4 pt-4 border-t border-blue-100/50">
                                <button
                                    onClick={async () => {
                                        if (!window.confirm('정말 처리를 중단하시겠습니까?')) return;
                                        try {
                                            await api.cancelProcessing(project.id);
                                        } catch (err) {
                                            alert('중단 실패: ' + err.message);
                                        }
                                    }}
                                    className="w-full flex items-center justify-center gap-2 py-2.5 bg-red-50 text-red-600 hover:bg-red-100 rounded-lg text-xs font-bold transition-all border border-red-200 shadow-sm"
                                >
                                    <X size={14} /> 처리 중단 (Stop Processing)
                                </button>
                            </div>
                        )}
                    </div>
                )}

            {/* Complete Status */}
            {(wsStatus === 'complete' || wsStatus === 'completed' || project?.status === 'completed' || project?.status === '완료') && (
                <div className="px-5 py-3 bg-emerald-50 border-b border-emerald-100 flex items-center gap-2 animate-in slide-in-from-top duration-300">
                    <CheckCircle2 size={16} className="text-emerald-600" />
                    <div>
                        <span className="text-sm font-bold text-emerald-800 block">처리가 완료되었습니다!</span>
                        <p className="text-[10px] text-emerald-600">결과물이 저장소에 성공적으로 업로드되었습니다.</p>
                    </div>
                </div>
            )}

            {/* Error Status */}
            {wsStatus === 'error' && (
                <div className="px-5 py-3 bg-red-50 border-b border-red-100 flex items-center gap-2">
                    <AlertTriangle size={16} className="text-red-600" />
                    <span className="text-sm font-medium text-red-800">처리 중 오류가 발생했습니다</span>
                </div>
            )}
            <div className="flex-1 overflow-y-auto custom-scrollbar p-5 space-y-6">
                {/* Preset Selection */}
                <div className="space-y-3">
                    <h4 className="text-sm font-bold text-slate-700 border-b pb-2 flex items-center gap-2">
                        <Bookmark size={14} className="text-blue-500" />프리셋 선택
                    </h4>
                    <div className="flex gap-2">
                        <select
                            className="flex-1 border border-slate-200 p-2 rounded text-sm bg-white"
                            value={selectedPresetId || ''}
                            onChange={(e) => handlePresetSelect(e.target.value || null)}
                            disabled={loadingPresets}
                        >
                            <option value="">-- 프리셋 선택 --</option>
                            {defaultPresets.length > 0 && (
                                <optgroup label="기본 프리셋">
                                    {defaultPresets.map(p => (
                                        <option key={p.id} value={p.id}>{p.name}</option>
                                    ))}
                                </optgroup>
                            )}
                            {presets.length > 0 && (
                                <optgroup label="내 프리셋">
                                    {presets.map(p => (
                                        <option key={p.id} value={p.id}>{p.name}</option>
                                    ))}
                                </optgroup>
                            )}
                        </select>
                        {selectedPresetId && presets.find(p => p.id === selectedPresetId) && (
                            <button
                                onClick={() => handleDeletePreset(selectedPresetId)}
                                className="p-2 text-red-500 hover:bg-red-50 rounded"
                                title="프리셋 삭제"
                            >
                                <Trash2 size={16} />
                            </button>
                        )}
                    </div>
                    <button
                        onClick={() => setIsSaveModalOpen(true)}
                        className="w-full text-sm text-blue-600 hover:text-blue-700 hover:bg-blue-50 py-2 rounded flex items-center justify-center gap-1"
                    >
                        <Save size={14} /> 현재 설정을 프리셋으로 저장
                    </button>
                </div>

                {/* Input Data Info */}
                <div className="space-y-3">
                    <h4 className="text-sm font-bold text-slate-700 border-b pb-2">1. 입력 데이터 정보</h4>
                    <div className="grid grid-cols-2 gap-4 text-sm"><div><span className="text-slate-500 block text-xs">이미지 수</span><span className="font-mono">{project?.imageCount || 0} 장</span></div><div><span className="text-slate-500 block text-xs">EO 데이터</span><span className="text-emerald-600 font-bold">로드됨</span></div></div>
                </div>

                {/* Processing Parameters */}
                <div className="space-y-3">
                    <h4 className="text-sm font-bold text-slate-700 border-b pb-2">2. 처리 엔진 및 파라미터</h4>

                    <div className="space-y-2">
                        <label className="block text-sm text-slate-600 font-medium">처리 엔진 (Engine)</label>
                        <div className="grid grid-cols-3 gap-2">
                            <button
                                onClick={() => setOptions(prev => ({ ...prev, engine: 'odm' }))}
                                className={`flex flex-col items-center gap-1.5 py-2.5 rounded-lg border-2 transition-all ${options.engine === 'odm' ? 'border-blue-500 bg-blue-50 text-blue-700' : 'border-slate-100 bg-white text-slate-400 hover:border-slate-200'}`}
                            >
                                <div className={`w-8 h-8 rounded-full flex items-center justify-center ${options.engine === 'odm' ? 'bg-blue-600 text-white' : 'bg-slate-100 text-slate-400'}`}>
                                    <span className="text-[10px] font-bold">ODM</span>
                                </div>
                                <span className="text-[10px] font-bold">오픈소스</span>
                            </button>

                            <button
                                onClick={() => setOptions(prev => ({ ...prev, engine: 'metashape' }))}
                                className={`flex flex-col items-center gap-1.5 py-2.5 rounded-lg border-2 transition-all ${options.engine === 'metashape' ? 'border-purple-500 bg-purple-50 text-purple-700' : 'border-slate-100 bg-white text-slate-400 hover:border-slate-200'}`}
                            >
                                <div className={`w-8 h-8 rounded-full flex items-center justify-center ${options.engine === 'metashape' ? 'bg-purple-600 text-white' : 'bg-slate-100 text-slate-400'}`}>
                                    <span className="text-[10px] font-bold">MS</span>
                                </div>
                                <span className="text-[10px] font-bold">Metashape</span>
                            </button>

                        </div>
                        <p className="text-[10px] text-slate-400">
                            {options.engine === 'odm' && 'OpenDroneMap을 사용하여 서버에서 직접 처리합니다.'}
                            {options.engine === 'metashape' && 'Agisoft Metashape SDK를 사용하여 고품질 정사영상을 생성합니다.'}
                        </p>
                    </div>

                    <div className="space-y-2">
                        <label className="block text-sm text-slate-600">GSD (cm/pixel)</label>
                        <input
                            type="number"
                            value={options.gsd}
                            onChange={(e) => setOptions(prev => ({ ...prev, gsd: parseFloat(e.target.value) || 5.0 }))}
                            className="border border-slate-200 p-2 rounded w-full text-sm"
                            step="0.5"
                            min="0.5"
                        />
                    </div>
                    <div className="space-y-2">
                        <label className="block text-sm text-slate-600">좌표계</label>
                        <select
                            className="w-full border border-slate-200 p-2 rounded text-sm bg-white"
                            value={options.output_crs}
                            onChange={(e) => setOptions(prev => ({ ...prev, output_crs: e.target.value }))}
                        >
                            <option value="EPSG:5186">GRS80 / TM Middle (EPSG:5186)</option>
                            <option value="EPSG:5187">GRS80 / TM East (EPSG:5187)</option>
                            <option value="EPSG:5185">GRS80 / TM West (EPSG:5185)</option>
                            <option value="EPSG:4326">WGS84 (EPSG:4326)</option>
                        </select>
                    </div>
                </div>

                {/* Output Format */}
                <div className="space-y-3">
                    <h4 className="text-sm font-bold text-slate-700 border-b pb-2">3. 출력 형식</h4>
                    <div className="flex gap-4">
                        <label className="flex items-center gap-2 text-sm cursor-pointer">
                            <input
                                type="radio"
                                name="output_format"
                                value="GeoTiff"
                                checked={options.output_format === 'GeoTiff'}
                                onChange={(e) => setOptions(prev => ({ ...prev, output_format: e.target.value }))}
                            /> GeoTiff
                        </label>
                        <label className="flex items-center gap-2 text-sm cursor-pointer">
                            <input
                                type="radio"
                                name="output_format"
                                value="JPG"
                                checked={options.output_format === 'JPG'}
                                onChange={(e) => setOptions(prev => ({ ...prev, output_format: e.target.value }))}
                            /> JPG
                        </label>
                    </div>
                </div>
            </div>
            <div className="p-5 border-t border-slate-200 bg-slate-50 flex gap-3">
                <button onClick={onCancel} className="flex-1 py-3 text-slate-600 font-bold text-sm hover:bg-slate-200 rounded-lg">취소</button>
                {(() => {
                    const uploadsInProgress = activeUploads.some(u => u.status === 'uploading' || u.status === 'waiting');
                    const hasImages = (project?.imageCount || 0) > 0;
                    const isProcessing = ((project?.status === 'processing' || project?.status === '진행중') ||
                        (wsStatus === 'processing' || wsStatus === 'queued') ||
                        (wsStatus === 'connecting' && (project?.status === 'processing' || project?.status === '진행중')) ||
                        isStarting) && (wsStatus !== 'complete' && wsStatus !== 'completed');
                    const isDisabled = !hasImages || uploadsInProgress || isProcessing;

                    let buttonText = '처리 시작';
                    if (!hasImages) buttonText = '업로드된 이미지 없음';
                    else if (uploadsInProgress) buttonText = `업로드 중... (${activeUploads.filter(u => u.status === 'completed').length}/${activeUploads.length})`;
                    else if (isProcessing) buttonText = '처리 중...';
                    else buttonText = `처리 시작 (${project?.imageCount || 0}장)`;

                    return (
                        <button
                            onClick={handleStart}
                            disabled={isDisabled}
                            className={`flex-[2] py-3 font-bold text-sm rounded-lg flex items-center justify-center gap-2 shadow-md transition-all
                ${isDisabled
                                    ? 'bg-slate-300 text-slate-500 cursor-not-allowed'
                                    : 'bg-blue-600 hover:bg-blue-700 text-white'}`}
                        >
                            <Play size={16} fill="currentColor" />
                            {buttonText}
                        </button>
                    );
                })()}
            </div>

            {/* Save Preset Modal */}
            {isSaveModalOpen && (
                <div className="fixed inset-0 z-[9999] flex items-center justify-center bg-black/50" onClick={() => setIsSaveModalOpen(false)}>
                    <div className="bg-white rounded-xl p-6 w-96 shadow-2xl" onClick={(e) => e.stopPropagation()}>
                        <h3 className="font-bold text-lg mb-4 flex items-center gap-2"><Save size={18} className="text-blue-600" /> 프리셋 저장</h3>
                        <div className="space-y-4">
                            <div>
                                <label className="block text-sm text-slate-600 mb-1">프리셋 이름 *</label>
                                <input
                                    type="text"
                                    value={newPresetName}
                                    onChange={(e) => setNewPresetName(e.target.value)}
                                    className="w-full border border-slate-200 p-2 rounded text-sm"
                                    placeholder="예: 고해상도 설정"
                                />
                            </div>
                            <div>
                                <label className="block text-sm text-slate-600 mb-1">설명 (선택)</label>
                                <textarea
                                    value={newPresetDesc}
                                    onChange={(e) => setNewPresetDesc(e.target.value)}
                                    className="w-full border border-slate-200 p-2 rounded text-sm"
                                    rows={2}
                                    placeholder="이 프리셋에 대한 설명"
                                />
                            </div>
                            <div className="bg-slate-50 p-3 rounded text-xs text-slate-600">
                                <strong>저장될 설정:</strong>
                                <div className="mt-1 grid grid-cols-2 gap-1">
                                    <span>GSD: {options.gsd} cm</span>
                                    <span>좌표계: {options.output_crs}</span>
                                    <span>형식: {options.output_format}</span>
                                </div>
                            </div>
                        </div>
                        <div className="flex gap-3 mt-6">
                            <button onClick={() => setIsSaveModalOpen(false)} className="flex-1 py-2 border border-slate-200 rounded text-sm font-medium hover:bg-slate-50">취소</button>
                            <button onClick={handleSavePreset} className="flex-1 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded text-sm font-bold">저장</button>
                        </div>
                    </div>
                </div>
            )}
        </aside>
    );
}
