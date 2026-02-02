import React, { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import {
  Map, Settings, Bell, User, Search,
  Layers, FileImage, AlertTriangle, Loader2, X,
  Download, Box, Maximize2,
  Sparkles, CheckCircle2, MapPin, UploadCloud,
  FolderOpen, FilePlus, FileText, Camera, ArrowRight, ArrowLeft, Save, Play, Table as TableIcon, RefreshCw, CheckSquare, Square, FileOutput, LogOut, Trash2, Bookmark,
  Folder, FolderPlus, ChevronRight, ChevronDown, GripVertical, MoreHorizontal, Edit2, Plus
} from 'lucide-react';

// API & Auth imports
import { AuthProvider, useAuth } from './contexts/AuthContext';
import { useProjects, useProcessingStatus } from './hooks/useApi';
import LoginPage from './components/LoginPage';
import api from './api/client';
import S3MultipartUploader from './services/s3Upload';
import { useProcessingProgress } from './hooks/useProcessingProgress';

// Modularized Components
import Header from './components/Dashboard/Header';
import Sidebar from './components/Dashboard/Sidebar';
import ExportDialog from './components/Project/ExportDialog';
import UploadProgressPanel from './components/Upload/UploadProgressPanel';
import ProcessingSidebar from './components/Processing/ProcessingSidebar';
import UploadWizard from './components/Upload/UploadWizard';
import InspectorPanel from './components/Project/InspectorPanel';
import ProjectMap from './components/Project/ProjectMap';

// Leaflet
import 'leaflet/dist/leaflet.css';
import ResumableDownloader from './services/download';
import DashboardView from './components/Dashboard/DashboardView';


// --- 1. CONSTANTS ---
const REGIONS = ['경기 권역', '충청 권역', '강원 권역', '전라 권역', '경상 권역'];
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
    wx: 127.5, // Default center point in Korea to avoid confusing random scatter
    wy: 36.5,
    hasEo: true, // Mark as having EO for visualization
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
      // Use real bounds from backend, don't mock it!
      bounds: p.bounds,
      orthoResult: (p.status === 'completed' || p.status === '완료') ? {
        resolution: '5cm GSD',
        fileSize: p.ortho_path ? 'Loading...' : 'Check storage',
        generatedAt: p.updated_at?.slice(0, 10)
      } : null,
    }));
  }, [apiProjects]);

  // Groups state for folder organization
  const [groups, setGroups] = useState([]);
  const [expandedGroupIds, setExpandedGroupIds] = useState(new Set());
  const [isGroupModalOpen, setIsGroupModalOpen] = useState(false);
  const [editingGroup, setEditingGroup] = useState(null);
  const [activeGroupId, setActiveGroupId] = useState(null); // For group filtering

  // Filter projects by active group
  const filteredProjects = useMemo(() => {
    if (!activeGroupId) return projects;
    return projects.filter(p => p.group_id === activeGroupId);
  }, [projects, activeGroupId]);

  // Fetch groups on mount
  useEffect(() => {
    api.getGroups().then(data => {
      setGroups(Array.isArray(data) ? data : (data.items || []));
    }).catch(err => console.error('Failed to fetch groups:', err));
  }, []);

  // Group handlers
  const handleCreateGroup = async (name, color) => {
    try {
      const created = await api.createGroup({ name, color: color || '#94a3b8' });
      setGroups(prev => [...prev, created]);
      setExpandedGroupIds(prev => new Set([...prev, created.id]));
      return created;
    } catch (err) {
      console.error('Failed to create group:', err);
      throw err;
    }
  };

  const handleUpdateGroup = async (groupId, data) => {
    try {
      const updated = await api.updateGroup(groupId, data);
      setGroups(prev => prev.map(g => g.id === groupId ? { ...g, ...updated } : g));
    } catch (err) {
      console.error('Failed to update group:', err);
    }
  };

  const handleDeleteGroup = async (groupId) => {
    if (!window.confirm('이 그룹을 삭제하시겠습니까? 그룹 내 프로젝트는 유지됩니다.')) return;
    try {
      await api.deleteGroup(groupId);
      setGroups(prev => prev.filter(g => g.id !== groupId));
      refreshProjects(); // 프로젝트 목록 갱신하여 미분류로 표시
    } catch (err) {
      console.error('Failed to delete group:', err);
    }
  };

  const handleMoveProjectToGroup = async (projectId, groupId) => {
    try {
      await api.moveProjectToGroup(projectId, groupId);
      refreshProjects();
    } catch (err) {
      console.error('Failed to move project:', err);
    }
  };

  const handleRenameProject = async (projectId, newTitle) => {
    try {
      await api.updateProject(projectId, { title: newTitle });
      refreshProjects();
    } catch (err) {
      console.error('Failed to rename project:', err);
      alert('이름 변경 실패: ' + err.message);
    }
  };

  const toggleGroupExpand = (groupId) => {
    setExpandedGroupIds(prev => {
      const next = new Set(prev);
      if (next.has(groupId)) next.delete(groupId);
      else next.add(groupId);
      return next;
    });
  };

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
  const [viewMode, setViewMode] = useState(initialViewMode);
  const [processingProject, setProcessingProject] = useState(null);
  const activeProjectId = viewMode === 'processing'
    ? (processingProject?.id || selectedProjectId)
    : selectedProjectId;

  // 자동 선택 제거: 사용자가 명시적으로 선택할 때만 프로젝트 선택
  // 로고 클릭 시 전체 대시보드를 보여주기 위해 자동 선택 비활성화
  const [projectImages, setProjectImages] = useState([]); // Store fetched images
  // 멀티 프로젝트 업로드 지원: 프로젝트별로 업로드 상태 관리
  const [uploadsByProject, setUploadsByProject] = useState({}); // { projectId: [uploads...] }
  const [uploaderControllers, setUploaderControllers] = useState({}); // { projectId: controller }

  // 모든 프로젝트의 업로드를 평탄화 (대시보드용)
  const allUploads = useMemo(() => {
    return Object.values(uploadsByProject).flat();
  }, [uploadsByProject]);

  // 현재 프로젝트의 업로드만 필터링 (처리 옵션 화면용)
  const currentProjectUploads = useMemo(() => {
    const currentProjectId = processingProject?.id || selectedProjectId;
    return currentProjectId ? (uploadsByProject[currentProjectId] || []) : [];
  }, [uploadsByProject, processingProject, selectedProjectId]);

  // 활성 업로드가 있는지 확인
  const hasAnyActiveUploads = useMemo(() => {
    return allUploads.some(u => u.status === 'uploading' || u.status === 'waiting');
  }, [allUploads]);

  const [loadingImages, setLoadingImages] = useState(false);
  const [imageRefreshKey, setImageRefreshKey] = useState(0); // Trigger to force image reload

  // 완료된 프로젝트의 업로드 상태 정리 (프론트엔드 업로더가 없는 경우)
  useEffect(() => {
    // 각 프로젝트별로 업로더가 없고 업로드가 완료된 경우 정리
    Object.keys(uploadsByProject).forEach(projectId => {
      const uploads = uploadsByProject[projectId] || [];
      const hasController = !!uploaderControllers[projectId];
      const hasActiveUploads = uploads.some(u => u.status === 'uploading' || u.status === 'waiting');

      // 컨트롤러가 없고 활성 업로드가 없으면 해당 프로젝트 업로드 정리
      if (!hasController && !hasActiveUploads && uploads.length > 0) {
        // 완료된 지 5초 후에 정리 (사용자가 결과를 볼 시간)
        const allCompleted = uploads.every(u => u.status === 'completed' || u.status === 'error');
        if (allCompleted) {
          setTimeout(() => {
            setUploadsByProject(prev => {
              const { [projectId]: _, ...rest } = prev;
              return rest;
            });
          }, 5000);
        }
      }
    });
  }, [uploadsByProject, uploaderControllers]);

  // 처리 옵션 설정 화면에서 해당 프로젝트의 업로드 진행 상태를 표시 (백엔드 기반)
  useEffect(() => {
    // 처리 옵션 설정 화면이 아니면 스킵
    if (viewMode !== 'processing') return;

    const currentProjectId = processingProject?.id || selectedProjectId;
    if (!currentProjectId) return;

    // 이미 프론트엔드 업로더가 해당 프로젝트를 관리 중이면 스킵
    if (uploaderControllers[currentProjectId]) return;

    // 이미 업로드 데이터가 있으면 스킵
    const existingUploads = uploadsByProject[currentProjectId] || [];
    const hasActiveUploads = existingUploads.some(u => u.status === 'uploading' || u.status === 'waiting');
    if (hasActiveUploads) return;

    const currentProject = projects.find(p => p.id === currentProjectId);
    if (!currentProject?.upload_in_progress) return;

    // 백엔드 데이터로 synthetic uploads 생성
    api.getProjectImages(currentProjectId)
      .then(images => {
        if (images.length === 0) return;

        const syntheticUploads = images.map(img => ({
          name: img.filename,
          projectId: currentProjectId,
          projectTitle: currentProject.title,
          status: img.upload_status === 'completed' ? 'completed' :
                  img.upload_status === 'uploading' ? 'uploading' : 'waiting',
          progress: img.upload_status === 'completed' ? 100 : 0,
        }));

        const hasUploading = syntheticUploads.some(u => u.status === 'uploading' || u.status === 'waiting');
        if (hasUploading) {
          setUploadsByProject(prev => ({
            ...prev,
            [currentProjectId]: syntheticUploads
          }));
        }
      })
      .catch(err => {
        console.warn('Failed to fetch upload status from backend:', err);
      });
  }, [viewMode, processingProject, selectedProjectId, projects, uploadsByProject, uploaderControllers]);

  // Fetch images when project is selected
  useEffect(() => {
    if (!activeProjectId) {
      setProjectImages([]);
      return;
    }

    setLoadingImages(true);
    api.getProjectImages(activeProjectId)
      .then(images => {
        // Normalize logic
        if (images.length === 0) {
          setProjectImages([]);
          return;
        }

        const points = images.map(img => {
          const eo = img.exterior_orientation;
          return {
            id: img.id,
            name: img.filename,
            // If EO exists, use it. Otherwise 0
            wx: eo ? eo.x : 0,
            wy: eo ? eo.y : 0,
            z: eo ? eo.z : null,
            omega: eo ? eo.omega : null,
            phi: eo ? eo.phi : null,
            kappa: eo ? eo.kappa : null,
            hasEo: !!eo,
            thumbnail_url: img.thumbnail_url || null,
            file_size: img.file_size || null,
            thumbnailColor: `hsl(${Math.random() * 360}, 70%, 80%)`
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
  }, [activeProjectId, imageRefreshKey]); // Add imageRefreshKey to force refresh
  const [checkedProjectIds, setCheckedProjectIds] = useState(new Set());
  const [selectedImageId, setSelectedImageId] = useState(null);
  const [searchTerm, setSearchTerm] = useState('');
  const [regionFilter, setRegionFilter] = useState('ALL');
  const [sidebarWidth, setSidebarWidth] = useState(800);
  const [isResizing, setIsResizing] = useState(false);
  const [isUploadOpen, setIsUploadOpen] = useState(false);
  const [showInspector, setShowInspector] = useState(false); // Inspector only opens on double-click

  const processingViewProject = useMemo(() => {
    if (!processingProject) return null;
    const fromList = projects.find(p => p.id === processingProject.id);
    if (!fromList) return processingProject;
    return {
      ...processingProject,
      ...fromList,
      images: processingProject.images || fromList.images || projectImages
    };
  }, [processingProject, projects, projectImages]);


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

  // 브라우저 뒤로가기/앞으로가기 처리
  // 글로벌 업로드: 앱 내 네비게이션 시 업로드 유지 (업로드 중단하지 않음)
  useEffect(() => {
    const handlePopState = (event) => {
      // 뒤로가기 시 대시보드로 복귀 (업로드는 계속 진행)
      setViewMode('dashboard');
      setProcessingProject(null);
      setSelectedProjectId(null);
      setShowInspector(false);
      setHighlightProjectId(null);
      // 업로드는 유지 (글로벌 업로드)
      refreshProjects();
    };

    window.addEventListener('popstate', handlePopState);
    return () => window.removeEventListener('popstate', handlePopState);
  }, [refreshProjects]);

  // 업로드 중 페이지 이탈 시 경고 표시
  useEffect(() => {
    if (!hasAnyActiveUploads) return;

    const handleBeforeUnload = (e) => {
      e.preventDefault();
      e.returnValue = '업로드가 진행 중입니다. 페이지를 벗어나면 업로드가 중단됩니다.';
      return e.returnValue;
    };

    window.addEventListener('beforeunload', handleBeforeUnload);
    return () => window.removeEventListener('beforeunload', handleBeforeUnload);
  }, [hasAnyActiveUploads]);

  // Periodic refresh while processing is active (dashboard auto-update)
  useEffect(() => {
    const hasActiveProcessing = projects.some(p =>
      p.status === 'processing' ||
      p.status === 'queued' ||
      p.status === 'running' ||
      p.status === '진행중' ||
      p.status === '대기'
    );

    if (!hasActiveProcessing) return;

    const intervalId = setInterval(() => {
      refreshProjects();
    }, 10000);

    return () => clearInterval(intervalId);
  }, [projects, refreshProjects]);

  // Export Modal State
  const [exportModalState, setExportModalState] = useState({ isOpen: false, projectIds: [] });

  // Highlight state for post-processing animation
  const [highlightProjectId, setHighlightProjectId] = useState(null);

  const selectedProject = useMemo(() => {
    // Try to find in projects list first
    const proj = projects.find(p => p.id === selectedProjectId);

    if (proj) {
      return {
        ...proj,
        images: projectImages
      };
    }

    // Fallback to processingProject (for newly created projects)
    if (viewMode === 'processing' && processingProject) {
      return {
        ...processingProject,
        images: projectImages.length > 0 ? projectImages : (processingProject.images || [])
      };
    }

    return null;
  }, [viewMode, processingProject, projects, selectedProjectId, projectImages]);

  const selectedImage = selectedProject?.images?.find(img => img.id === selectedImageId) || null;
  const [qcData, setQcData] = useState(() => JSON.parse(localStorage.getItem('innopam_qc_data') || '{}'));

  // RAF-based smooth resize handling with overlay
  const rafRef = useRef(null);
  const overlayRef = useRef(null);

  const startResizing = useCallback((e) => {
    e.preventDefault();
    setIsResizing(true);

    // Create full-screen overlay to capture all mouse events
    const overlay = document.createElement('div');
    overlay.style.cssText = `
      position: fixed;
      top: 0;
      left: 0;
      right: 0;
      bottom: 0;
      z-index: 99999;
      cursor: col-resize;
      user-select: none;
      -webkit-user-select: none;
    `;
    document.body.appendChild(overlay);
    overlayRef.current = overlay;
    document.body.style.cursor = 'col-resize';
  }, []);

  useEffect(() => {
    if (!isResizing) return;

    const handleMove = (e) => {
      e.preventDefault();
      e.stopPropagation();
      if (rafRef.current) return;
      rafRef.current = requestAnimationFrame(() => {
        setSidebarWidth(Math.max(240, Math.min(800, e.clientX)));
        rafRef.current = null;
      });
    };

    const handleUp = (e) => {
      e.preventDefault();
      setIsResizing(false);
      document.body.style.cursor = '';

      // Remove overlay
      if (overlayRef.current) {
        overlayRef.current.remove();
        overlayRef.current = null;
      }

      if (rafRef.current) {
        cancelAnimationFrame(rafRef.current);
        rafRef.current = null;
      }
    };

    // Use capture phase for better event handling
    document.addEventListener('mousemove', handleMove, { capture: true, passive: false });
    document.addEventListener('mouseup', handleUp, { capture: true });

    return () => {
      document.removeEventListener('mousemove', handleMove, { capture: true });
      document.removeEventListener('mouseup', handleUp, { capture: true });
      if (rafRef.current) {
        cancelAnimationFrame(rafRef.current);
        rafRef.current = null;
      }
      if (overlayRef.current) {
        overlayRef.current.remove();
        overlayRef.current = null;
      }
    };
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
      let imagesToUse = generatePlaceholderImages(created.id, files?.length || 0);
      if (eoFile) {
        console.log('Uploading EO data...');
        try {
          await api.uploadEoData(created.id, eoFile, eoConfig);
          // Wait briefly (500ms) for DB commit and fetch real images
          await new Promise(resolve => setTimeout(resolve, 500));
          const fetchedImages = await api.getProjectImages(created.id);
          if (fetchedImages && fetchedImages.length > 0) {
            const points = fetchedImages.map(img => {
              const eo = img.exterior_orientation;
              return {
                id: img.id,
                name: img.filename,
                // If EO exists, use it. Otherwise 0
                wx: eo ? eo.x : 0,
                wy: eo ? eo.y : 0,
                z: eo ? eo.z : null,
                omega: eo ? eo.omega : null,
                phi: eo ? eo.phi : null,
                kappa: eo ? eo.kappa : null,
                hasEo: !!eo,
                thumbnail_url: img.thumbnail_url || null,
                file_size: img.file_size || null,
                thumbnailColor: `hsl(${Math.random() * 360}, 70%, 80%)`
              };
            });
            imagesToUse = points.filter(p => p.hasEo);
            setProjectImages(imagesToUse); // Update global state for map
          }
          alert("EO data uploaded successfully.");
        } catch (e) {
          console.error(e);
          alert("Failed to upload EO data: " + e.message);
        }
      }

      // 4. Initiate TUS Image Uploads
      if (files && files.length > 0) {
        console.log(`Starting upload for ${files.length} images...`);
        const projectId = created.id;

        // Initialize progress state for this project
        const initialUploads = files.map(f => ({
          name: f.name,
          projectId: projectId,
          projectTitle: created.title,
          progress: 0,
          status: 'waiting',
          speed: null,
          eta: null
        }));

        setUploadsByProject(prev => ({
          ...prev,
          [projectId]: initialUploads
        }));

        const uploader = new S3MultipartUploader(api.token);
        const controller = uploader.uploadFiles(files, projectId, {
          concurrency: 6,
          partConcurrency: 4,
          partSize: 10 * 1024 * 1024, // 10MB parts
          onFileProgress: (idx, name, progress) => {
            setUploadsByProject(prev => {
              const projectUploads = prev[projectId] || [];
              const next = [...projectUploads];
              if (next[idx]) {
                next[idx] = {
                  ...next[idx],
                  progress: progress.percentage,
                  status: 'uploading',
                  speed: S3MultipartUploader.formatSpeed(progress.speed),
                  eta: S3MultipartUploader.formatETA(progress.eta)
                };
              }
              return { ...prev, [projectId]: next };
            });
          },
          onFileComplete: (idx, name) => {
            console.log(`Uploaded ${name}`);
            setUploadsByProject(prev => {
              const projectUploads = prev[projectId] || [];
              const next = [...projectUploads];
              if (next[idx]) {
                next[idx] = { ...next[idx], status: 'completed', progress: 100 };
              }
              return { ...prev, [projectId]: next };
            });
          },
          onAllComplete: async () => {
            console.log(`All uploads finished for project ${projectId}`);
            // 해당 프로젝트의 컨트롤러만 제거
            setUploaderControllers(prev => {
              const { [projectId]: _, ...rest } = prev;
              return rest;
            });

            // 썸네일 생성 대기
            const attempts = 8;
            const intervalMs = 4000;
            for (let i = 1; i <= attempts; i += 1) {
              const delay = i * intervalMs;
              setTimeout(() => {
                setImageRefreshKey(prev => prev + 1);
              }, delay);
            }
          },
          onError: (idx, name, err) => {
            console.error(`Failed ${name}`, err);
            setUploadsByProject(prev => {
              const projectUploads = prev[projectId] || [];
              const next = [...projectUploads];
              if (next[idx]) {
                next[idx] = { ...next[idx], status: 'error' };
              }
              return { ...prev, [projectId]: next };
            });
          }
        });

        setUploaderControllers(prev => ({
          ...prev,
          [projectId]: controller
        }));
      }

      // 5. Update UI State (Switch to Processing View immediately)
      const projectForProcessing = {
        ...created,
        status: '대기',
        imageCount: files?.length || 0,
        images: imagesToUse, // Use real images if fetched, else placeholders
        bounds: { x: 30, y: 30, w: 40, h: 40 },
        cameraModel: cameraModel
      };

      setProcessingProject(projectForProcessing);
      setViewMode('processing');
      // 브라우저 히스토리에 추가 (뒤로가기 지원)
      window.history.pushState({ viewMode: 'processing' }, '', `?viewMode=processing&projectId=${created.id}`);

      // Ensure project list is refreshed with new data including EO
      await refreshProjects();
      setImageRefreshKey(prev => prev + 1);

    } catch (err) {
      console.error('Failed to create project:', err);
      alert('프로젝트 생성 실패: ' + err.message);
    }
  };

  const handleStartProcessing = async (options = {}, force = false) => {
    if (!processingProject) return;

    const projectId = processingProject.id;

    // Use provided options or defaults (Metashape only)
    const processingOptions = {
      engine: 'metashape',  // Fixed to metashape
      gsd: options.gsd || 5.0,
      output_crs: options.output_crs || 'EPSG:5186',
      output_format: options.output_format || 'GeoTiff',
      process_mode: options.process_mode || 'Normal',
      build_point_cloud: options.build_point_cloud || false,
    };

    try {
      // Start processing via API
      const result = await api.startProcessing(projectId, processingOptions, force);
      console.log('Processing started:', result);

      // 해당 프로젝트의 업로드 패널 자동 숨김 (처리 시작 시)
      setUploadsByProject(prev => {
        const { [projectId]: _, ...rest } = prev;
        return rest;
      });
      setProcessingProject(prev => prev ? ({ ...prev, status: '대기', progress: 0 }) : prev);

      // Stay on processing page to show progress
      // The ProcessingSidebar will show progress via WebSocket connection
      alert('처리가 시작되었습니다. 진행률은 이 화면에서 확인할 수 있습니다.\n\n처리 시간은 이미지 수에 따라 오래 걸릴 수 있습니다.');

    } catch (err) {
      console.error('Failed to start processing:', err);

      // 불완전한 업로드가 있는 경우 사용자에게 확인 요청
      if (err.status === 409 && err.data?.type === 'incomplete_uploads') {
        const { message, confirm_message, completed_count, incomplete_count } = err.data;
        const shouldProceed = window.confirm(
          `${message}\n\n${confirm_message}\n\n` +
          `[확인]을 누르면 완료된 ${completed_count}개 이미지만으로 처리를 시작합니다.\n` +
          `[취소]를 누르면 처리를 중단합니다.`
        );

        if (shouldProceed) {
          // force=true로 다시 시도
          return handleStartProcessing(options, true);
        }
        return;
      }

      alert('처리 시작 실패: ' + err.message);
      return;
    }

    // Refresh project list to update status
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
      <style>{`
        .custom-scrollbar::-webkit-scrollbar{width:6px}
        .custom-scrollbar::-webkit-scrollbar-thumb{background:#cbd5e1;border-radius:3px}
        .map-grid{background-image:linear-gradient(to right,rgba(0,0,0,0.05) 1px,transparent 1px),linear-gradient(to bottom,rgba(0,0,0,0.05) 1px,transparent 1px);background-size:40px 40px}
        @keyframes slideInFromLeft {
          from { transform: translateX(-100%); opacity: 0; }
          to { transform: translateX(0); opacity: 1; }
        }
        @keyframes slideInFromRight {
          from { transform: translateX(100%); opacity: 0; }
          to { transform: translateX(0); opacity: 1; }
        }
        @keyframes slideOutToRight {
          from { transform: translateX(0); opacity: 1; }
          to { transform: translateX(100%); opacity: 0; }
        }
        @keyframes fadeIn {
          from { opacity: 0; }
          to { opacity: 1; }
        }
        .panel-slide-in-right {
          animation: slideInFromRight 0.3s cubic-bezier(0.4, 0, 0.2, 1) forwards;
        }
      `}</style>
      <Header onLogoClick={() => {
        // 글로벌 업로드: 앱 내 네비게이션 시 업로드 유지 (경고 없이 이동)
        // 상태 기반 네비게이션으로 대시보드 복귀
        setViewMode('dashboard');
        setProcessingProject(null);
        setSelectedProjectId(null);
        setShowInspector(false);
        setHighlightProjectId(null);
        setActiveGroupId(null);
        setSearchTerm('');
        setRegionFilter('ALL');
        // 업로드는 유지 (글로벌 업로드)
        refreshProjects();
        window.history.pushState({}, '', window.location.pathname);
      }} />
      <div className="flex flex-1 overflow-hidden relative">
        {viewMode === 'processing' ? (
          <ProcessingSidebar
            width={sidebarWidth}
            project={processingViewProject}
            activeUploads={currentProjectUploads}
            onCancel={() => {
              // 글로벌 업로드: 앱 내 네비게이션 시 업로드 유지 (경고 없이 이동)
              setViewMode('dashboard');
              setProcessingProject(null);
              // 업로드는 유지 (글로벌 업로드)
              refreshProjects();
            }}
            onStartProcessing={handleStartProcessing}
            onEoReloaded={async () => {
              await refreshProjects();
              setImageRefreshKey(prev => prev + 1);
            }}
            onCancelled={async () => {
              await refreshProjects();
              setProcessingProject(prev => prev ? ({ ...prev, status: '취소', progress: 0 }) : prev);
            }}
            onComplete={async () => {
              console.log('onComplete called - refreshing data'); // 디버그용
              // 프로젝트 목록 갱신
              await refreshProjects();
              setImageRefreshKey(prev => prev + 1);

              // processingProject 상태를 완료로 직접 설정
              if (processingProject?.id) {
                setProcessingProject(prev => prev ? ({
                  ...prev,
                  status: '완료'
                }) : null);
              }
            }}
          />
        ) : (
          <Sidebar
            width={sidebarWidth}
            isResizing={isResizing}
            projects={projects}
            selectedProjectId={selectedProjectId}
            checkedProjectIds={checkedProjectIds}
            onSelectProject={(id) => { setSelectedProjectId(id); setHighlightProjectId(id); setSelectedImageId(null); setShowInspector(false); }}
            onOpenInspector={(id) => { setSelectedProjectId(id); setShowInspector(true); }}
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
            onRenameProject={handleRenameProject}
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
            onOpenProcessing={async (projectId) => {
              const proj = projects.find(p => p.id === projectId);
              if (proj) {
                // If projectId differs from current selectedProjectId, we need to fetch images first
                let imagesToUse = projectImages;
                if (projectId !== selectedProjectId) {
                  // Fetch images for this project
                  try {
                    const images = await api.getProjectImages(projectId);
                    // Normalize like we do in the useEffect
                    const points = images.map(img => {
                      const eo = img.exterior_orientation;
                      return {
                        id: img.id,
                        name: img.filename,
                        wx: eo ? eo.x : 0,
                        wy: eo ? eo.y : 0,
                        z: eo ? eo.z : null,
                        omega: eo ? eo.omega : null,
                        phi: eo ? eo.phi : null,
                        kappa: eo ? eo.kappa : null,
                        hasEo: !!eo,
                        thumbnail_url: img.thumbnail_url || null,
                        file_size: img.file_size || null,
                        thumbnailColor: `hsl(${Math.random() * 360}, 70%, 80%)`
                      };
                    });
                    imagesToUse = points.filter(p => p.hasEo);
                    // Also update state so map can show them
                    setProjectImages(imagesToUse);
                  } catch (err) {
                    console.error('Failed to fetch project images:', err);
                    imagesToUse = [];
                  }
                }
                setProcessingProject({
                  ...proj,
                  images: imagesToUse
                });
                setSelectedProjectId(projectId);
                setViewMode('processing');
                // 브라우저 히스토리에 추가 (뒤로가기 지원)
                window.history.pushState({ viewMode: 'processing' }, '', `?viewMode=processing&projectId=${projectId}`);
              }
            }}
            onOpenExport={(projectId) => {
              openExportDialog([projectId]);
            }}
            searchTerm={searchTerm}
            onSearchTermChange={setSearchTerm}
            regionFilter={regionFilter}
            onRegionFilterChange={setRegionFilter}
            groups={groups}
            expandedGroupIds={expandedGroupIds}
            onToggleGroupExpand={toggleGroupExpand}
            onMoveProjectToGroup={handleMoveProjectToGroup}
            onCreateGroup={() => setIsGroupModalOpen(true)}
            onEditGroup={setEditingGroup}
            onDeleteGroup={handleDeleteGroup}
            activeGroupId={activeGroupId}
            onFilterGroup={(groupId) => setActiveGroupId(prev => prev === groupId ? null : groupId)}
          />
        )}
        <div className="w-1.5 bg-slate-200 hover:bg-blue-400 cursor-col-resize z-20 flex items-center justify-center group" onMouseDown={startResizing}><div className="h-8 w-1 bg-slate-300 rounded-full group-hover:bg-white/50" /></div>
        <div className="flex flex-col flex-1 min-w-0 bg-slate-50">
          {/* Dashboard mode view logic */}
          {viewMode === 'dashboard' ? (
            <>
              {/* Always use DashboardView for both single and double click */}
              <DashboardView
                projects={filteredProjects}
                selectedProject={selectedProject}
                sidebarWidth={sidebarWidth}
                onProjectClick={(project) => {
                  setSelectedProjectId(project.id);
                  setHighlightProjectId(project.id);
                }}
                regionFilter={regionFilter}
                onRegionClick={(regionId, regionName) => {
                  setRegionFilter(prev => prev === regionName ? 'ALL' : regionName);
                }}
                onDeselectProject={() => {
                  console.log('onDeselectProject called'); // 디버그용
                  setSelectedProjectId(null);
                  setShowInspector(false);
                  setHighlightProjectId(null);
                  // processingProject도 null로 설정 (대시보드 모드에서 완전 초기화)
                  if (viewMode === 'dashboard') {
                    setProcessingProject(null);
                  }
                }}
                highlightProjectId={highlightProjectId}
                onHighlightEnd={() => setHighlightProjectId(null)}
                showInspector={showInspector}
                renderInspector={(project) => (
                  <InspectorPanel
                    project={project}
                    image={selectedImage}
                    qcData={qcData[selectedImageId] || {}}
                    onQcUpdate={(id, d) => { const n = { ...qcData, [id]: d }; setQcData(n); localStorage.setItem('innopam_qc_data', JSON.stringify(n)); }}
                    onCloseImage={() => setSelectedImageId(null)}
                    onExport={() => openExportDialog([project.id])}
                  />
                )}
              />
            </>
          ) : (
            /* Processing mode: show Map + Inspector */
            <>
              <main className="flex-1 relative overflow-hidden">
                <ProjectMap project={selectedProject} isProcessingMode={viewMode === 'processing'} selectedImageId={selectedImageId} onSelectImage={(id) => setSelectedImageId(id)} />
              </main>
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

      {/* Group Create/Edit Modal */}
      {(isGroupModalOpen || editingGroup) && (
        <div className="fixed inset-0 z-[1000] flex items-center justify-center bg-black/60 backdrop-blur-sm animate-in fade-in duration-200" onClick={() => { setIsGroupModalOpen(false); setEditingGroup(null); }}>
          <div className="bg-white rounded-xl shadow-2xl w-[400px] overflow-hidden" onClick={e => e.stopPropagation()}>
            <div className="h-14 border-b border-slate-200 bg-slate-50 flex items-center justify-between px-6">
              <h3 className="font-bold text-slate-800 flex items-center gap-2">
                <Folder size={20} className="text-blue-600" />
                {editingGroup ? '폴더 수정' : '새 폴더 만들기'}
              </h3>
              <button onClick={() => { setIsGroupModalOpen(false); setEditingGroup(null); }}><X size={20} className="text-slate-400 hover:text-slate-600" /></button>
            </div>
            <form onSubmit={async (e) => {
              e.preventDefault();
              const formData = new FormData(e.target);
              const name = formData.get('name');
              const color = formData.get('color');
              try {
                if (editingGroup) {
                  await handleUpdateGroup(editingGroup.id, { name, color });
                } else {
                  await handleCreateGroup(name, color);
                }
                setIsGroupModalOpen(false);
                setEditingGroup(null);
              } catch (err) {
                alert('실패: ' + err.message);
              }
            }} className="p-6 space-y-4">
              <div className="space-y-2">
                <label className="text-sm font-medium text-slate-700">폴더 이름</label>
                <input type="text" name="name" defaultValue={editingGroup?.name || ''} className="w-full border border-slate-200 p-3 rounded-lg text-sm" placeholder="예: 경기권역 2026" required autoFocus />
              </div>
              <div className="space-y-2">
                <label className="text-sm font-medium text-slate-700">색상</label>
                <div className="flex gap-2">
                  {['#3b82f6', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6', '#94a3b8'].map(c => (
                    <label key={c} className="cursor-pointer">
                      <input type="radio" name="color" value={c} defaultChecked={editingGroup?.color === c || (!editingGroup && c === '#3b82f6')} className="sr-only peer" />
                      <div className="w-8 h-8 rounded-full peer-checked:ring-2 peer-checked:ring-offset-2 peer-checked:ring-blue-500" style={{ backgroundColor: c }} />
                    </label>
                  ))}
                </div>
              </div>
              <div className="flex gap-3 pt-4">
                <button type="button" onClick={() => { setIsGroupModalOpen(false); setEditingGroup(null); }} className="flex-1 py-2.5 border border-slate-200 rounded-lg text-sm font-medium hover:bg-slate-50">취소</button>
                <button type="submit" className="flex-1 py-2.5 bg-blue-600 hover:bg-blue-700 text-white rounded-lg text-sm font-bold">{editingGroup ? '수정' : '만들기'}</button>
              </div>
            </form>
          </div>
        </div>
      )}
      {/* Upload Progress Overlay - 멀티 프로젝트 업로드 지원 */}
      {/* 대시보드: 모든 프로젝트 업로드 표시 / 처리 화면: 현재 프로젝트만 표시 */}
      {allUploads.length > 0 && (
        <UploadProgressPanel
          uploads={viewMode === 'processing' ? currentProjectUploads : allUploads}
          onAbortAll={() => {
            if (window.confirm('모든 업로드를 취소하시겠습니까?')) {
              // 모든 컨트롤러 중단
              Object.values(uploaderControllers).forEach(ctrl => ctrl?.abortAll());
              setUploaderControllers({});
              setUploadsByProject({});
            }
          }}
          onRestore={() => {
            // 업로드가 완료된 경우에만 패널 닫기 허용
            if (hasAnyActiveUploads) {
              if (window.confirm('업로드가 진행 중입니다. 패널을 닫으면 업로드가 취소됩니다.\n\n계속하시겠습니까?')) {
                Object.values(uploaderControllers).forEach(ctrl => ctrl?.abortAll());
                setUploaderControllers({});
                setUploadsByProject({});
              }
            } else {
              setUploaderControllers({});
              setUploadsByProject({});
            }
          }}
        />
      )}
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
