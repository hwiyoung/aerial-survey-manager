import React, { useState, useEffect, useCallback, useMemo } from 'react';
import { 
  Map, Settings, Bell, User, Search,
  Layers, FileImage, AlertTriangle, Loader2, X, 
  Download, Box, Maximize2,
  Sparkles, CheckCircle2, MapPin, UploadCloud, 
  FolderOpen, FilePlus, FileText, Camera, ArrowRight, Save, Play, Table as TableIcon, RefreshCw, CheckSquare, Square, FileOutput
} from 'lucide-react';

// --- 0. CONFIGURATION & UTILS ---
const apiKey = ""; 

// --- 1. MOCK DATA GENERATOR ---
const REGIONS = ['경기권역', '충청권역', '강원권역', '전라권역', '경상권역'];
const COMPANIES = ['(주)공간정보', '대한측량', '미래매핑', '하늘지리'];

const generateImages = (projectId, count) => {
  return Array.from({ length: count }).map((_, i) => ({
    id: `${projectId}-IMG-${i + 1}`,
    name: `DJI_${20250000 + i}.JPG`,
    capturedAt: '2025-03-15 14:30:00',
    resolution: '4000x3000',
    size: '5.4MB',
    hasError: Math.random() < 0.1,
    x: Math.random() * 80 + 10,
    y: Math.random() * 80 + 10,
    thumbnailColor: `hsl(${Math.random() * 360}, 70%, 80%)`
  }));
};

const mockProjects = Array.from({ length: 12 }).map((_, i) => {
  const region = REGIONS[i % REGIONS.length];
  const blockNum = ((i * 7) % 20) + 1; 
  const subBlock = Math.floor(Math.random() * 5) + 1;
  const projectId = `${blockNum}BL-${subBlock}-202503`;
  
  return {
    id: projectId,
    title: projectId,
    region: region,
    company: COMPANIES[i % COMPANIES.length],
    startDate: '2025-03-01',
    imageCount: 50 + Math.floor(Math.random() * 200),
    progress: 100,
    status: '완료',
    images: generateImages(projectId, 15),
    bounds: { x: 15 + (i * 13) % 60, y: 15 + (i * 7) % 60, w: 30, h: 30 },
    orthoResult: { resolution: '5cm GSD', fileSize: '4.2GB', generatedAt: '2025-03-16' }
  };
});

// --- 2. COMPONENTS ---

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
        setFilename(`Bulk_Export_${new Date().toISOString().slice(0,10)}`);
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
            <Download size={20} className="text-blue-600"/>
            정사영상 내보내기 설정
          </h3>
          {!isExporting && <button onClick={onClose}><X size={20} className="text-slate-400 hover:text-slate-600"/></button>}
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
                <select className="w-full border p-2 rounded text-sm bg-white" value={format} onChange={e=>setFormat(e.target.value)}>
                  <option value="GeoTiff">GeoTiff (*.tif)</option>
                  <option value="JPG">JPG (*.jpg)</option>
                  <option value="PNG">PNG (*.png)</option>
                  <option value="ECW">ECW (*.ecw)</option>
                </select>
              </div>
              <div className="space-y-1">
                <label className="text-xs font-bold text-slate-500">좌표계 (CRS)</label>
                <select className="w-full border p-2 rounded text-sm bg-white" value={crs} onChange={e=>setCrs(e.target.value)}>
                  <option>GRS80 (EPSG:5186)</option>
                  <option>WGS84 (EPSG:4326)</option>
                  <option>UTM52N (EPSG:32652)</option>
                </select>
              </div>
            </div>
            <div className="space-y-1">
              <label className="text-xs font-bold text-slate-500">해상도 (GSD)</label>
              <div className="flex gap-2">
                <input type="number" className="border p-2 rounded text-sm w-full" value={gsd} onChange={e=>setGsd(e.target.value)} />
                <span className="text-sm text-slate-500 self-center whitespace-nowrap">cm/pixel</span>
              </div>
            </div>
            <div className="space-y-1">
              <label className="text-xs font-bold text-slate-500">파일 이름</label>
              <div className="flex gap-2 items-center">
                <input type="text" className="border p-2 rounded text-sm w-full" value={filename} onChange={e=>setFilename(e.target.value)} />
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
                <FileOutput size={16}/> 내보내기
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
        <h3 className="font-bold text-lg text-slate-800 flex items-center gap-2"><Settings className="text-blue-600" size={20}/>처리 옵션 설정</h3>
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
  const [eoConfig, setEoConfig] = useState({
    delimiter: ',',
    hasHeader: true,
    crs: 'WGS84 (EPSG:4326)',
    columns: { id: 0, x: 2, y: 1, z: 3, omega: 4, phi: 5, kappa: 6 } 
  });

  const rawEoData = `ImageID,Lat,Lon,Alt,Omega,Phi,Kappa
IMG_001,37.1234,127.5543,150.2,0.1,-0.2,1.5
IMG_002,37.1235,127.5544,150.3,0.1,-0.2,1.5
IMG_003,37.1236,127.5545,150.2,0.0,-0.2,1.4
IMG_004,37.1237,127.5546,150.1,0.2,-0.1,1.3`;

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
        id: getVal(eoConfig.columns.id),
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
      setEoConfig({ delimiter: ',', hasHeader: true, crs: 'WGS84 (EPSG:4326)', columns: { id: 0, x: 2, y: 1, z: 3, omega: 4, phi: 5, kappa: 6 } });
    }
  }, [isOpen]);

  const handleFolderSelect = () => setImageCount(142); 
  const handleFileSelect = () => setImageCount(12);   

  const handleFinish = () => {
    const newProject = {
      id: `NEW-BL-${Math.floor(Math.random() * 100)}`,
      title: `NEW-BLOCK-WORK`,
      region: '경기권역',
      company: '신규 업로드',
      status: '대기',
      progress: 0,
      imageCount: imageCount || 100,
      images: generateImages('NEW', 20),
      bounds: { x: 30, y: 30, w: 40, h: 40 },
      orthoResult: null
    };
    onComplete(newProject);
    onClose();
  };

  if (!isOpen) return null;

  return (
    <div className="absolute inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm animate-in fade-in duration-200">
      <div className="bg-white rounded-xl shadow-2xl w-[900px] flex flex-col max-h-[95vh]">
        <div className="h-16 border-b border-slate-200 flex items-center justify-between px-8 bg-slate-50"><h3 className="font-bold text-slate-800 text-lg flex items-center gap-2"><UploadCloud size={24} className="text-blue-600"/>새 프로젝트 데이터 업로드</h3><div className="flex items-center gap-1">{[1, 2, 3, 4].map(s => (<div key={s} className={`w-2 h-2 rounded-full ${step === s ? 'bg-blue-600 scale-125' : step > s ? 'bg-blue-300' : 'bg-slate-200'}`} />))}</div></div>
        <div className="p-8 flex-1 overflow-y-auto min-h-[500px]">
          {step === 1 && (
            <div className="space-y-6 max-w-2xl mx-auto h-full flex flex-col justify-center">
              <h4 className="text-xl font-bold text-slate-800 text-center mb-6">1. 원본 이미지 선택</h4>
              <div className="grid grid-cols-2 gap-4">
                <button onClick={handleFolderSelect} className={`p-10 border-2 rounded-xl flex flex-col items-center gap-4 transition-all ${imageCount === 142 ? 'border-blue-500 bg-blue-50' : 'border-slate-200 hover:border-blue-300'}`}><FolderOpen size={48} className="text-blue-600" /><div><div className="font-bold text-slate-700 text-lg">폴더 선택</div><div className="text-sm text-slate-500">폴더 내 전체 로드</div></div></button>
                <button onClick={handleFileSelect} className={`p-10 border-2 rounded-xl flex flex-col items-center gap-4 transition-all ${imageCount === 12 ? 'border-blue-500 bg-blue-50' : 'border-slate-200 hover:border-blue-300'}`}><FilePlus size={48} className="text-emerald-600" /><div><div className="font-bold text-slate-700 text-lg">이미지 선택</div><div className="text-sm text-slate-500">개별 파일 선택</div></div></button>
              </div>
              {imageCount > 0 && <div className="text-center p-4 bg-slate-100 rounded-lg text-slate-700 animate-in fade-in flex items-center justify-center gap-2"><CheckCircle2 size={20} className="text-blue-600"/>총 <span className="font-bold text-blue-600">{imageCount}</span>장의 이미지가 확인되었습니다.</div>}
            </div>
          )}
          {step === 2 && (
            <div className="flex flex-col h-full gap-6">
              <div className="flex justify-between items-center shrink-0"><h4 className="text-xl font-bold text-slate-800">2. EO (Exterior Orientation) 로드 및 설정</h4><button onClick={() => { setEoConfig({ delimiter: ',', hasHeader: true, crs: 'WGS84 (EPSG:4326)', columns: { id: 0, x: 2, y: 1, z: 3, omega: 4, phi: 5, kappa: 6 } }); setEoFileName(null); }} className="text-xs flex items-center gap-1 text-slate-500 hover:text-blue-600 bg-slate-100 px-2 py-1 rounded"><RefreshCw size={12}/> 설정 초기화</button></div>
              <div className="flex gap-6 shrink-0 h-[220px]">
                <div className={`w-1/4 border-2 border-dashed rounded-xl flex flex-col items-center justify-center gap-3 cursor-pointer transition-colors ${eoFileName ? 'border-emerald-500 bg-emerald-50' : 'border-slate-300 hover:bg-slate-50'}`} onClick={() => setEoFileName("2025_Block7_EO.txt")}>
                    {eoFileName ? (<><div className="p-3 bg-emerald-100 rounded-full text-emerald-600"><FileText size={32} /></div><div className="text-center px-4"><div className="text-sm font-bold text-slate-800 truncate max-w-[150px]">{eoFileName}</div><div className="text-[10px] text-emerald-600 font-bold mt-1">로드 성공</div></div></>) : (<><div className="p-3 bg-slate-100 rounded-full text-slate-400"><UploadCloud size={32} /></div><div className="text-center"><div className="text-sm font-bold text-slate-600">EO 파일 선택</div><div className="text-xs text-slate-400 mt-1">.txt, .csv, .json</div></div></>)}
                 </div>
                 <div className="flex-1 bg-slate-50 p-5 rounded-xl border border-slate-200 flex flex-col justify-between">
                    <div className="grid grid-cols-3 gap-6">
                      <div className="space-y-1.5"><label className="text-xs font-bold text-slate-500 block">좌표계 (CRS)</label><select className="w-full text-sm border p-2.5 rounded-lg bg-white shadow-sm" value={eoConfig.crs} onChange={(e) => setEoConfig({...eoConfig, crs: e.target.value})}><option value="WGS84 (EPSG:4326)">WGS84 (Lat/Lon)</option><option value="GRS80 (EPSG:5186)">GRS80 (TM)</option><option value="UTM52N (EPSG:32652)">UTM Zone 52N</option></select></div>
                      <div className="space-y-1.5"><label className="text-xs font-bold text-slate-500 block">구분자</label><select className="w-full text-sm border p-2.5 rounded-lg bg-white shadow-sm" value={eoConfig.delimiter} onChange={(e) => setEoConfig({...eoConfig, delimiter: e.target.value})}><option value=",">콤마 (,)</option><option value="tab">탭 (Tab)</option><option value="space">공백 (Space)</option></select></div>
                      <div className="space-y-1.5"><label className="text-xs font-bold text-slate-500 block">헤더 행</label><select className="w-full text-sm border p-2.5 rounded-lg bg-white shadow-sm" value={eoConfig.hasHeader} onChange={(e) => setEoConfig({...eoConfig, hasHeader: e.target.value === 'true'})}><option value="true">첫 줄 제외 (Skip)</option><option value="false">포함 (Include)</option></select></div>
                    </div>
                    <div className="pt-4 border-t border-slate-200">
                      <label className="text-xs font-bold text-slate-500 mb-2 block">열 번호 매핑 (Column Index)</label>
                      <div className="flex gap-3">{Object.entries(eoConfig.columns).map(([key, val]) => (<div key={key} className="flex-1 bg-white p-1.5 rounded border border-slate-200 flex flex-col items-center"><span className="text-[10px] font-bold text-slate-400 uppercase mb-1">{key}</span><input type="number" min="0" className="w-full text-center font-mono text-sm font-bold text-blue-600 bg-transparent outline-none" value={val} onChange={(e) => setEoConfig({ ...eoConfig, columns: { ...eoConfig.columns, [key]: parseInt(e.target.value) || 0 } })}/></div>))}</div>
                    </div>
                 </div>
              </div>
              <div className="flex-1 min-h-0 flex flex-col bg-white rounded-xl border border-slate-200 overflow-hidden shadow-sm">
                 <div className="p-3 border-b border-slate-100 bg-slate-50 flex justify-between items-center shrink-0"><span className="text-sm font-bold text-slate-700 flex items-center gap-2"><TableIcon size={16} className="text-slate-400"/> 데이터 파싱 미리보기</span>{eoFileName && <span className="text-[10px] text-blue-600 bg-blue-50 px-2 py-1 rounded font-bold">실시간 업데이트 중</span>}</div>
                 <div className="flex-1 overflow-auto custom-scrollbar relative">
                   {!eoFileName ? (<div className="absolute inset-0 flex flex-col items-center justify-center text-slate-300"><FileText size={48} className="mb-3 opacity-30"/><p className="text-sm font-medium">상단에서 EO 파일을 로드하면<br/>이곳에 미리보기가 표시됩니다.</p></div>) : (
                     <table className="w-full text-sm text-left"><thead className="bg-slate-50 sticky top-0 z-10 text-slate-500 text-xs uppercase"><tr><th className="p-3 border-b font-semibold w-[15%]">Image ID ({eoConfig.columns.id})</th><th className="p-3 border-b font-semibold">Lat/X ({eoConfig.columns.x})</th><th className="p-3 border-b font-semibold">Lon/Y ({eoConfig.columns.y})</th><th className="p-3 border-b font-semibold">Alt/Z ({eoConfig.columns.z})</th><th className="p-3 border-b font-semibold">Ω ({eoConfig.columns.omega})</th><th className="p-3 border-b font-semibold">Φ ({eoConfig.columns.phi})</th><th className="p-3 border-b font-semibold">K ({eoConfig.columns.kappa})</th></tr></thead><tbody className="divide-y divide-slate-100">{parsedPreview.map((row) => (<tr key={row.key} className="hover:bg-blue-50 transition-colors group"><td className="p-3 font-mono text-slate-700 font-medium group-hover:text-blue-700">{row.id}</td><td className="p-3 font-mono text-slate-500">{row.x}</td><td className="p-3 font-mono text-slate-500">{row.y}</td><td className="p-3 font-mono text-slate-500">{row.z}</td><td className="p-3 font-mono text-slate-400">{row.omega}</td><td className="p-3 font-mono text-slate-400">{row.phi}</td><td className="p-3 font-mono text-slate-400">{row.kappa}</td></tr>))}</tbody></table>
                   )}
                 </div>
              </div>
            </div>
          )}
          {step === 3 && (
            <div className="space-y-6 text-center max-w-2xl mx-auto h-full flex flex-col justify-center">
              <h4 className="text-xl font-bold text-slate-800">3. 카메라 모델 (IO) 선택</h4>
              <div className="max-w-sm mx-auto space-y-6 w-full"><div className="p-6 bg-slate-50 rounded-full w-32 h-32 mx-auto flex items-center justify-center border border-slate-200"><Camera size={56} className="text-slate-400"/></div><select className="w-full p-4 border border-slate-300 rounded-xl bg-white font-bold text-lg focus:ring-2 focus:ring-blue-500 outline-none" value={cameraModel} onChange={(e) => setCameraModel(e.target.value)}><option value="UltraCam Eagle 4.1">UltraCam Eagle 4.1</option><option value="Leica DMC III">Leica DMC III</option><option value="Phase One iXU">Phase One iXU</option><option value="Sony A7R IV">Sony A7R IV (Custom)</option></select><div className="bg-slate-50 p-5 rounded-xl text-left space-y-2 border border-slate-200"><div className="flex justify-between text-sm"><span className="text-slate-500">Focal Length</span><span className="font-mono font-bold text-slate-700">80 mm</span></div><div className="flex justify-between text-sm"><span className="text-slate-500">Sensor Size</span><span className="font-mono font-bold text-slate-700">53.4 x 40.0 mm</span></div><div className="flex justify-between text-sm"><span className="text-slate-500">Pixel Size</span><span className="font-mono font-bold text-slate-700">5.2 µm</span></div></div></div>
            </div>
          )}
          {step === 4 && (
            <div className="space-y-8 max-w-2xl mx-auto h-full flex flex-col justify-center">
              <h4 className="text-2xl font-bold text-slate-800 text-center">4. 업로드 결과 요약</h4>
              <div className="bg-white p-8 rounded-2xl border border-slate-200 shadow-lg space-y-6">
                 <div className="flex justify-between border-b border-slate-100 pb-4 items-center"><span className="text-slate-500 font-medium">입력 이미지</span><div className="text-right"><span className="text-xl font-bold text-slate-800">{imageCount}</span><span className="text-sm text-slate-400 ml-1">장</span></div></div>
                 <div className="flex justify-between border-b border-slate-100 pb-4 items-center"><span className="text-slate-500 font-medium">위치 데이터(EO)</span><div className="text-right"><div className="font-bold text-emerald-600 flex items-center gap-1 justify-end"><CheckCircle2 size={16}/> {eoFileName}</div><div className="text-xs text-slate-400 mt-1">{eoConfig.crs}</div></div></div>
                 <div className="flex justify-between border-b border-slate-100 pb-4 items-center"><span className="text-slate-500 font-medium">카메라 모델</span><span className="font-bold text-slate-800">{cameraModel}</span></div>
                 <div className="flex justify-between items-center pt-2"><span className="text-slate-500 font-medium">데이터 상태</span><span className="bg-blue-100 text-blue-700 px-3 py-1 rounded-full text-sm font-bold">준비 완료</span></div>
              </div>
              <p className="text-center text-sm text-slate-500"><span className="font-bold text-slate-700">확인</span> 버튼을 누르면 프로젝트 처리 옵션 화면으로 이동합니다.</p>
            </div>
          )}
        </div>
        <div className="h-20 border-t border-slate-200 px-8 flex items-center justify-end gap-3 bg-slate-50">
          {step > 1 && <button onClick={() => setStep(s => s-1)} className="px-5 py-2.5 text-slate-500 font-bold hover:bg-slate-200 rounded-lg transition-colors">이전</button>}
          {step === 1 && <button onClick={() => setStep(2)} disabled={imageCount === 0} className="px-6 py-2.5 bg-blue-600 text-white rounded-lg font-bold hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors shadow-sm">확인</button>}
          {step === 2 && <button onClick={() => setStep(3)} disabled={!eoFileName} className="px-6 py-2.5 bg-blue-600 text-white rounded-lg font-bold hover:bg-blue-700 disabled:opacity-50 transition-colors shadow-sm flex items-center gap-2">다음 <ArrowRight size={18}/></button>}
          {step === 3 && <button onClick={() => setStep(4)} className="px-6 py-2.5 bg-blue-600 text-white rounded-lg font-bold hover:bg-blue-700 transition-colors shadow-sm flex items-center gap-2">다음 <ArrowRight size={18}/></button>}
          {step === 4 && <button onClick={handleFinish} className="px-8 py-2.5 bg-emerald-600 text-white rounded-lg font-bold hover:bg-emerald-700 flex items-center gap-2 shadow-md transition-all active:scale-95"><CheckCircle2 size={18}/> 확인 및 설정 이동</button>}
        </div>
      </div>
    </div>
  );
}

// [Header]
function Header() {
  return (
    <header className="h-14 bg-white border-b border-slate-200 flex items-center justify-between px-4 z-20 shadow-sm shrink-0">
      <div className="flex items-center gap-2"><div className="bg-blue-600 p-1.5 rounded text-white"><Map size={20} /></div><h1 className="font-bold text-lg text-slate-800 tracking-tight">InnoPAM <span className="font-normal text-slate-500 text-sm hidden sm:inline">| 실감정사영상 생성 플랫폼</span></h1></div>
      <div className="flex items-center gap-4"><button className="p-2 text-slate-500 hover:bg-slate-100 rounded-full relative"><Bell size={18} /></button><div className="flex items-center gap-2 pl-4 border-l border-slate-200"><div className="w-8 h-8 bg-slate-200 rounded-full flex items-center justify-center text-slate-600"><User size={16} /></div><span className="text-sm font-medium text-slate-700 hidden md:block">관리자님</span></div></div>
    </header>
  );
}

// [Sidebar]
function Sidebar({ width, projects, selectedProjectId, checkedProjectIds, onSelectProject, onToggleCheck, onOpenUpload, onBulkExport, onSelectMultiple }) {
  const [searchTerm, setSearchTerm] = useState('');
  const [regionFilter, setRegionFilter] = useState('ALL');

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
          {isAllSelected ? <CheckSquare size={16} className="text-blue-600"/> : <Square size={16}/>}
          <span>전체 선택 ({filteredProjects.length}개)</span>
        </button>
      </div>
      <div className="flex-1 overflow-y-auto custom-scrollbar">
        <div className="p-2 space-y-1">
          {filteredProjects.map(project => (
            <ProjectItem key={project.id} project={project} isSelected={project.id === selectedProjectId} isChecked={checkedProjectIds.has(project.id)} onSelect={() => onSelectProject(project.id)} onToggle={() => onToggleCheck(project.id)}/>
          ))}
        </div>
      </div>
      {checkedProjectIds.size > 0 && (
        <div className="p-4 border-t border-slate-200 bg-slate-50 animate-in slide-in-from-bottom duration-200">
           <button onClick={onBulkExport} className="w-full flex items-center justify-center gap-2 bg-slate-800 hover:bg-slate-900 text-white py-3 rounded-lg text-sm font-bold shadow-md transition-all"><Download size={16} className="text-white" /><span>선택한 {checkedProjectIds.size}건 정사영상 내보내기</span></button>
        </div>
      )}
    </aside>
  );
}

function ProjectItem({ project, isSelected, isChecked, onSelect, onToggle }) {
  return (
    <div onClick={onSelect} className={`relative flex items-start gap-3 p-3 rounded-lg cursor-pointer transition-all border ${isSelected ? "bg-blue-50 border-blue-200 shadow-sm z-10" : "bg-white hover:bg-slate-50 border-transparent"}`}>
      <div onClick={(e) => { e.stopPropagation(); onToggle(); }} className="mt-1 text-slate-400 hover:text-blue-600 cursor-pointer">{isChecked ? <CheckSquare size={18} className="text-blue-600" /> : <Square size={18} />}</div>
      <div className="flex-1 min-w-0">
        <div className="flex justify-between items-start"><h4 className="text-sm font-bold text-slate-800 truncate">{project.title}</h4><span className={`text-[10px] px-1.5 py-0.5 rounded-full font-medium border ml-2 shrink-0 ${project.status === '완료' ? "bg-emerald-50 text-emerald-600 border-emerald-100" : "bg-blue-50 text-blue-600 border-blue-100"}`}>{project.status}</span></div>
        <div className="flex items-center gap-2 text-xs text-slate-500 mt-1"><span className="bg-slate-100 px-1.5 rounded">{project.region}</span><span className="text-slate-300">|</span><span>{project.company}</span></div>
      </div>
    </div>
  );
}

// [Map Placeholder]
function MapPlaceholder({ project, isProcessingMode, selectedImageId, onSelectImage }) {
  const [isLoading, setIsLoading] = useState(false);
  useEffect(() => { if (project) { setIsLoading(true); const t = setTimeout(() => setIsLoading(false), 800); return () => clearTimeout(t); } }, [project]);

  if (!project) return <div className="w-full h-full flex flex-col items-center justify-center bg-slate-100 map-grid text-slate-400"><div className="bg-white p-6 rounded-xl shadow-sm text-center"><Layers size={48} className="mx-auto mb-4 text-slate-300" /><p className="text-lg font-medium text-slate-600">프로젝트를 선택하세요</p></div></div>;

  return (
    <div className="w-full h-full relative overflow-hidden bg-[#e5e7eb] map-grid select-none">
      <div className="absolute inset-0 opacity-10 pointer-events-none"><div className="absolute top-1/4 left-1/4 w-96 h-96 bg-slate-400 rounded-full blur-3xl"></div><div className="absolute bottom-1/3 right-1/4 w-80 h-80 bg-blue-300 rounded-full blur-3xl"></div></div>
      <div className={`absolute transition-all duration-700 ease-out flex flex-col overflow-hidden ${isProcessingMode ? 'border border-blue-400 bg-blue-50/10' : ''}`} style={{ left: `${project.bounds.x}%`, top: `${project.bounds.y}%`, width: `${project.bounds.w}%`, height: `${project.bounds.h}%`, ...(isProcessingMode ? {} : {backgroundColor: '#78716c', boxShadow: '0 10px 15px -3px rgba(0,0,0,0.1)'}) }}>
        <div className={`absolute top-2 left-2 backdrop-blur-sm text-white text-[10px] px-2 py-1 rounded shadow-sm font-bold flex items-center gap-1 z-20 ${isProcessingMode ? 'bg-blue-600' : 'bg-black/60'}`}>{isProcessingMode ? <MapPin size={10}/> : <Layers size={10}/>}{project.title} {isProcessingMode ? '(Points)' : 'Ortho'}</div>
        <div className="w-full h-full relative" style={{ opacity: isLoading ? 0 : 1 }}>
          {project.images.map((img) => (
            <div key={img.id} onClick={(e) => { e.stopPropagation(); onSelectImage(img.id); }} className={`absolute rounded-full flex items-center justify-center cursor-pointer transition-all ${isProcessingMode ? 'w-2 h-2 bg-yellow-400 hover:scale-150' : `w-4 h-4 -ml-2 -mt-2 group ${img.id === selectedImageId ? 'z-30 scale-150' : 'z-10 hover:z-20 hover:scale-125'}`}`} style={{ left: `${img.x}%`, top: `${img.y}%` }}>
               {!isProcessingMode && (<div className={`w-2 h-2 rounded-full shadow-sm transition-colors duration-200 ${img.id === selectedImageId ? 'bg-blue-500 ring-2 ring-white' : 'bg-white/30 group-hover:bg-white ring-1 ring-white'}`} />)}
            </div>
          ))}
        </div>
      </div>
      <div className="absolute right-4 bottom-4 flex flex-col gap-2 z-10"><button className="w-9 h-9 bg-white rounded shadow-sm font-bold">+</button><button className="w-9 h-9 bg-white rounded shadow-sm font-bold">-</button></div>
    </div>
  );
}

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
            <div className="flex justify-between border-b pb-2"><span className="text-slate-500">상태</span><span className={`font-bold ${project.status==='완료'?'text-emerald-600':project.status==='오류'?'text-red-600':'text-blue-600'}`}>{project.status}</span></div>
          </div>
        </div>
        <div className="flex-1 p-6 bg-slate-50 overflow-y-auto">
           {project.orthoResult ? (<div className="bg-white border border-slate-200 rounded-xl p-5 shadow-sm flex items-center justify-between"><div className="flex items-center gap-4"><FileImage size={24} className="text-slate-400"/><div><div className="font-bold">Result_Ortho.tif</div><div className="text-xs text-slate-500">{project.orthoResult.fileSize}</div></div></div><button onClick={onExport} disabled={project.status !== '완료'} className="bg-slate-800 hover:bg-slate-900 disabled:bg-slate-300 text-white px-4 py-2 rounded text-sm flex gap-2 transition-colors font-bold shadow-sm"><Download size={16}/>정사영상 내보내기</button></div>) : (<div className="flex flex-col items-center justify-center h-32 border-2 border-dashed border-slate-300 rounded-xl text-slate-400 gap-2"><Loader2 size={24} className={project.status === '진행중' ? "animate-spin" : ""} /><span className="text-sm font-medium">{project.status === '진행중' ? '정사영상 생성 처리 중...' : '결과물이 없습니다.'}</span></div>)}
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-full w-full bg-white relative">
      <button onClick={onCloseImage} className="absolute top-4 right-4 z-10 p-2 hover:bg-slate-100 rounded-full"><X size={20} /></button>
      <div className="w-1/3 min-w-[320px] bg-slate-900 p-4 flex flex-col justify-center relative">
        <div className="flex-1 bg-black/40 rounded-lg overflow-hidden relative border border-white/10">
           {isImageLoaded ? <div className="w-full h-full relative"><div className="w-full h-full opacity-80" style={{backgroundColor:image.thumbnailColor}}></div><div className="absolute inset-0 flex items-center justify-center text-white/30 text-4xl font-black rotate-12">PREVIEW</div></div> : <div className="flex h-full items-center justify-center text-slate-500"><Loader2 className="animate-spin" /></div>}
        </div>
      </div>
      <div className="flex-1 p-6 overflow-y-auto bg-slate-50">
        <h4 className="font-bold mb-4">품질 점검</h4>
        <div className="space-y-2 mb-4"><label className="flex items-center gap-3 p-3 bg-white border rounded cursor-pointer"><input type="checkbox" checked={qcData.issues?.includes('blur')||false} onChange={() => onQcUpdate(image.id, { ...qcData, issues: [...(qcData.issues||[]), 'blur'], status: 'Fail' })} /><span className="text-sm">블러 (Blur)</span></label></div>
        <textarea className="w-full p-3 border rounded text-sm bg-white" placeholder="코멘트 입력..." value={qcData.comment||''} onChange={e => onQcUpdate(image.id, {...qcData, comment: e.target.value})}></textarea>
      </div>
    </div>
  );
}

// --- 3. MAIN APP ---
export default function App() {
  const [projects, setProjects] = useState([]);
  const [selectedProjectId, setSelectedProjectId] = useState(null);
  const [checkedProjectIds, setCheckedProjectIds] = useState(new Set());
  const [selectedImageId, setSelectedImageId] = useState(null);
  const [sidebarWidth, setSidebarWidth] = useState(320);
  const [isResizing, setIsResizing] = useState(false);
  const [isUploadOpen, setIsUploadOpen] = useState(false);
  
  const [viewMode, setViewMode] = useState('dashboard'); 
  const [processingProject, setProcessingProject] = useState(null);
  
  // Export Modal State
  const [exportModalState, setExportModalState] = useState({ isOpen: false, projectIds: [] });

  const selectedProject = viewMode === 'processing' ? processingProject : projects.find(p => p.id === selectedProjectId) || null;
  const selectedImage = selectedProject?.images.find(img => img.id === selectedImageId) || null;
  const [qcData, setQcData] = useState(() => JSON.parse(localStorage.getItem('innopam_qc_data') || '{}'));

  useEffect(() => { setTimeout(() => setProjects(mockProjects), 500); }, []);

  const startResizing = useCallback(() => setIsResizing(true), []);
  useEffect(() => {
    const handleMove = (e) => isResizing && setSidebarWidth(Math.max(240, Math.min(800, e.clientX)));
    const handleUp = () => setIsResizing(false);
    if(isResizing) { window.addEventListener('mousemove', handleMove); window.addEventListener('mouseup', handleUp); }
    return () => { window.removeEventListener('mousemove', handleMove); window.removeEventListener('mouseup', handleUp); };
  }, [isResizing]);

  const handleUploadComplete = (newProject) => { setProcessingProject(newProject); setViewMode('processing'); };
  const handleStartProcessing = () => {
    const finalProject = { ...processingProject, status: '진행중', progress: 5 };
    setProjects(prev => [finalProject, ...prev]);
    setSelectedProjectId(finalProject.id);
    setViewMode('dashboard'); 
    setProcessingProject(null);
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
          />
        )}
        <div className="w-1.5 bg-slate-200 hover:bg-blue-400 cursor-col-resize z-20 flex items-center justify-center group" onMouseDown={startResizing}><div className="h-8 w-1 bg-slate-300 rounded-full group-hover:bg-white/50" /></div>
        <div className="flex flex-col flex-1 min-w-0 bg-slate-200">
          <main className="flex-1 relative overflow-hidden">
            <MapPlaceholder project={selectedProject} isProcessingMode={viewMode === 'processing'} selectedImageId={selectedImageId} onSelectImage={(id) => setSelectedImageId(id)} />
          </main>
          {viewMode === 'dashboard' && (
            <div className="h-[350px] border-t border-slate-300 bg-white shadow-sm z-20 relative flex items-center justify-center text-slate-400">
              <InspectorPanel 
                project={selectedProject} 
                image={selectedImage} 
                qcData={qcData[selectedImageId] || {}} 
                onQcUpdate={(id, d) => { const n = {...qcData, [id]: d}; setQcData(n); localStorage.setItem('innopam_qc_data', JSON.stringify(n)); }} 
                onCloseImage={() => setSelectedImageId(null)}
                onExport={() => openExportDialog([selectedProject.id])} 
              />
            </div>
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