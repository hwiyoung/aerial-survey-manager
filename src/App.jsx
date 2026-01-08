import React, { useState, useEffect, useCallback, useMemo } from 'react';
import {
  Map, Settings, Bell, User, Search,
  Layers, FileImage, AlertTriangle, Loader2, X,
  Download, Box, Maximize2,
  Sparkles, CheckCircle2, MapPin, UploadCloud,
  FolderOpen, FilePlus, FileText, Camera, ArrowRight, Save, Play, Table as TableIcon, RefreshCw, CheckSquare, Square, FileOutput, LogOut, Trash2
} from 'lucide-react';

// API & Auth imports
import { AuthProvider, useAuth } from './contexts/AuthContext';
import { useProjects, useProcessingStatus } from './hooks/useApi';
import LoginPage from './components/LoginPage';
import api from './api/client';
import ResumableUploader from './services/upload';

// Leaflet
import { MapContainer, TileLayer, CircleMarker, Popup, useMap } from 'react-leaflet';
import 'leaflet/dist/leaflet.css';
import L from 'leaflet';
import ResumableDownloader from './services/download';
import DashboardView from './components/Dashboard/DashboardView';

// --- 1. CONSTANTS ---
const REGIONS = ['경기권역', '충청권역', '강원권역', '전라권역', '경상권역'];
const COMPANIES = ['(주)공간정보', '대한측량', '미래매핑', '하늘지리'];

// Status mapping for display
const STATUS_MAP = {
  'pending': '대기',
  'queued': '대기',
  'processing': '진행중',
  'completed': '완료',
  'error': '오류',
  'cancelled': '취소',
};

// Generate placeholder images for visualization
const generatePlaceholderImages = (projectId, count) => {
  return Array.from({ length: count }).map((_, i) => ({
    id: `${projectId}-IMG-${i + 1}`,
    name: `DJI_${20250000 + i}.JPG`,
    x: Math.random() * 80 + 10,
    y: Math.random() * 80 + 10,
    thumbnailColor: `hsl(${Math.random() * 360}, 70%, 80%)`
  }));
};

// --- 2. COMPONENTS ---

class ErrorBoundary extends React.Component {
  constructor(props) { super(props); this.state = { hasError: false, error: null }; }
  static getDerivedStateFromError(error) { return { hasError: true, error }; }
  render() {
    if (this.state.hasError) {
      return (
        <div className="min-h-screen flex items-center justify-center bg-red-50 p-10">
          <div className="bg-white p-8 rounded-xl shadow-lg max-w-2xl w-full">
            <h1 className="text-2xl font-bold text-red-600 mb-4">Application Error</h1>
            <pre className="bg-slate-900 text-slate-100 p-4 rounded overflow-auto text-sm font-mono whitespace-pre-wrap">
              {this.state.error?.toString()}
              {this.state.error?.stack}
            </pre>
            <button onClick={() => window.location.reload()} className="mt-6 px-4 py-2 bg-slate-800 text-white rounded hover:bg-slate-900">Reload Page</button>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}

// [Export Dialog Component]
function ExportDialog({ isOpen, onClose, targetProjectIds, allProjects }) {
  const [format, setFormat] = useState('GeoTiff');
  const [crs, setCrs] = useState('GRS80 (EPSG:5186)');
  const [gsd, setGsd] = useState(5);
  const [filename, setFilename] = useState('');
  const [isExporting, setIsExporting] = useState(false);
  const [progress, setProgress] = useState(0);

  const targets = useMemo(() => {
    return allProjects.filter(p => targetProjectIds.includes(p.id));
  }, [allProjects, targetProjectIds]);

  useEffect(() => {
    if (isOpen) {
      setIsExporting(false);
      setProgress(0);
      if (targets.length === 1) {
        setFilename(`${targets[0].title}_ortho`);
      } else {
        setFilename(`Bulk_Export_${new Date().toISOString().slice(0, 10)}`);
      }
    }
  }, [isOpen, targets]);

  const handleExportStart = () => {
    setIsExporting(true);
    const interval = setInterval(() => {
      setProgress(prev => {
        if (prev >= 100) {
          clearInterval(interval);
          setTimeout(() => {
            alert("내보내기가 완료되었습니다.");
            onClose();
          }, 200);
          return 100;
        }
        return prev + 10;
      });
    }, 200);
  };

  if (!isOpen) return null;

  return (
    <div className="absolute inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm animate-in fade-in duration-200">
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
                <input type="number" className="border p-2 rounded text-sm w-full" value={gsd} onChange={e => setGsd(e.target.value)} />
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

// [Processing Options Sidebar]
function ProcessingSidebar({ width, project, onCancel, onStartProcessing }) {
  return (
    <aside className="bg-white border-r border-slate-200 flex flex-col h-full z-10 shadow-xl shrink-0 transition-all relative animate-in slide-in-from-left duration-300" style={{ width: width }}>
      <div className="p-5 border-b border-slate-200 bg-slate-50">
        <h3 className="font-bold text-lg text-slate-800 flex items-center gap-2"><Settings className="text-blue-600" size={20} />처리 옵션 설정</h3>
        <p className="text-xs text-slate-500 mt-1">프로젝트: {project?.title}</p>
      </div>
      <div className="flex-1 overflow-y-auto custom-scrollbar p-5 space-y-8">
        <div className="space-y-3">
          <h4 className="text-sm font-bold text-slate-700 border-b pb-2">1. 입력 데이터 정보</h4>
          <div className="grid grid-cols-2 gap-4 text-sm"><div><span className="text-slate-500 block text-xs">이미지 수</span><span className="font-mono">{project?.imageCount || 0} 장</span></div><div><span className="text-slate-500 block text-xs">EO 데이터</span><span className="text-emerald-600 font-bold">로드됨</span></div></div>
        </div>
        <div className="space-y-3">
          <h4 className="text-sm font-bold text-slate-700 border-b pb-2">2. 처리 파라미터</h4>
          <div className="space-y-2"><label className="block text-sm text-slate-600">GSD (cm/pixel)</label><input type="number" defaultValue={5} className="border p-2 rounded w-full text-sm" /></div>
          <div className="space-y-2"><label className="block text-sm text-slate-600">좌표계</label><select className="w-full border p-2 rounded text-sm bg-white"><option>GRS80 / TM Middle</option></select></div>
        </div>
        <div className="space-y-3">
          <h4 className="text-sm font-bold text-slate-700 border-b pb-2">3. 출력 형식</h4>
          <div className="flex gap-4"><label className="flex items-center gap-2 text-sm"><input type="checkbox" defaultChecked /> GeoTiff</label><label className="flex items-center gap-2 text-sm"><input type="checkbox" /> JPG</label></div>
        </div>
      </div>
      <div className="p-5 border-t border-slate-200 bg-slate-50 flex gap-3">
        <button onClick={onCancel} className="flex-1 py-3 text-slate-600 font-bold text-sm hover:bg-slate-200 rounded-lg">취소</button>
        <button onClick={onStartProcessing} className="flex-[2] py-3 bg-blue-600 hover:bg-blue-700 text-white font-bold text-sm rounded-lg flex items-center justify-center gap-2 shadow-md"><Play size={16} fill="currentColor" /> 처리 시작</button>
      </div>
    </aside>
  );
}

// [Upload Wizard]
function UploadWizard({ isOpen, onClose, onComplete }) {
  const [step, setStep] = useState(1);
  const [imageCount, setImageCount] = useState(0);
  const [eoFileName, setEoFileName] = useState(null);
  const [cameraModel, setCameraModel] = useState("UltraCam Eagle 4.1");
  const [cameraModels, setCameraModels] = useState([]);
  const [isAddingCamera, setIsAddingCamera] = useState(false);
  const [newCamera, setNewCamera] = useState({ name: '', focal_length: 80, sensor_width: 53.4, sensor_height: 40, pixel_size: 5.2 });

  useEffect(() => {
    if (isOpen) {
      api.getCameraModels().then(setCameraModels).catch(console.error);
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
  const [eoConfig, setEoConfig] = useState({ delimiter: ',', hasHeader: true, crs: 'WGS84 (EPSG:4326)', columns: { image_name: 0, x: 2, y: 1, z: 3, omega: 4, phi: 5, kappa: 6 } });

  const folderInputRef = React.useRef(null);
  const fileInputRef = React.useRef(null);
  const eoInputRef = React.useRef(null);

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
      setEoConfig({ delimiter: ',', hasHeader: true, crs: 'WGS84 (EPSG:4326)', columns: { image_name: 0, x: 2, y: 1, z: 3, omega: 4, phi: 5, kappa: 6 } });
    }
  }, [isOpen]);

  const handleFolderSelect = (e) => {
    const files = Array.from(e.target.files);
    setSelectedFiles(files);
    setImageCount(files.length);
  };
  const handleFileSelect = (e) => {
    const files = Array.from(e.target.files);
    setSelectedFiles(files);
    setImageCount(files.length);
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

  const handleFinish = async () => {
    // Pass raw data to parent for processing
    const projectData = {
      title: `Project_${new Date().toISOString().slice(0, 19).replace(/[-:T]/g, '')}`,
      region: '경기권역',
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
    <div className="absolute inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm animate-in fade-in duration-200">
      <div className="bg-white rounded-xl shadow-2xl w-[900px] flex flex-col max-h-[95vh]">
        <div className="h-16 border-b border-slate-200 flex items-center justify-between px-8 bg-slate-50"><h3 className="font-bold text-slate-800 text-lg flex items-center gap-2"><UploadCloud size={24} className="text-blue-600" />새 프로젝트 데이터 업로드</h3><div className="flex items-center gap-1">{[1, 2, 3, 4].map(s => (<div key={s} className={`w-2 h-2 rounded-full ${step === s ? 'bg-blue-600 scale-125' : step > s ? 'bg-blue-300' : 'bg-slate-200'}`} />))}</div></div>
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
                  type="file"
                  multiple
                  ref={fileInputRef}
                  onChange={handleFileSelect}
                  className="hidden"
                />
                <button
                  onClick={() => folderInputRef.current.click()}
                  className={`p-10 border-2 rounded-xl flex flex-col items-center gap-4 transition-all ${selectedFiles.length > 0 && folderInputRef.current?.files.length > 0 ? 'border-blue-500 bg-blue-50' : 'border-slate-200 hover:border-blue-300'}`}
                >
                  <FolderOpen size={48} className="text-blue-600" />
                  <div>
                    <div className="font-bold text-slate-700 text-lg">폴더 선택</div>
                    <div className="text-sm text-slate-500">폴더 내 전체 로드</div>
                  </div>
                </button>
                <button
                  onClick={() => fileInputRef.current.click()}
                  className={`p-10 border-2 rounded-xl flex flex-col items-center gap-4 transition-all ${selectedFiles.length > 0 && fileInputRef.current?.files.length > 0 ? 'border-blue-500 bg-blue-50' : 'border-slate-200 hover:border-blue-300'}`}
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
              <div className="flex justify-between items-center shrink-0"><h4 className="text-xl font-bold text-slate-800">2. EO (Exterior Orientation) 로드 및 설정</h4><button onClick={() => { setEoConfig({ delimiter: ',', hasHeader: true, crs: 'WGS84 (EPSG:4326)', columns: { id: 0, x: 2, y: 1, z: 3, omega: 4, phi: 5, kappa: 6 } }); setEoFileName(null); }} className="text-xs flex items-center gap-1 text-slate-500 hover:text-blue-600 bg-slate-100 px-2 py-1 rounded"><RefreshCw size={12} /> 설정 초기화</button></div>
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
                    <div className="space-y-1.5"><label className="text-xs font-bold text-slate-500 block">좌표계 (CRS)</label><select className="w-full text-sm border p-2.5 rounded-lg bg-white shadow-sm" value={eoConfig.crs} onChange={(e) => setEoConfig({ ...eoConfig, crs: e.target.value })}><option value="WGS84 (EPSG:4326)">WGS84 (Lat/Lon)</option><option value="GRS80 (EPSG:5186)">GRS80 (TM)</option><option value="UTM52N (EPSG:32652)">UTM Zone 52N</option></select></div>
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
                    <table className="w-full text-sm text-left"><thead className="bg-slate-50 sticky top-0 z-10 text-slate-500 text-xs uppercase"><tr><th className="p-3 border-b font-semibold w-[15%]">Image ID ({eoConfig.columns.image_name})</th><th className="p-3 border-b font-semibold">Lat/X ({eoConfig.columns.x})</th><th className="p-3 border-b font-semibold">Lon/Y ({eoConfig.columns.y})</th><th className="p-3 border-b font-semibold">Alt/Z ({eoConfig.columns.z})</th><th className="p-3 border-b font-semibold">Ω ({eoConfig.columns.omega})</th><th className="p-3 border-b font-semibold">Φ ({eoConfig.columns.phi})</th><th className="p-3 border-b font-semibold">K ({eoConfig.columns.kappa})</th></tr></thead><tbody className="divide-y divide-slate-100">{parsedPreview.map((row) => (<tr key={row.key} className="hover:bg-blue-50 transition-colors group"><td className="p-3 font-mono text-slate-700 font-medium group-hover:text-blue-700">{row.image_name}</td><td className="p-3 font-mono text-slate-500">{row.x}</td><td className="p-3 font-mono text-slate-500">{row.y}</td><td className="p-3 font-mono text-slate-500">{row.z}</td><td className="p-3 font-mono text-slate-400">{row.omega}</td><td className="p-3 font-mono text-slate-400">{row.phi}</td><td className="p-3 font-mono text-slate-400">{row.kappa}</td></tr>))}</tbody></table>
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
                    <button onClick={handleAddCamera} className="w-full py-3 bg-blue-600 text-white rounded-lg font-bold text-sm hover:bg-blue-700 shadow-md mt-2">저장 및 선택</button>
                  </div>
                ) : (
                  <div className="space-y-3">
                    <div className="relative">
                      <select className="w-full p-4 border border-slate-300 rounded-xl bg-white font-bold text-lg focus:ring-2 focus:ring-blue-500 outline-none appearance-none" value={cameraModel} onChange={(e) => setCameraModel(e.target.value)}>
                        {Array.isArray(cameraModels) && cameraModels.map(c => <option key={c.id} value={c.name}>{c.name}</option>)}
                        {!cameraModels?.length && <option value="" disabled>카메라 모델 로딩 중...</option>}
                        <option value="UltraCam Eagle 4.1">UltraCam Eagle 4.1</option>
                        <option value="Leica DMC III">Leica DMC III</option>
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
                </div>
              </div>
            </div>
          )}
          {step === 4 && (
            <div className="space-y-8 max-w-2xl mx-auto h-full flex flex-col justify-center">
              <h4 className="text-2xl font-bold text-slate-800 text-center">4. 업로드 결과 요약</h4>
              <div className="bg-white p-8 rounded-2xl border border-slate-200 shadow-lg space-y-6">
                <div className="flex justify-between border-b border-slate-100 pb-4 items-center"><span className="text-slate-500 font-medium">입력 이미지</span><div className="text-right"><span className="text-xl font-bold text-slate-800">{imageCount}</span><span className="text-sm text-slate-400 ml-1">장</span></div></div>
                <div className="flex justify-between border-b border-slate-100 pb-4 items-center"><span className="text-slate-500 font-medium">위치 데이터(EO)</span><div className="text-right"><div className="font-bold text-emerald-600 flex items-center gap-1 justify-end"><CheckCircle2 size={16} /> {eoFileName}</div><div className="text-xs text-slate-400 mt-1">{eoConfig.crs}</div></div></div>
                <div className="flex justify-between border-b border-slate-100 pb-4 items-center"><span className="text-slate-500 font-medium">카메라 모델</span><span className="font-bold text-slate-800">{cameraModel}</span></div>
                <div className="flex justify-between items-center pt-2"><span className="text-slate-500 font-medium">데이터 상태</span><span className="bg-blue-100 text-blue-700 px-3 py-1 rounded-full text-sm font-bold">준비 완료</span></div>
              </div>
              <p className="text-center text-sm text-slate-500"><span className="font-bold text-slate-700">확인</span> 버튼을 누르면 프로젝트 처리 옵션 화면으로 이동합니다.</p>
            </div>
          )}
        </div>
        <div className="h-20 border-t border-slate-200 px-8 flex items-center justify-end gap-3 bg-slate-50">
          {step > 1 && <button onClick={() => setStep(s => s - 1)} className="px-5 py-2.5 text-slate-500 font-bold hover:bg-slate-200 rounded-lg transition-colors">이전</button>}
          {step === 1 && <button onClick={() => setStep(2)} disabled={imageCount === 0} className="px-6 py-2.5 bg-blue-600 text-white rounded-lg font-bold hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors shadow-sm">확인</button>}
          {step === 2 && <button onClick={() => setStep(3)} disabled={!eoFileName} className="px-6 py-2.5 bg-blue-600 text-white rounded-lg font-bold hover:bg-blue-700 disabled:opacity-50 transition-colors shadow-sm flex items-center gap-2">다음 <ArrowRight size={18} /></button>}
          {step === 3 && <button onClick={() => setStep(4)} className="px-6 py-2.5 bg-blue-600 text-white rounded-lg font-bold hover:bg-blue-700 transition-colors shadow-sm flex items-center gap-2">다음 <ArrowRight size={18} /></button>}
          {step === 4 && <button onClick={handleFinish} className="px-8 py-2.5 bg-emerald-600 text-white rounded-lg font-bold hover:bg-emerald-700 flex items-center gap-2 shadow-md transition-all active:scale-95"><CheckCircle2 size={18} /> 확인 및 설정 이동</button>}
        </div>
      </div>
    </div>
  );
}

// [Header]
function Header() {
  const { user, logout } = useAuth();

  return (
    <header className="h-14 bg-white border-b border-slate-200 flex items-center justify-between px-4 z-20 shadow-sm shrink-0">
      <div
        className="flex items-center gap-2 cursor-pointer hover:opacity-80 transition-opacity"
        onClick={() => {
          // URL 파라미터 초기화하여 깨끗한 상태로 메인 페이지 복귀
          window.history.pushState({}, '', window.location.pathname);
          window.location.reload();
        }}
        title="메인 페이지로 이동"
      >
        <div className="bg-blue-600 p-1.5 rounded text-white"><Map size={20} /></div>
        <h1 className="font-bold text-lg text-slate-800 tracking-tight">InnoPAM <span className="font-normal text-slate-500 text-sm hidden sm:inline">| 실감정사영상 생성 플랫폼</span></h1>
      </div>
      <div className="flex items-center gap-4">
        <button className="p-2 text-slate-500 hover:bg-slate-100 rounded-full relative">
          <Bell size={18} />
        </button>
        <div className="flex items-center gap-2 pl-4 border-l border-slate-200">
          <div className="w-8 h-8 bg-slate-200 rounded-full flex items-center justify-center text-slate-600">
            <User size={16} />
          </div>
          <span className="text-sm font-medium text-slate-700 hidden md:block">
            {user?.name || user?.email || '사용자'}님
          </span>
          <button
            onClick={logout}
            className="p-2 text-slate-400 hover:text-red-500 hover:bg-red-50 rounded-full transition-colors"
            title="로그아웃"
          >
            <LogOut size={16} />
          </button>
        </div>
      </div>
    </header>
  );
}

// [Sidebar]
function Sidebar({ width, projects, selectedProjectId, checkedProjectIds, onSelectProject, onToggleCheck, onOpenUpload, onBulkExport, onSelectMultiple, onDeleteProject, onBulkDelete, onOpenProcessing, onOpenExport }) {
  const [searchTerm, setSearchTerm] = useState('');
  const [regionFilter, setRegionFilter] = useState('ALL');

  // Width-based size mode calculation
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

  const isAllSelected = filteredProjects.length > 0 && filteredProjects.every(p => checkedProjectIds.has(p.id));

  const handleToggleAll = () => {
    const ids = filteredProjects.map(p => p.id);
    onSelectMultiple(ids, !isAllSelected);
  };

  return (
    <aside className="bg-white border-r border-slate-200 flex flex-col h-full z-10 shadow-sm shrink-0 transition-all relative" style={{ width: width }}>
      <div className="p-4 pb-2">
        <button onClick={onOpenUpload} className="w-full bg-blue-600 hover:bg-blue-700 text-white py-3 rounded-lg flex items-center justify-center gap-2 font-bold shadow-md transition-all active:scale-95"><UploadCloud size={20} /><span>새 프로젝트 업로드</span></button>
      </div>
      <div className="p-4 pt-2 border-b border-slate-200 space-y-3">
        <div className="relative"><Search className="absolute left-3 top-2.5 text-slate-400" size={16} /><input type="text" placeholder="검색..." className="w-full pl-9 pr-3 py-2 bg-slate-50 border border-slate-200 rounded-md text-sm" value={searchTerm} onChange={(e) => setSearchTerm(e.target.value)} /></div>
        <select className="w-full p-2 bg-slate-50 border border-slate-200 rounded-md text-sm text-slate-600" value={regionFilter} onChange={(e) => setRegionFilter(e.target.value)}><option value="ALL">전체 권역</option>{REGIONS.map(r => <option key={r} value={r}>{r}</option>)}</select>
      </div>
      <div className="px-4 py-2 border-b border-slate-100 flex items-center gap-2 bg-slate-50 text-xs font-bold text-slate-500">
        <button onClick={handleToggleAll} className="flex items-center gap-2 hover:text-blue-600 transition-colors">
          {isAllSelected ? <CheckSquare size={16} className="text-blue-600" /> : <Square size={16} />}
          <span>전체 선택 ({filteredProjects.length}개)</span>
        </button>
      </div>
      <div className="flex-1 overflow-y-auto custom-scrollbar">
        <div className="p-2 space-y-1">
          {filteredProjects.map(project => (
            <ProjectItem key={project.id} project={project} isSelected={project.id === selectedProjectId} isChecked={checkedProjectIds.has(project.id)} sizeMode={sizeMode} onSelect={() => onSelectProject(project.id)} onToggle={() => onToggleCheck(project.id)} onDelete={() => onDeleteProject(project.id)} onOpenProcessing={() => onOpenProcessing(project.id)} onOpenExport={() => onOpenExport(project.id)} />
          ))}
        </div>
      </div>
      {checkedProjectIds.size > 0 && (
        <div className="p-4 border-t border-slate-200 bg-slate-50 animate-in slide-in-from-bottom duration-200 space-y-2">
          <button onClick={onBulkExport} className="w-full flex items-center justify-center gap-2 bg-slate-800 hover:bg-slate-900 text-white py-2.5 rounded-lg text-sm font-bold shadow-md transition-all">
            <Download size={16} className="text-white" />
            <span>선택한 {checkedProjectIds.size}건 정사영상 내보내기</span>
          </button>
          <button onClick={onBulkDelete} className="w-full flex items-center justify-center gap-2 bg-red-600 hover:bg-red-700 text-white py-2.5 rounded-lg text-sm font-bold shadow-md transition-all">
            <Trash2 size={16} className="text-white" />
            <span>선택한 {checkedProjectIds.size}건 삭제</span>
          </button>
        </div>
      )}
    </aside>
  );
}

function ProjectItem({ project, isSelected, isChecked, sizeMode = 'normal', onSelect, onToggle, onDelete, onOpenProcessing, onOpenExport }) {
  const handleDelete = (e) => {
    e.stopPropagation();
    if (window.confirm(`"${project.title}" 프로젝트를 삭제하시겠습니까?\n\n이 작업은 되돌릴 수 없으며, 모든 이미지 및 관련 데이터가 삭제됩니다.`)) {
      onDelete();
    }
  };

  const handleProcessing = (e) => {
    e.stopPropagation();
    onOpenProcessing();
  };

  const handleExport = (e) => {
    e.stopPropagation();
    onOpenExport();
  };

  // Compact mode: minimal info with hover action icons
  if (sizeMode === 'compact') {
    return (
      <div onClick={onSelect} className={`relative flex items-center gap-2 p-2 rounded-lg cursor-pointer transition-all border group ${isSelected ? "bg-blue-50 border-blue-200 shadow-sm" : "bg-white hover:bg-slate-50 border-transparent"}`}>
        <div onClick={(e) => { e.stopPropagation(); onToggle(); }} className="text-slate-400 hover:text-blue-600 cursor-pointer shrink-0">{isChecked ? <CheckSquare size={16} className="text-blue-600" /> : <Square size={16} />}</div>
        <h4 className="text-sm font-bold text-slate-800 truncate flex-1 min-w-0">{project.title}</h4>
        <span className={`text-[10px] px-1.5 py-0.5 rounded-full font-medium border shrink-0 ${project.status === '완료' ? "bg-emerald-50 text-emerald-600 border-emerald-100" : project.status === '진행중' ? "bg-yellow-50 text-yellow-600 border-yellow-100" : project.status === '오류' ? "bg-red-50 text-red-600 border-red-100" : "bg-blue-50 text-blue-600 border-blue-100"}`}>{project.status}</span>
        {/* Hover action icons */}
        <div className="opacity-0 group-hover:opacity-100 flex items-center gap-1 transition-opacity">
          <button onClick={handleProcessing} className="p-1.5 text-blue-600 hover:bg-blue-100 rounded transition-colors" title="처리 시작"><Play size={14} /></button>
          <button onClick={handleExport} disabled={project.status !== '완료'} className="p-1.5 text-slate-500 hover:bg-slate-100 rounded transition-colors disabled:opacity-30" title="내보내기"><Download size={14} /></button>
        </div>
      </div>
    );
  }

  // Expanded mode: full info with always-visible buttons
  if (sizeMode === 'expanded') {
    return (
      <div onClick={onSelect} className={`relative flex flex-col gap-2 p-3 rounded-lg cursor-pointer transition-all border group ${isSelected ? "bg-blue-50 border-blue-200 shadow-sm z-10" : "bg-white hover:bg-slate-50 border-transparent"}`}>
        <div className="flex items-start gap-3">
          <div onClick={(e) => { e.stopPropagation(); onToggle(); }} className="mt-1 text-slate-400 hover:text-blue-600 cursor-pointer">{isChecked ? <CheckSquare size={18} className="text-blue-600" /> : <Square size={18} />}</div>
          <div className="flex-1 min-w-0">
            <div className="flex justify-between items-start">
              <h4 className="text-sm font-bold text-slate-800 truncate">{project.title}</h4>
              <div className="flex items-center gap-1">
                <span className={`text-[10px] px-1.5 py-0.5 rounded-full font-medium border shrink-0 ${project.status === '완료' ? "bg-emerald-50 text-emerald-600 border-emerald-100" : project.status === '진행중' ? "bg-yellow-50 text-yellow-600 border-yellow-100" : project.status === '오류' ? "bg-red-50 text-red-600 border-red-100" : "bg-blue-50 text-blue-600 border-blue-100"}`}>{project.status}</span>
                <button onClick={handleDelete} className="opacity-0 group-hover:opacity-100 p-1 text-slate-400 hover:text-red-500 hover:bg-red-50 rounded transition-all" title="프로젝트 삭제">
                  <Trash2 size={14} />
                </button>
              </div>
            </div>
            <div className="flex items-center gap-2 text-xs text-slate-500 mt-1"><span className="bg-slate-100 px-1.5 rounded">{project.region}</span><span className="text-slate-300">|</span><span>{project.company}</span></div>
            {/* Extended info for expanded mode */}
            <div className="flex items-center gap-3 text-xs text-slate-400 mt-2">
              <span className="flex items-center gap-1"><FileImage size={12} /> {project.imageCount || 0}장</span>
              {project.startDate && <span className="flex items-center gap-1">📅 {project.startDate}</span>}
            </div>
            {/* Progress bar for processing status */}
            {project.status === '진행중' && (
              <div className="mt-2">
                <div className="h-1.5 bg-slate-200 rounded-full overflow-hidden">
                  <div className="h-full bg-blue-500 rounded-full animate-pulse" style={{ width: '60%' }}></div>
                </div>
              </div>
            )}
          </div>
        </div>
        {/* Always visible action buttons in expanded mode */}
        <div className="flex gap-2 pl-7">
          <button
            onClick={handleProcessing}
            className="flex-1 flex items-center justify-center gap-1 px-2 py-1.5 text-xs font-medium bg-blue-100 hover:bg-blue-200 text-blue-700 rounded transition-colors"
            title="처리 옵션 설정"
          >
            <Play size={12} /> 처리
          </button>
          <button
            onClick={handleExport}
            disabled={project.status !== '완료'}
            className="flex-1 flex items-center justify-center gap-1 px-2 py-1.5 text-xs font-medium bg-slate-100 hover:bg-slate-200 text-slate-700 rounded transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
            title="정사영상 내보내기"
          >
            <Download size={12} /> 내보내기
          </button>
        </div>
      </div>
    );
  }

  // Normal mode (default): current layout
  return (
    <div onClick={onSelect} className={`relative flex flex-col gap-2 p-3 rounded-lg cursor-pointer transition-all border group ${isSelected ? "bg-blue-50 border-blue-200 shadow-sm z-10" : "bg-white hover:bg-slate-50 border-transparent"}`}>
      <div className="flex items-start gap-3">
        <div onClick={(e) => { e.stopPropagation(); onToggle(); }} className="mt-1 text-slate-400 hover:text-blue-600 cursor-pointer">{isChecked ? <CheckSquare size={18} className="text-blue-600" /> : <Square size={18} />}</div>
        <div className="flex-1 min-w-0">
          <div className="flex justify-between items-start">
            <h4 className="text-sm font-bold text-slate-800 truncate">{project.title}</h4>
            <div className="flex items-center gap-1">
              <span className={`text-[10px] px-1.5 py-0.5 rounded-full font-medium border shrink-0 ${project.status === '완료' ? "bg-emerald-50 text-emerald-600 border-emerald-100" : project.status === '진행중' ? "bg-yellow-50 text-yellow-600 border-yellow-100" : project.status === '오류' ? "bg-red-50 text-red-600 border-red-100" : "bg-blue-50 text-blue-600 border-blue-100"}`}>{project.status}</span>
              <button onClick={handleDelete} className="opacity-0 group-hover:opacity-100 p-1 text-slate-400 hover:text-red-500 hover:bg-red-50 rounded transition-all" title="프로젝트 삭제">
                <Trash2 size={14} />
              </button>
            </div>
          </div>
          <div className="flex items-center gap-2 text-xs text-slate-500 mt-1"><span className="bg-slate-100 px-1.5 rounded">{project.region}</span><span className="text-slate-300">|</span><span>{project.company}</span></div>
        </div>
      </div>
      {/* Action buttons - shown on select or hover */}
      <div className={`flex gap-2 pl-7 ${isSelected ? 'opacity-100' : 'opacity-0 group-hover:opacity-100'} transition-opacity`}>
        <button
          onClick={handleProcessing}
          className="flex-1 flex items-center justify-center gap-1 px-2 py-1.5 text-xs font-medium bg-blue-100 hover:bg-blue-200 text-blue-700 rounded transition-colors"
          title="처리 옵션 설정"
        >
          <Play size={12} /> 처리
        </button>
        <button
          onClick={handleExport}
          disabled={project.status !== '완료'}
          className="flex-1 flex items-center justify-center gap-1 px-2 py-1.5 text-xs font-medium bg-slate-100 hover:bg-slate-200 text-slate-700 rounded transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
          title="정사영상 내보내기"
        >
          <Download size={12} /> 내보내기
        </button>
      </div>
    </div>
  );
}

// [Map Component - Real Leaflet]
function FitBounds({ images }) {
  const map = useMap();
  useEffect(() => {
    if (images && images.length > 0) {
      const bounds = L.latLngBounds(images.map(img => [img.wy, img.wx])); // y=lat, x=lon
      if (bounds.isValid()) {
        map.fitBounds(bounds, { padding: [50, 50] });
      }
    }
  }, [images, map]);
  return null;
}

function ProMap({ project, isProcessingMode, selectedImageId, onSelectImage }) {
  const [isLoading, setIsLoading] = useState(false);

  // Images are already normalized/processed in Dashboard, but here we need RAW coords (wx, wy)
  // Dashboard passes 'project.images' which has wx, wy
  const images = useMemo(() => {
    if (!project?.images) return [];
    return project.images.filter(img => img.hasEo);
  }, [project]);

  if (!project) return <div className="w-full h-full flex flex-col items-center justify-center bg-slate-100 map-grid text-slate-400"><div className="bg-white p-6 rounded-xl shadow-sm text-center"><Layers size={48} className="mx-auto mb-4 text-slate-300" /><p className="text-lg font-medium text-slate-600">프로젝트를 선택하세요</p></div></div>;

  return (
    <div className="w-full h-full relative bg-slate-200 z-0">
      <MapContainer
        center={[36.5, 127.5]}
        zoom={7}
        style={{ height: '100%', width: '100%', background: '#f1f5f9' }}
        zoomControl={false}
      >
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        />
        {images.length > 0 && <FitBounds images={images} />}

        {images.map(img => (
          <CircleMarker
            key={img.id}
            center={[img.wy, img.wx]}
            radius={isProcessingMode ? 2 : (img.id === selectedImageId ? 8 : 5)}
            pathOptions={{
              color: img.id === selectedImageId ? '#2563eb' : (isProcessingMode ? '#eab308' : '#ffffff'),
              fillColor: img.id === selectedImageId ? '#3b82f6' : (isProcessingMode ? '#facc15' : '#64748b'),
              fillOpacity: 0.8,
              weight: 2
            }}
            eventHandlers={{
              click: (e) => {
                L.DomEvent.stopPropagation(e);
                onSelectImage(img.id);
              }
            }}
          >
            <Popup>
              <div className="text-xs">
                <strong className="block mb-1 text-slate-700">{img.name}</strong>
                <div className="grid grid-cols-2 gap-x-2 gap-y-1 text-[10px] text-slate-500">
                  <span>Lat: {img.wy.toFixed(6)}</span>
                  <span>Lon: {img.wx.toFixed(6)}</span>
                  <span>Alt: {img.z || '-'}</span>
                  <span>Omega: {img.omega || '0'}</span>
                  <span>Phi: {img.phi || '0'}</span>
                  <span>Kappa: {img.kappa || '0'}</span>
                </div>
              </div>
            </Popup>
          </CircleMarker>
        ))}
      </MapContainer>

      {/* Overlay for non-EO projects */}
      {images.length === 0 && project.images?.length > 0 && (
        <div className="absolute inset-0 flex items-center justify-center bg-black/50 z-[1000] pointer-events-none">
          <div className="bg-white p-4 rounded shadow text-slate-700 font-bold">
            EO 데이터가 없어 지도에 표시할 수 없습니다.
          </div>
        </div>
      )}
    </div>
  );
}
// Renaming for compatibility with existing usage
const MapPlaceholder = ProMap;

// [Inspector Panel]
function InspectorPanel({ project, image, qcData, onQcUpdate, onCloseImage, onExport }) {
  const [isImageLoaded, setIsImageLoaded] = useState(false);
  useEffect(() => { setIsImageLoaded(false); if (image) { const t = setTimeout(() => setIsImageLoaded(true), 600); return () => clearTimeout(t); } }, [image]);

  if (!project) return <div className="flex h-full items-center justify-center bg-slate-50 text-slate-400">프로젝트를 선택하세요</div>;

  if (!image) {
    return (
      <div className="flex h-full w-full bg-white text-slate-800">
        <div className="w-1/3 min-w-[300px] border-r border-slate-200 p-6 overflow-y-auto">
          <div className="flex items-center gap-2 mb-2"><span className="px-2 py-0.5 rounded text-[10px] font-bold bg-slate-100 text-slate-600 border border-slate-200">BLOCK</span><span className="text-xs text-slate-400 font-mono">{project.id}</span></div>
          <h2 className="text-2xl font-bold leading-tight mb-6">{project.title}</h2>
          <div className="space-y-4 text-sm">
            <div className="flex justify-between border-b pb-2"><span className="text-slate-500">권역/업체</span><span className="font-medium">{project.region}/{project.company}</span></div>
            <div className="flex justify-between border-b pb-2"><span className="text-slate-500">상태</span><span className={`font-bold ${project.status === '완료' ? 'text-emerald-600' : project.status === '오류' ? 'text-red-600' : 'text-blue-600'}`}>{project.status}</span></div>
            <div className="flex justify-between border-b pb-2"><span className="text-slate-500">원본사진</span><span className="font-medium">{project.imageCount || 0}장</span></div>
            {project.startDate && <div className="flex justify-between border-b pb-2"><span className="text-slate-500">촬영일</span><span className="font-medium">{project.startDate}</span></div>}
            {project.dataSize && <div className="flex justify-between border-b pb-2"><span className="text-slate-500">데이터용량</span><span className="font-medium">{project.dataSize}</span></div>}
          </div>
        </div>
        <div className="flex-1 p-6 bg-slate-50 overflow-y-auto">
          {project.orthoResult ? (<div className="bg-white border border-slate-200 rounded-xl p-5 shadow-sm flex items-center justify-between"><div className="flex items-center gap-4"><FileImage size={24} className="text-slate-400" /><div><div className="font-bold">Result_Ortho.tif</div><div className="text-xs text-slate-500">{project.orthoResult.fileSize}</div></div></div><button onClick={onExport} disabled={project.status !== '완료'} className="bg-slate-800 hover:bg-slate-900 disabled:bg-slate-300 text-white px-4 py-2 rounded text-sm flex gap-2 transition-colors font-bold shadow-sm"><Download size={16} />정사영상 내보내기</button></div>) : (<div className="flex flex-col items-center justify-center h-32 border-2 border-dashed border-slate-300 rounded-xl text-slate-400 gap-2"><Loader2 size={24} className={project.status === '진행중' ? "animate-spin" : ""} /><span className="text-sm font-medium">{project.status === '진행중' ? '정사영상 생성 처리 중...' : '결과물이 없습니다.'}</span></div>)}
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-full w-full bg-white relative">
      <button onClick={onCloseImage} className="absolute top-4 right-4 z-10 p-2 hover:bg-slate-100 rounded-full"><X size={20} /></button>
      <div className="w-1/3 min-w-[320px] bg-slate-900 p-4 flex flex-col justify-center relative">
        <div className="flex-1 bg-black/40 rounded-lg overflow-hidden relative border border-white/10">
          {isImageLoaded ? <div className="w-full h-full relative"><div className="w-full h-full opacity-80" style={{ backgroundColor: image.thumbnailColor }}></div><div className="absolute inset-0 flex items-center justify-center text-white/30 text-4xl font-black rotate-12">PREVIEW</div></div> : <div className="flex h-full items-center justify-center text-slate-500"><Loader2 className="animate-spin" /></div>}
        </div>
      </div>
      <div className="flex-1 p-6 overflow-y-auto bg-slate-50">
        <h4 className="font-bold mb-4">품질 점검</h4>
        <div className="space-y-2 mb-4"><label className="flex items-center gap-3 p-3 bg-white border rounded cursor-pointer"><input type="checkbox" checked={qcData.issues?.includes('blur') || false} onChange={() => onQcUpdate(image.id, { ...qcData, issues: [...(qcData.issues || []), 'blur'], status: 'Fail' })} /><span className="text-sm">블러 (Blur)</span></label></div>
        <textarea className="w-full p-3 border rounded text-sm bg-white" placeholder="코멘트 입력..." value={qcData.comment || ''} onChange={e => onQcUpdate(image.id, { ...qcData, comment: e.target.value })}></textarea>
      </div>
    </div>
  );
}

// --- 3. MAIN DASHBOARD ---
function Dashboard() {
  // Use API hook for projects
  const { projects: apiProjects, loading: projectsLoading, error: projectsError, refresh: refreshProjects, createProject, deleteProject } = useProjects();

  // Transform API projects to match UI expectations
  const projects = useMemo(() => {
    return apiProjects.map(p => ({
      ...p,
      status: STATUS_MAP[p.status] || p.status,
      imageCount: p.image_count || 0,
      startDate: p.created_at?.slice(0, 10) || '',
      bounds: { x: 15 + Math.random() * 60, y: 15 + Math.random() * 60, w: 30, h: 30 },
      orthoResult: p.status === 'completed' ? { resolution: '5cm GSD', fileSize: '4.2GB', generatedAt: p.updated_at?.slice(0, 10) } : null,
    }));
  }, [apiProjects]);

  // Read project ID from URL query parameter on initial load
  const initialProjectId = useMemo(() => {
    const params = new URLSearchParams(window.location.search);
    return params.get('projectId');
  }, []);

  // Read viewMode from URL query parameter
  const initialViewMode = useMemo(() => {
    const params = new URLSearchParams(window.location.search);
    return params.get('viewMode') || 'dashboard';
  }, []);

  const [selectedProjectId, setSelectedProjectId] = useState(initialProjectId);
  const [projectImages, setProjectImages] = useState([]); // Store fetched images
  const [loadingImages, setLoadingImages] = useState(false);
  const [imageRefreshKey, setImageRefreshKey] = useState(0); // Trigger to force image reload

  // Fetch images when project is selected
  useEffect(() => {
    if (!selectedProjectId) {
      setProjectImages([]);
      return;
    }

    setLoadingImages(true);
    api.getProjectImages(selectedProjectId)
      .then(images => {
        // Normalize logic
        if (images.length === 0) {
          setProjectImages([]);
          return;
        }

        // Extract coordinates from EO data if available
        // Backend returns exterior_orientation object
        const points = images.map(img => {
          const eo = img.exterior_orientation;
          return {
            id: img.id,
            name: img.filename,
            // If EO exists, use it. Otherwise random fallback or 0
            wx: eo ? eo.x : 0,
            wy: eo ? eo.y : 0,
            hasEo: !!eo,
            thumbnailColor: `hsl(${Math.random() * 360}, 70%, 80%)` // Still random color for now
          };
        });

        const validPoints = points.filter(p => p.hasEo);

        if (validPoints.length > 0) {
          // Calculate bounds
          const xs = validPoints.map(p => p.wx);
          const ys = validPoints.map(p => p.wy);
          const minX = Math.min(...xs);
          const maxX = Math.max(...xs);
          const minY = Math.min(...ys);
          const maxY = Math.max(...ys);

          const rangeX = maxX - minX || 1;
          const rangeY = maxY - minY || 1;

          // Normalize to 0-100%
          const normalized = points.map(p => {
            if (!p.hasEo) return { ...p, x: 50, y: 50 }; // Center if no EO
            return {
              ...p,
              // Map world coords to 5-95% of container
              x: 5 + ((p.wx - minX) / rangeX) * 90,
              y: 95 - ((p.wy - minY) / rangeY) * 90 // Invert Y for screen coords
            };
          });
          setProjectImages(normalized);
        } else {
          // Fallback to placeholder if no EO data at all
          setProjectImages(generatePlaceholderImages(selectedProjectId, images.length));
        }
      })
      .catch(err => {
        console.error("Failed to fetch images:", err);
        setProjectImages([]);
      })
      .finally(() => setLoadingImages(false));
  }, [selectedProjectId, imageRefreshKey]); // Add imageRefreshKey to force refresh
  const [checkedProjectIds, setCheckedProjectIds] = useState(new Set());
  const [selectedImageId, setSelectedImageId] = useState(null);
  const [sidebarWidth, setSidebarWidth] = useState(320);
  const [isResizing, setIsResizing] = useState(false);
  const [isUploadOpen, setIsUploadOpen] = useState(false);

  const [viewMode, setViewMode] = useState(initialViewMode);
  const [processingProject, setProcessingProject] = useState(null);

  // Set processingProject when viewMode is processing and project is loaded
  useEffect(() => {
    if (initialViewMode === 'processing' && initialProjectId && projects.length > 0) {
      const proj = projects.find(p => p.id === initialProjectId);
      if (proj && !processingProject) {
        setProcessingProject({
          ...proj,
          images: projectImages
        });
      }
    }
  }, [initialViewMode, initialProjectId, projects, projectImages, processingProject]);

  // Export Modal State
  const [exportModalState, setExportModalState] = useState({ isOpen: false, projectIds: [] });

  // Highlight state for post-processing animation
  const [highlightProjectId, setHighlightProjectId] = useState(null);

  const selectedProject = useMemo(() => {
    if (viewMode === 'processing') return processingProject;
    const proj = projects.find(p => p.id === selectedProjectId);
    if (!proj) return null;

    // Merge fetched images
    return {
      ...proj,
      images: projectImages
    };
  }, [viewMode, processingProject, projects, selectedProjectId, projectImages]);

  const selectedImage = selectedProject?.images?.find(img => img.id === selectedImageId) || null;
  const [qcData, setQcData] = useState(() => JSON.parse(localStorage.getItem('innopam_qc_data') || '{}'));

  const startResizing = useCallback(() => setIsResizing(true), []);
  useEffect(() => {
    const handleMove = (e) => isResizing && setSidebarWidth(Math.max(240, Math.min(800, e.clientX)));
    const handleUp = () => setIsResizing(false);
    if (isResizing) { window.addEventListener('mousemove', handleMove); window.addEventListener('mouseup', handleUp); }
    return () => { window.removeEventListener('mousemove', handleMove); window.removeEventListener('mouseup', handleUp); };
  }, [isResizing]);

  const handleUploadComplete = async ({ projectData, files, eoFile, eoConfig, cameraModel }) => {
    try {
      // 1. Create Project via API
      console.log('Creating project:', projectData);
      const created = await createProject({
        title: projectData.title,
        region: projectData.region,
        company: projectData.company,
      });
      console.log('Project created:', created);

      // 2. Initialize Images (Create records in DB)
      if (files && files.length > 0) {
        console.log('Initializing image records...');
        try {
          await Promise.all(files.map(file => api.initImageUpload(created.id, file.name, file.size)));
        } catch (err) {
          console.error('Failed to initialize images:', err);
          alert('이미지 초기화 실패: ' + err.message);
          return;
        }
      }

      // 3. Upload EO Data if exists (Now that images exist)
      if (eoFile) {
        console.log('Uploading EO data...');
        try {
          await api.uploadEoData(created.id, eoFile, eoConfig);
          alert("EO data uploaded successfully.");
        } catch (e) {
          console.error(e);
          alert("Failed to upload EO data: " + e.message);
        }
      }

      // 4. Initiate TUS Image Uploads
      if (files && files.length > 0) {
        console.log(`Starting upload for ${files.length} images...`);
        alert(`${files.length}개의 이미지 업로드를 시작합니다.\n(백그라운드에서 진행됩니다)`);

        const uploader = new ResumableUploader(api.token);
        uploader.uploadFiles(files, created.id, {
          onFileComplete: (idx, name) => console.log(`Uploaded ${name}`),
          onAllComplete: async () => {
            console.log('All uploads finished');
            alert("모든 이미지 업로드가 완료되었습니다. 처리 화면으로 이동합니다.");
            // Reload the page with project ID and viewMode in URL to maintain context
            window.location.href = `${window.location.origin}${window.location.pathname}?projectId=${created.id}&viewMode=processing`;
          },
          onError: (idx, name, err) => console.error(`Failed ${name}`, err)
        });
      }

      // 4. Update UI State (Switch to Processing View immediately or show new project)
      // Transform for processing view
      const projectForProcessing = {
        ...created,
        status: '대기', // Initial status
        imageCount: files?.length || 0,
        images: generatePlaceholderImages(created.id, files?.length || 0), // Placeholders until real images load
        bounds: { x: 30, y: 30, w: 40, h: 40 },
        cameraModel: cameraModel
      };

      setProcessingProject(projectForProcessing);
      setViewMode('processing');
      refreshProjects();

    } catch (err) {
      console.error('Failed to create project:', err);
      alert('프로젝트 생성 실패: ' + err.message);
    }
  };

  const handleStartProcessing = async () => {
    if (!processingProject) return;

    const projectId = processingProject.id;

    try {
      // Start processing via API
      await api.startProcessing(projectId, {
        engine: 'odm',
        gsd: 5.0,
        output_crs: 'EPSG:5186',
        output_format: 'GeoTiff',
      });
    } catch (err) {
      console.error('Failed to start processing:', err);
    }

    // Go to dashboard with highlight (not select the project directly)
    setSelectedProjectId(null);
    setViewMode('dashboard');
    setProcessingProject(null);
    setHighlightProjectId(projectId); // Highlight the project on map for 3.5 seconds
    refreshProjects();
  };

  const handleToggleCheck = (id) => {
    const newChecked = new Set(checkedProjectIds);
    if (newChecked.has(id)) newChecked.delete(id); else newChecked.add(id);
    setCheckedProjectIds(newChecked);
  };

  const handleSelectMultiple = (ids, shouldSelect) => {
    const newChecked = new Set(checkedProjectIds);
    ids.forEach(id => {
      if (shouldSelect) newChecked.add(id);
      else newChecked.delete(id);
    });
    setCheckedProjectIds(newChecked);
  };

  const openExportDialog = (projectIds) => {
    setExportModalState({ isOpen: true, projectIds: projectIds });
  };

  return (
    <div className="flex flex-col h-screen w-full bg-slate-100 overflow-hidden font-sans">
      <style>{`.custom-scrollbar::-webkit-scrollbar{width:6px}.custom-scrollbar::-webkit-scrollbar-thumb{background:#cbd5e1;border-radius:3px}.map-grid{background-image:linear-gradient(to right,rgba(0,0,0,0.05) 1px,transparent 1px),linear-gradient(to bottom,rgba(0,0,0,0.05) 1px,transparent 1px);background-size:40px 40px}`}</style>
      <Header />
      <div className="flex flex-1 overflow-hidden relative">
        {viewMode === 'processing' ? (
          <ProcessingSidebar width={sidebarWidth} project={processingProject} onCancel={() => { setViewMode('dashboard'); setProcessingProject(null); }} onStartProcessing={handleStartProcessing} />
        ) : (
          <Sidebar
            width={sidebarWidth}
            projects={projects}
            selectedProjectId={selectedProjectId}
            checkedProjectIds={checkedProjectIds}
            onSelectProject={(id) => { setSelectedProjectId(id); setSelectedImageId(null); }}
            onToggleCheck={handleToggleCheck}
            onSelectMultiple={handleSelectMultiple}
            onOpenUpload={() => setIsUploadOpen(true)}
            onBulkExport={() => openExportDialog(Array.from(checkedProjectIds))}
            onDeleteProject={async (id) => {
              try {
                await deleteProject(id);
                if (selectedProjectId === id) setSelectedProjectId(null);
                alert('프로젝트가 삭제되었습니다.');
              } catch (err) {
                alert('삭제 실패: ' + err.message);
              }
            }}
            onBulkDelete={async () => {
              const count = checkedProjectIds.size;
              if (!window.confirm(`선택한 ${count}개의 프로젝트를 삭제하시겠습니까?\n\n이 작업은 되돌릴 수 없으며, 모든 이미지 및 관련 데이터가 삭제됩니다.`)) return;

              let successCount = 0;
              let failCount = 0;
              for (const id of checkedProjectIds) {
                try {
                  await deleteProject(id);
                  successCount++;
                  if (selectedProjectId === id) setSelectedProjectId(null);
                } catch (err) {
                  failCount++;
                  console.error(`Failed to delete ${id}:`, err);
                }
              }
              setCheckedProjectIds(new Set());
              alert(`${successCount}개 삭제 완료${failCount > 0 ? `, ${failCount}개 실패` : ''}`);
            }}
            onOpenProcessing={(projectId) => {
              const proj = projects.find(p => p.id === projectId);
              if (proj) {
                setProcessingProject({
                  ...proj,
                  images: projectImages
                });
                setSelectedProjectId(projectId);
                setViewMode('processing');
              }
            }}
            onOpenExport={(projectId) => {
              openExportDialog([projectId]);
            }}
          />
        )}
        <div className="w-1.5 bg-slate-200 hover:bg-blue-400 cursor-col-resize z-20 flex items-center justify-center group" onMouseDown={startResizing}><div className="h-8 w-1 bg-slate-300 rounded-full group-hover:bg-white/50" /></div>
        <div className="flex flex-col flex-1 min-w-0 bg-slate-50">
          {/* Show DashboardView when no project selected in dashboard mode */}
          {viewMode === 'dashboard' && !selectedProjectId ? (
            <DashboardView
              projects={projects}
              sidebarWidth={sidebarWidth}
              onProjectClick={(project) => {
                setSelectedProjectId(project.id);
              }}
              highlightProjectId={highlightProjectId}
              onHighlightEnd={() => setHighlightProjectId(null)}
            />
          ) : (
            <>
              <main className="flex-1 relative overflow-hidden">
                <MapPlaceholder project={selectedProject} isProcessingMode={viewMode === 'processing'} selectedImageId={selectedImageId} onSelectImage={(id) => setSelectedImageId(id)} />
              </main>
              {viewMode === 'dashboard' && selectedProjectId && (
                <div className="h-[350px] border-t border-slate-300 bg-white shadow-sm z-20 relative flex items-center justify-center text-slate-400">
                  <InspectorPanel
                    project={selectedProject}
                    image={selectedImage}
                    qcData={qcData[selectedImageId] || {}}
                    onQcUpdate={(id, d) => { const n = { ...qcData, [id]: d }; setQcData(n); localStorage.setItem('innopam_qc_data', JSON.stringify(n)); }}
                    onCloseImage={() => setSelectedImageId(null)}
                    onExport={() => openExportDialog([selectedProject.id])}
                  />
                </div>
              )}
            </>
          )}
        </div>
      </div>

      {/* Modals */}
      <UploadWizard isOpen={isUploadOpen} onClose={() => setIsUploadOpen(false)} onComplete={handleUploadComplete} />

      <ExportDialog
        isOpen={exportModalState.isOpen}
        onClose={() => setExportModalState({ ...exportModalState, isOpen: false })}
        targetProjectIds={exportModalState.projectIds}
        allProjects={projects}
      />
    </div>
  );
}

// --- 4. MAIN APP WITH AUTH ---
export default function App() {
  const { isAuthenticated, loading } = useAuth();

  if (loading) {
    return (
      <div className="min-h-screen bg-slate-100 flex items-center justify-center">
        <div className="text-center">
          <Loader2 className="w-12 h-12 text-blue-600 animate-spin mx-auto mb-4" />
          <p className="text-slate-600">로딩 중...</p>
        </div>
      </div>
    );
  }

  return isAuthenticated ? <ErrorBoundary><Dashboard /></ErrorBoundary> : <LoginPage />;
}

// --- 5. APP WITH PROVIDER ---
export function AppWithProvider() {
  return (
    <AuthProvider>
      <App />
    </AuthProvider>
  );
}