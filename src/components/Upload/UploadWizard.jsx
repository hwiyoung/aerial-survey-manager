import React, { useState, useEffect, useMemo, useRef } from 'react';
import { UploadCloud, FileText, CheckCircle2, ChevronRight, ChevronLeft, AlertCircle, X, Camera, FolderOpen, Info, Trash2, Image as ImageIcon, FilePlus, ArrowRight, ArrowLeft, Table as TableIcon, RefreshCw, AlertTriangle } from 'lucide-react';

const IMAGE_EXTENSIONS = ['.jpg', '.jpeg', '.png', '.tif', '.tiff', '.dng', '.raw', '.arw', '.cr2', '.nef'];

const isImageFile = (file) => {
    if (file.type.startsWith('image/')) return true;
    const ext = file.name.toLowerCase().substring(file.name.lastIndexOf('.'));
    return IMAGE_EXTENSIONS.includes(ext);
};
import api from '../../api/client';

export default function UploadWizard({ isOpen, onClose, onComplete }) {
    const [step, setStep] = useState(1);
    const [imageCount, setImageCount] = useState(0);
    const [eoFileName, setEoFileName] = useState(null);
    const [cameraModel, setCameraModel] = useState("");
    const [cameraModels, setCameraModels] = useState([]);
    const [isAddingCamera, setIsAddingCamera] = useState(false);
    const [newCamera, setNewCamera] = useState({
        name: '',
        focal_length: 80,
        sensor_width: 53.4,
        sensor_height: 40,
        pixel_size: 5.2,
        sensor_width_px: 17310,
        sensor_height_px: 11310,
        ppa_x: 0,
        ppa_y: 0
    });
    const [projectName, setProjectName] = useState('');
    const [showMismatchWarning, setShowMismatchWarning] = useState(false);

    useEffect(() => {
        if (isOpen) {
            api.getCameraModels().then(models => {
                setCameraModels(models);
                // Set default to first camera model if not already set
                if (models.length > 0 && !cameraModel) {
                    setCameraModel(models[0].name);
                }
            }).catch(console.error);
        }
    }, [isOpen]);

    const selectedCamera = useMemo(() => {
        return cameraModels.find(c => c.name === cameraModel) || { focal_length: 0, sensor_width: 0, sensor_height: 0, pixel_size: 0 };
    }, [cameraModel, cameraModels]);

    const handleAddCamera = async () => {
        try {
            const created = await api.createCameraModel({ ...newCamera, name: newCamera.name || 'Custom Camera' });
            setCameraModels(prev => [...prev, created]);
            setCameraModel(created.name);
            setIsAddingCamera(false);
        } catch (err) {
            alert("Failed to add camera model");
        }
    };
    const [selectedFiles, setSelectedFiles] = useState([]);
    const [selectedEoFile, setSelectedEoFile] = useState(null);
    const [eoConfig, setEoConfig] = useState({ delimiter: ',', hasHeader: true, crs: 'TM중부 (EPSG:5186)', columns: { image_name: 0, x: 1, y: 2, z: 3, omega: 4, phi: 5, kappa: 6 } });

    const folderInputRef = useRef(null);
    const fileInputRef = useRef(null);
    const eoInputRef = useRef(null);
    const [selectionMode, setSelectionMode] = useState(null); // 'folder' or 'files'

    const [rawEoData, setRawEoData] = useState(`ImageID,Lat,Lon,Alt,Omega,Phi,Kappa
IMG_001,37.1234,127.5543,150.2,0.1,-0.2,1.5
IMG_002,37.1235,127.5544,150.3,0.1,-0.2,1.5
IMG_003,37.1236,127.5545,150.2,0.0,-0.2,1.4
IMG_004,37.1237,127.5546,150.1,0.2,-0.1,1.3`);

    const parsedPreview = useMemo(() => {
        if (!eoFileName) return [];
        const lines = rawEoData.split('\n');
        const startIdx = eoConfig.hasHeader ? 1 : 0;
        const previewLines = lines.slice(startIdx, startIdx + 8);
        return previewLines.map((line, idx) => {
            let parts = [];
            if (eoConfig.delimiter === 'tab') parts = line.split('\t');
            else if (eoConfig.delimiter === 'space') parts = line.split(/\s+/);
            else parts = line.split(eoConfig.delimiter);
            parts = parts.map(p => p.trim()).filter(p => p !== '');
            const getVal = (colIdx) => parts[colIdx] || '-';
            return {
                key: idx,
                image_name: getVal(eoConfig.columns.image_name),
                x: getVal(eoConfig.columns.x),
                y: getVal(eoConfig.columns.y),
                z: getVal(eoConfig.columns.z),
                omega: getVal(eoConfig.columns.omega),
                phi: getVal(eoConfig.columns.phi),
                kappa: getVal(eoConfig.columns.kappa),
            };
        });
    }, [eoConfig, eoFileName, rawEoData]);

    useEffect(() => {
        if (isOpen) {
            setStep(1);
            setImageCount(0);
            setEoFileName(null);
            setEoConfig({ delimiter: ',', hasHeader: true, crs: 'TM중부 (EPSG:5186)', columns: { image_name: 0, x: 1, y: 2, z: 3, omega: 4, phi: 5, kappa: 6 } });
            setProjectName('');
            setShowMismatchWarning(false);
            setSelectedFiles([]);
            setSelectedEoFile(null);
        }
    }, [isOpen]);

    // ESC key handler to close modal
    useEffect(() => {
        const handleKeyDown = (e) => {
            if (e.key === 'Escape' && !showMismatchWarning) {
                if (imageCount > 0 || eoFileName) {
                    if (window.confirm('업로드를 취소하시겠습니까? 모든 선택이 초기화됩니다.')) {
                        onClose();
                    }
                } else {
                    onClose();
                }
            }
        };
        if (isOpen) {
            document.addEventListener('keydown', handleKeyDown);
        }
        return () => document.removeEventListener('keydown', handleKeyDown);
    }, [isOpen, imageCount, eoFileName, showMismatchWarning, onClose]);

    const handleFolderSelect = (e) => {
        const allFiles = Array.from(e.target.files);
        const imageFiles = allFiles.filter(isImageFile);

        if (imageFiles.length < allFiles.length) {
            console.log(`${allFiles.length - imageFiles.length} files filtered out from folder`);
        }

        setSelectedFiles(imageFiles); // Replace existing files for folder selection
        setImageCount(imageFiles.length);
        setSelectionMode('folder');
        // Clear the other input
        if (fileInputRef.current) fileInputRef.current.value = '';
        // Auto-set project name from folder name if not set
        if (!projectName && allFiles.length > 0) {
            const path = allFiles[0].webkitRelativePath || '';
            const folderName = path.split('/')[0];
            if (folderName) setProjectName(folderName);
        }
    };
    const handleFileSelect = (e) => {
        const files = Array.from(e.target.files);
        const imageFiles = files.filter(isImageFile);

        if (imageFiles.length < files.length) {
            alert(`${files.length - imageFiles.length}개의 비이미지 파일이 제외되었습니다.`);
        }

        setSelectedFiles(imageFiles); // Replace existing files for individual file selection
        setImageCount(imageFiles.length);
        setSelectionMode('files');
        // Clear the other input
        if (folderInputRef.current) folderInputRef.current.value = '';
    };

    const handleEoFileSelect = (e) => {
        const file = e.target.files[0];
        if (file) {
            setSelectedEoFile(file);
            setEoFileName(file.name);

            const reader = new FileReader();
            reader.onload = (e) => {
                setRawEoData(e.target.result);
            };
            reader.readAsText(file);
        }
    };

    // Count EO data lines (excluding header if applicable)
    const eoLineCount = useMemo(() => {
        if (!rawEoData) return 0;
        const lines = rawEoData.split('\n').filter(l => l.trim());
        return eoConfig.hasHeader ? Math.max(0, lines.length - 1) : lines.length;
    }, [rawEoData, eoConfig.hasHeader]);

    const handleProceedToStep4 = () => {
        if (imageCount !== eoLineCount) {
            setShowMismatchWarning(true);
        } else {
            setStep(4);
        }
    };

    const handleConfirmMismatch = () => {
        setShowMismatchWarning(false);
        setStep(4);
    };

    const handleCancelUpload = () => {
        if (imageCount > 0 || eoFileName) {
            if (window.confirm('업로드를 취소하시겠습니까? 모든 선택이 초기화됩니다.')) {
                onClose();
            }
        } else {
            onClose();
        }
    };

    const handleFinish = async () => {
        // Pass raw data to parent for processing
        const projectData = {
            title: projectName || `Project_${new Date().toISOString().slice(0, 19).replace(/[-:T]/g, '')}`,
            region: '수도권북부 권역',
            company: '신규 업로드',
        };

        console.log('handleFinish - selectedEoFile:', selectedEoFile); // DEBUG
        await onComplete({
            projectData,
            files: selectedFiles,
            eoFile: selectedEoFile,
            eoConfig,
            cameraModel
        });
        onClose();
    };

    if (!isOpen) return null;

    return (
        <div className="fixed inset-0 z-[1000] flex items-center justify-center bg-black/60 backdrop-blur-sm animate-in fade-in duration-200" onClick={handleCancelUpload}>
            <div className="bg-white rounded-xl shadow-2xl w-[900px] flex flex-col max-h-[95vh]" onClick={e => e.stopPropagation()}>
                <div className="h-16 border-b border-slate-200 flex items-center justify-between px-8 bg-slate-50">
                    <h3 className="font-bold text-slate-800 text-lg flex items-center gap-2"><UploadCloud size={24} className="text-blue-600" />새 프로젝트 데이터 업로드</h3>
                    <div className="flex items-center gap-3">
                        <div className="flex items-center gap-1">{[1, 2, 3, 4].map(s => (<div key={s} className={`w-2 h-2 rounded-full ${step === s ? 'bg-blue-600 scale-125' : step > s ? 'bg-blue-300' : 'bg-slate-200'}`} />))}</div>
                        <button onClick={handleCancelUpload} className="p-1.5 text-slate-400 hover:text-slate-600 hover:bg-slate-200 rounded-lg transition-colors" title="닫기"><X size={20} /></button>
                    </div>
                </div>
                <div className="p-8 flex-1 overflow-y-auto min-h-[500px]">
                    {step === 1 && (
                        <div className="space-y-6 max-w-2xl mx-auto h-full flex flex-col justify-center">
                            <h4 className="text-xl font-bold text-slate-800 text-center mb-6">1. 원본 이미지 선택</h4>
                            <div className="grid grid-cols-2 gap-4">
                                <input
                                    type="file"
                                    webkitdirectory="true"
                                    directory="true"
                                    ref={folderInputRef}
                                    onChange={handleFolderSelect}
                                    className="hidden"
                                />
                                <input
                                    id="file-upload"
                                    type="file"
                                    multiple
                                    ref={fileInputRef}
                                    onChange={handleFileSelect}
                                    className="hidden"
                                    accept="image/*,.tif,.tiff,.dng,.raw,.arw,.cr2,.nef"
                                />
                                <button
                                    onClick={() => folderInputRef.current.click()}
                                    className={`p-10 border-2 rounded-xl flex flex-col items-center gap-4 transition-all ${selectionMode === 'folder' ? 'border-blue-500 bg-blue-50' : 'border-slate-200 hover:border-blue-300'}`}
                                >
                                    <FolderOpen size={48} className="text-blue-600" />
                                    <div>
                                        <div className="font-bold text-slate-700 text-lg">폴더 선택</div>
                                        <div className="text-sm text-slate-500">폴더 내 전체 로드</div>
                                    </div>
                                </button>
                                <button
                                    onClick={() => fileInputRef.current.click()}
                                    className={`p-10 border-2 rounded-xl flex flex-col items-center gap-4 transition-all ${selectionMode === 'files' ? 'border-blue-500 bg-blue-50' : 'border-slate-200 hover:border-blue-300'}`}
                                >
                                    <FilePlus size={48} className="text-emerald-600" />
                                    <div>
                                        <div className="font-bold text-slate-700 text-lg">이미지 선택</div>
                                        <div className="text-sm text-slate-500">개별 파일 선택</div>
                                    </div>
                                </button>
                            </div>
                            {imageCount > 0 && <div className="text-center p-4 bg-slate-100 rounded-lg text-slate-700 animate-in fade-in flex items-center justify-center gap-2"><CheckCircle2 size={20} className="text-blue-600" />총 <span className="font-bold text-blue-600">{imageCount}</span>장의 이미지가 확인되었습니다.</div>}
                        </div>
                    )}
                    {step === 2 && (
                        <div className="flex flex-col h-full gap-6">
                            <div className="flex justify-between items-center shrink-0"><h4 className="text-xl font-bold text-slate-800">2. EO (Exterior Orientation) 로드 및 설정</h4><button onClick={() => { setEoConfig({ delimiter: ',', hasHeader: true, crs: 'TM중부 (EPSG:5186)', columns: { image_name: 0, x: 1, y: 2, z: 3, omega: 4, phi: 5, kappa: 6 } }); setEoFileName(null); setSelectedEoFile(null); if (eoInputRef.current) eoInputRef.current.value = ''; }} className="text-xs flex items-center gap-1 text-slate-500 hover:text-blue-600 bg-slate-100 px-2 py-1 rounded"><RefreshCw size={12} /> 설정 초기화</button></div>
                            <div className="flex gap-6 shrink-0 h-[220px]">
                                <input
                                    type="file"
                                    accept=".txt,.csv,.json"
                                    ref={eoInputRef}
                                    onChange={handleEoFileSelect}
                                    className="hidden"
                                />
                                <div
                                    className={`w-1/4 border-2 border-dashed rounded-xl flex flex-col items-center justify-center gap-3 cursor-pointer transition-colors ${eoFileName ? 'border-emerald-500 bg-emerald-50' : 'border-slate-300 hover:bg-slate-50'}`}
                                    onClick={() => eoInputRef.current.click()}
                                >
                                    {eoFileName ? (<><div className="p-3 bg-emerald-100 rounded-full text-emerald-600"><FileText size={32} /></div><div className="text-center px-4"><div className="text-sm font-bold text-slate-800 truncate max-w-[150px]">{eoFileName}</div><div className="text-[10px] text-emerald-600 font-bold mt-1">로드 성공</div></div></>) : (<><div className="p-3 bg-slate-100 rounded-full text-slate-400"><UploadCloud size={32} /></div><div className="text-center"><div className="text-sm font-bold text-slate-600">EO 파일 선택</div><div className="text-xs text-slate-400 mt-1">.txt, .csv, .json</div></div></>)}
                                </div>
                                <div className="flex-1 bg-slate-50 p-5 rounded-xl border border-slate-200 flex flex-col justify-between">
                                    <div className="grid grid-cols-3 gap-6">
                                        <div className="space-y-1.5"><label className="text-xs font-bold text-slate-500 block">좌표계 (CRS)</label><select className="w-full text-sm border p-2.5 rounded-lg bg-white shadow-sm" value={eoConfig.crs} onChange={(e) => setEoConfig({ ...eoConfig, crs: e.target.value })}><option value="TM중부 (EPSG:5186)">TM 중부 (EPSG:5186)</option><option value="TM서부 (EPSG:5185)">TM 서부 (EPSG:5185)</option><option value="TM동부 (EPSG:5187)">TM 동부 (EPSG:5187)</option><option value="UTM-K (EPSG:5179)">UTM-K (EPSG:5179)</option><option value="WGS84 (EPSG:4326)">WGS84 (EPSG:4326)</option></select></div>
                                        <div className="space-y-1.5"><label className="text-xs font-bold text-slate-500 block">구분자</label><select className="w-full text-sm border p-2.5 rounded-lg bg-white shadow-sm" value={eoConfig.delimiter} onChange={(e) => setEoConfig({ ...eoConfig, delimiter: e.target.value })}><option value=",">콤마 (,)</option><option value="tab">탭 (Tab)</option><option value="space">공백 (Space)</option></select></div>
                                        <div className="space-y-1.5"><label className="text-xs font-bold text-slate-500 block">헤더 행</label><select className="w-full text-sm border p-2.5 rounded-lg bg-white shadow-sm" value={eoConfig.hasHeader} onChange={(e) => setEoConfig({ ...eoConfig, hasHeader: e.target.value === 'true' })}><option value="true">첫 줄 제외 (Skip)</option><option value="false">포함 (Include)</option></select></div>
                                    </div>
                                    <div className="pt-4 border-t border-slate-200">
                                        <label className="text-xs font-bold text-slate-500 mb-2 block">열 번호 매핑 (Column Index)</label>
                                        <div className="flex gap-3">{Object.entries(eoConfig.columns).map(([key, val]) => (<div key={key} className="flex-1 bg-white p-1.5 rounded border border-slate-200 flex flex-col items-center"><span className="text-[10px] font-bold text-slate-400 uppercase mb-1">{key}</span><input type="number" min="0" className="w-full text-center font-mono text-sm font-bold text-blue-600 bg-transparent outline-none" value={val} onChange={(e) => setEoConfig({ ...eoConfig, columns: { ...eoConfig.columns, [key]: parseInt(e.target.value) || 0 } })} /></div>))}</div>
                                    </div>
                                </div>
                            </div>
                            <div className="flex-1 min-h-0 flex flex-col bg-white rounded-xl border border-slate-200 overflow-hidden shadow-sm">
                                <div className="p-3 border-b border-slate-100 bg-slate-50 flex justify-between items-center shrink-0"><span className="text-sm font-bold text-slate-700 flex items-center gap-2"><TableIcon size={16} className="text-slate-400" /> 데이터 파싱 미리보기</span>{eoFileName && <span className="text-[10px] text-blue-600 bg-blue-50 px-2 py-1 rounded font-bold">실시간 업데이트 중</span>}</div>
                                <div className="flex-1 overflow-auto custom-scrollbar relative">
                                    {!eoFileName ? (<div className="absolute inset-0 flex flex-col items-center justify-center text-slate-300"><FileText size={48} className="mb-3 opacity-30" /><p className="text-sm font-medium">상단에서 EO 파일을 로드하면<br />이곳에 미리보기가 표시됩니다.</p></div>) : (
                                        <table className="w-full text-sm text-left"><thead className="bg-slate-50 sticky top-0 z-10 text-slate-500 text-xs uppercase"><tr><th className="p-3 border-b font-semibold w-[15%]">Image ID ({eoConfig.columns.image_name})</th><th className="p-3 border-b font-semibold">Lon/X ({eoConfig.columns.x})</th><th className="p-3 border-b font-semibold">Lat/Y ({eoConfig.columns.y})</th><th className="p-3 border-b font-semibold">Alt/Z ({eoConfig.columns.z})</th><th className="p-3 border-b font-semibold">Ω ({eoConfig.columns.omega})</th><th className="p-3 border-b font-semibold">Φ ({eoConfig.columns.phi})</th><th className="p-3 border-b font-semibold">K ({eoConfig.columns.kappa})</th></tr></thead><tbody className="divide-y divide-slate-100">{parsedPreview.map((row) => (<tr key={row.key} className="hover:bg-blue-50 transition-colors group"><td className="p-3 font-mono text-slate-700 font-medium group-hover:text-blue-700">{row.image_name}</td><td className="p-3 font-mono text-slate-500">{row.x}</td><td className="p-3 font-mono text-slate-500">{row.y}</td><td className="p-3 font-mono text-slate-500">{row.z}</td><td className="p-3 font-mono text-slate-400">{row.omega}</td><td className="p-3 font-mono text-slate-400">{row.phi}</td><td className="p-3 font-mono text-slate-400">{row.kappa}</td></tr>))}</tbody></table>
                                    )}
                                </div>
                            </div>
                        </div>
                    )}
                    {step === 3 && (
                        <div className="space-y-6 text-center max-w-2xl mx-auto h-full flex flex-col justify-center overflow-y-auto py-4">
                            <h4 className="text-xl font-bold text-slate-800">3. 카메라 모델 (IO) 선택</h4>
                            <div className="max-w-sm mx-auto space-y-6 w-full pb-4">
                                <div className="p-6 bg-slate-50 rounded-full w-32 h-32 mx-auto flex items-center justify-center border border-slate-200 shrink-0"><Camera size={56} className="text-slate-400" /></div>

                                {isAddingCamera ? (
                                    <div className="bg-white p-6 rounded-xl border border-blue-200 shadow-lg space-y-4 text-left animate-in fade-in zoom-in-95 duration-200">
                                        <div className="flex justify-between items-center mb-2">
                                            <h5 className="font-bold text-blue-600">새 카메라 추가</h5>
                                            <button onClick={() => setIsAddingCamera(false)} className="text-slate-400 hover:text-slate-600"><X size={16} /></button>
                                        </div>
                                        <div className="space-y-1">
                                            <label className="text-xs font-bold text-slate-500">모델명</label>
                                            <input type="text" className="w-full p-2 border rounded text-sm focus:ring-2 focus:ring-blue-500 outline-none" value={newCamera.name} onChange={e => setNewCamera({ ...newCamera, name: e.target.value })} placeholder="Ex: Sony A7R IV" autoFocus />
                                        </div>
                                        <div className="grid grid-cols-2 gap-3">
                                            <div className="space-y-1">
                                                <label className="text-xs font-bold text-slate-500">초점거리 (mm)</label>
                                                <input type="number" className="w-full p-2 border rounded text-sm" value={newCamera.focal_length} onChange={e => setNewCamera({ ...newCamera, focal_length: parseFloat(e.target.value) })} />
                                            </div>
                                            <div className="space-y-1">
                                                <label className="text-xs font-bold text-slate-500">Pixel Size (µm)</label>
                                                <input type="number" className="w-full p-2 border rounded text-sm" value={newCamera.pixel_size} onChange={e => setNewCamera({ ...newCamera, pixel_size: parseFloat(e.target.value) })} />
                                            </div>
                                        </div>
                                        <div className="grid grid-cols-2 gap-3">
                                            <div className="space-y-1">
                                                <label className="text-xs font-bold text-slate-500">Sensor W (mm)</label>
                                                <input type="number" className="w-full p-2 border rounded text-sm" value={newCamera.sensor_width} onChange={e => setNewCamera({ ...newCamera, sensor_width: parseFloat(e.target.value) })} />
                                            </div>
                                            <div className="space-y-1">
                                                <label className="text-xs font-bold text-slate-500">Sensor H (mm)</label>
                                                <input type="number" className="w-full p-2 border rounded text-sm" value={newCamera.sensor_height} onChange={e => setNewCamera({ ...newCamera, sensor_height: parseFloat(e.target.value) })} />
                                            </div>
                                        </div>
                                        <div className="grid grid-cols-2 gap-3">
                                            <div className="space-y-1">
                                                <label className="text-xs font-bold text-slate-500">이미지 W (px)</label>
                                                <input type="number" className="w-full p-2 border rounded text-sm" value={newCamera.sensor_width_px} onChange={e => setNewCamera({ ...newCamera, sensor_width_px: parseInt(e.target.value) })} />
                                            </div>
                                            <div className="space-y-1">
                                                <label className="text-xs font-bold text-slate-500">이미지 H (px)</label>
                                                <input type="number" className="w-full p-2 border rounded text-sm" value={newCamera.sensor_height_px} onChange={e => setNewCamera({ ...newCamera, sensor_height_px: parseInt(e.target.value) })} />
                                            </div>
                                        </div>
                                        <div className="grid grid-cols-2 gap-3">
                                            <div className="space-y-1">
                                                <label className="text-xs font-bold text-slate-500">PPA X (mm)</label>
                                                <input type="number" step="0.001" className="w-full p-2 border rounded text-sm" value={newCamera.ppa_x} onChange={e => setNewCamera({ ...newCamera, ppa_x: parseFloat(e.target.value) })} />
                                            </div>
                                            <div className="space-y-1">
                                                <label className="text-xs font-bold text-slate-500">PPA Y (mm)</label>
                                                <input type="number" step="0.001" className="w-full p-2 border rounded text-sm" value={newCamera.ppa_y} onChange={e => setNewCamera({ ...newCamera, ppa_y: parseFloat(e.target.value) })} />
                                            </div>
                                        </div>
                                        <button onClick={handleAddCamera} className="w-full py-3 bg-blue-600 text-white rounded-lg font-bold text-sm hover:bg-blue-700 shadow-md mt-2">저장 및 선택</button>
                                    </div>
                                ) : (
                                    <div className="space-y-3">
                                        <div className="relative">
                                            <select className="w-full p-4 border border-slate-300 rounded-xl bg-white font-bold text-lg focus:ring-2 focus:ring-blue-500 outline-none appearance-none" value={cameraModel} onChange={(e) => setCameraModel(e.target.value)}>
                                                {Array.isArray(cameraModels) && cameraModels.length > 0 ? (
                                                    cameraModels.map(c => <option key={c.id} value={c.name}>{c.name}</option>)
                                                ) : (
                                                    <option value="" disabled>카메라 모델 로딩 중...</option>
                                                )}
                                            </select>
                                            <div className="absolute right-4 top-1/2 -translate-y-1/2 pointer-events-none text-slate-500">▼</div>
                                        </div>
                                        <button onClick={() => setIsAddingCamera(true)} className="w-full py-3 border-2 border-dashed border-blue-200 text-blue-600 rounded-xl hover:bg-blue-50 font-bold transition-colors flex items-center justify-center gap-2">
                                            <FilePlus size={18} /> 새 카메라 모델 추가
                                        </button>
                                    </div>
                                )}

                                <div className="bg-slate-50 p-5 rounded-xl text-left space-y-2 border border-slate-200">
                                    <div className="flex justify-between text-sm"><span className="text-slate-500">Focal Length</span><span className="font-mono font-bold text-slate-700">{selectedCamera.focal_length} mm</span></div>
                                    <div className="flex justify-between text-sm"><span className="text-slate-500">Sensor Size</span><span className="font-mono font-bold text-slate-700">{selectedCamera.sensor_width} x {selectedCamera.sensor_height} mm</span></div>
                                    <div className="flex justify-between text-sm"><span className="text-slate-500">Pixel Size</span><span className="font-mono font-bold text-slate-700">{selectedCamera.pixel_size} µm</span></div>
                                    {(selectedCamera.sensor_width_px && selectedCamera.sensor_height_px) && (
                                        <div className="flex justify-between text-sm"><span className="text-slate-500">Image Size</span><span className="font-mono font-bold text-slate-700">{selectedCamera.sensor_width_px} x {selectedCamera.sensor_height_px} px</span></div>
                                    )}
                                    {(selectedCamera.ppa_x != null || selectedCamera.ppa_y != null) && (
                                        <div className="flex justify-between text-sm"><span className="text-blue-600">PPA</span><span className="font-mono font-bold text-blue-700">({selectedCamera.ppa_x?.toFixed(3) || '0.000'}, {selectedCamera.ppa_y?.toFixed(3) || '0.000'}) mm</span></div>
                                    )}
                                </div>
                            </div>
                        </div>
                    )}
                    {step === 4 && (
                        <div className="space-y-8 max-w-2xl mx-auto h-full flex flex-col justify-center">
                            <h4 className="text-2xl font-bold text-slate-800 text-center">4. 업로드 결과 요약</h4>
                            <div className="bg-white p-8 rounded-2xl border border-slate-200 shadow-lg space-y-6">
                                <div className="pb-4 border-b border-slate-100">
                                    <label className="text-slate-500 font-medium block mb-2">프로젝트 이름</label>
                                    <input
                                        type="text"
                                        value={projectName}
                                        onChange={(e) => setProjectName(e.target.value)}
                                        placeholder="프로젝트 이름을 입력하세요"
                                        className="w-full p-3 border border-slate-300 rounded-lg text-lg font-bold focus:ring-2 focus:ring-blue-500 focus:border-blue-500 outline-none"
                                    />
                                    <p className="text-xs text-slate-400 mt-1">비워두면 자동으로 생성됩니다</p>
                                </div>
                                <div className="flex justify-between border-b border-slate-100 pb-4 items-center"><span className="text-slate-500 font-medium">입력 이미지</span><div className="text-right"><span className="text-xl font-bold text-slate-800">{imageCount}</span><span className="text-sm text-slate-400 ml-1">장</span></div></div>
                                <div className="flex justify-between border-b border-slate-100 pb-4 items-center"><span className="text-slate-500 font-medium">위치 데이터(EO)</span><div className="text-right"><div className="font-bold text-emerald-600 flex items-center gap-1 justify-end"><CheckCircle2 size={16} /> {eoFileName}</div><div className="text-xs text-slate-400 mt-1">{eoConfig.crs} · {eoLineCount}줄</div></div></div>
                                <div className="flex justify-between border-b border-slate-100 pb-4 items-center"><span className="text-slate-500 font-medium">카메라 모델</span><span className="font-bold text-slate-800">{cameraModel}</span></div>
                                <div className="flex justify-between items-center pt-2"><span className="text-slate-500 font-medium">데이터 상태</span><span className="bg-blue-100 text-blue-700 px-3 py-1 rounded-full text-sm font-bold">준비 완료</span></div>
                            </div>
                            <p className="text-center text-sm text-slate-500"><span className="font-bold text-slate-700">확인</span> 버튼을 누르면 프로젝트 처리 옵션 화면으로 이동합니다.</p>
                        </div>
                    )}
                </div>
                {showMismatchWarning && (
                    <div className="absolute inset-0 z-[1100] flex items-center justify-center bg-black/40 backdrop-blur-sm">
                        <div className="bg-white rounded-xl shadow-2xl p-6 max-w-md animate-in zoom-in-95">
                            <div className="flex items-center gap-3 mb-4">
                                <div className="p-2 bg-amber-100 rounded-full text-amber-600"><AlertTriangle size={24} /></div>
                                <h4 className="font-bold text-slate-800">데이터 불일치</h4>
                            </div>
                            <p className="text-sm text-slate-600 mb-4">
                                이미지 수(<span className="font-bold text-blue-600">{imageCount}장</span>)와
                                EO 데이터 수(<span className="font-bold text-amber-600">{eoLineCount}줄</span>)가 일치하지 않습니다.
                            </p>
                            <p className="text-xs text-slate-500 mb-6">그래도 진행하시겠습니까?</p>
                            <div className="flex gap-3">
                                <button onClick={() => setShowMismatchWarning(false)} className="flex-1 py-2.5 border border-slate-200 text-slate-600 rounded-lg font-medium hover:bg-slate-50">돌아가기</button>
                                <button onClick={handleConfirmMismatch} className="flex-1 py-2.5 bg-amber-500 text-white rounded-lg font-bold hover:bg-amber-600">그래도 진행</button>
                            </div>
                        </div>
                    </div>
                )}
                <div className="h-20 border-t border-slate-200 px-8 flex items-center justify-between bg-slate-50">
                    <button onClick={handleCancelUpload} className="px-4 py-2 text-slate-400 hover:text-slate-600 text-sm">취소</button>
                    <div className="flex items-center gap-3">
                        {step > 1 && <button onClick={() => setStep(s => s - 1)} className="px-5 py-2.5 text-slate-500 font-bold hover:bg-slate-200 rounded-lg transition-colors">이전</button>}
                        {step === 1 && <button onClick={() => setStep(2)} disabled={imageCount === 0} className="px-6 py-2.5 bg-blue-600 text-white rounded-lg font-bold hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors shadow-sm">확인</button>}
                        {step === 2 && <button onClick={() => setStep(3)} disabled={!eoFileName} className="px-6 py-2.5 bg-blue-600 text-white rounded-lg font-bold hover:bg-blue-700 disabled:opacity-50 transition-colors shadow-sm flex items-center gap-2">다음 <ArrowRight size={18} /></button>}
                        {step === 3 && <button onClick={handleProceedToStep4} className="px-6 py-2.5 bg-blue-600 text-white rounded-lg font-bold hover:bg-blue-700 transition-colors shadow-sm flex items-center gap-2">다음 <ArrowRight size={18} /></button>}
                        {step === 4 && <button onClick={handleFinish} className="px-8 py-2.5 bg-emerald-600 text-white rounded-lg font-bold hover:bg-emerald-700 flex items-center gap-2 shadow-md transition-all active:scale-95"><CheckCircle2 size={18} /> 확인 및 설정 이동</button>}
                    </div>
                </div>
            </div>
        </div>
    );
}
