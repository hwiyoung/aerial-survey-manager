import { useState, useEffect, useMemo, useRef } from 'react';
import { Settings, ArrowLeft, Loader2, X, CheckCircle2, AlertTriangle, Save, Trash2, Play, Camera, RotateCcw, MapPinned } from 'lucide-react';
import api from '../../api/client';
import { useProcessingProgress } from '../../hooks/useProcessingProgress';
import CrsCorrectionModal from './CrsCorrectionModal';
import { formatCrsLabel } from '../../constants/crs';

const ACTIVE_UPLOAD_STATUSES = new Set(['waiting', 'uploading', 'validating']);
const CRS_CORRECTION_LOCKED_STATUSES = new Set(['closed', 'applying', 'applied']);

function normalizeRestartChoiceData(data) {
    if (!data) return null;
    return {
        type: 'restart_choice_required',
        message: data.message || '이전 처리 작업이 완료되지 않았습니다. 처리 방식을 선택해주세요.',
        job_id: data.job_id || data.id || null,
        job_status: data.job_status || data.status,
        can_resume: Boolean(data.can_resume),
        completed_steps: data.completed_steps || [],
        failed_step: data.failed_step || null,
        next_step: data.next_step || null,
    };
}

function getProcessingEngineLabel(engineName) {
    const normalized = String(engineName || '').trim().toLowerCase();
    if (normalized === 'metashape') return 'GPU 처리 엔진';
    return String(engineName || '처리 엔진');
}

export default function ProcessingSidebar({
    width,
    project,
    onCancel,
    onStartProcessing,
    onComplete,
    onCancelled,
    activeUploads = [],
    uploadEvents = [],
    onProcessingEventsChange = null,
    onEoPointsChanged = null,
    availableEngines = [],
    defaultEngine = 'metashape',
}) {
    const [isStarting, setIsStarting] = useState(false);
    const startInFlightRef = useRef(false);
    const [startError, setStartError] = useState('');
    const [presets, setPresets] = useState([]);
    const [defaultPresets, setDefaultPresets] = useState([]);
    const [selectedPresetId, setSelectedPresetId] = useState(null);
    const [loadingPresets, setLoadingPresets] = useState(true);
    const [isSaveModalOpen, setIsSaveModalOpen] = useState(false);
    const [newPresetName, setNewPresetName] = useState('');
    const [newPresetDesc, setNewPresetDesc] = useState('');
    const [isCrsCorrectionModalOpen, setIsCrsCorrectionModalOpen] = useState(false);
    const [selectedCrsCorrection, setSelectedCrsCorrection] = useState('EPSG:5186');
    const [currentSourceCrs, setCurrentSourceCrs] = useState(null);
    const [crsCorrection, setCrsCorrection] = useState({
        sourceCrs: null,
        status: null,
        requestedAt: null,
        appliedAt: null,
        eoDisplaySourceCrs: null,
        eoDisplayUpdatedCount: null,
        error: null,
    });
    const [isSavingCrsCorrection, setIsSavingCrsCorrection] = useState(false);
    const [crsCorrectionError, setCrsCorrectionError] = useState('');

    const processingEngines = useMemo(() => {
        if (!Array.isArray(availableEngines)) return [{ name: 'metashape', enabled: true, reason: '기본 엔진' }];

        const normalized = availableEngines
            .map((engine) => ({
                name: String(engine?.name || '').trim(),
                enabled: Boolean(engine?.enabled),
                reason: engine?.reason ? String(engine.reason) : '',
            }))
            .filter((engine) => engine.name);

        return normalized.length > 0 ? normalized : [{ name: 'metashape', enabled: true, reason: '기본 엔진' }];
    }, [availableEngines]);

    const enabledEngines = useMemo(() => processingEngines.filter((engine) => engine.enabled), [processingEngines]);
    const defaultAvailableEngine = useMemo(() => {
        const normalizedDefault = String(defaultEngine || '').trim();
        const matched = enabledEngines.find((engine) => engine.name === normalizedDefault);
        if (matched) return matched.name;
        if (enabledEngines.length > 0) return enabledEngines[0].name;
        if (processingEngines.length > 0) return processingEngines[0].name;
        return 'metashape';
    }, [defaultEngine, enabledEngines, processingEngines]);

    // Processing options state
    const [options, setOptions] = useState({
        engine: defaultAvailableEngine || 'metashape',
        gsd: 5.0,
        output_crs: 'EPSG:5186',
        process_mode: 'Normal',
        build_point_cloud: false
    });

    // UI states
    const [isCompletionModalOpen, setIsCompletionModalOpen] = useState(false);
    const [hasTriggeredComplete, setHasTriggeredComplete] = useState(false); // 완료 처리 중복 방지
    const [hasTriggeredCancel, setHasTriggeredCancel] = useState(false);
    const [restartChoiceData, setRestartChoiceData] = useState(null);
    const [restartChoiceDismissedJobId, setRestartChoiceDismissedJobId] = useState(null);

    // Real-time processing progress via WebSocket
    const { progress: wsProgress, status: wsStatus, message: wsMessage, reconnect } = useProcessingProgress(
        project?.id || null  // Use project.id for WebSocket connection
    );
    const [processingEvents, setProcessingEvents] = useState([]);
    const visibleEvents = useMemo(() => {
        const normalized = [...(uploadEvents || []), ...(processingEvents || [])]
            .map((event, index) => ({
                id: event.id || `${event.timestamp || 'event'}-${index}`,
                timestamp: event.timestamp || new Date().toISOString(),
                level: event.level || 'info',
                message: event.message || '',
            }))
            .filter((event) => event.message);
        return normalized.sort((a, b) => new Date(a.timestamp) - new Date(b.timestamp));
    }, [uploadEvents, processingEvents]);
    const alertEvents = useMemo(
        () => visibleEvents.filter((e) => {
            const lv = String(e.level || '').toLowerCase();
            return lv === 'error' || lv === 'warning' || lv === 'warn';
        }),
        [visibleEvents],
    );
    const normalizedProjectStatus = (project?.status || '').toLowerCase();
    const isProjectCompleted = normalizedProjectStatus === 'completed' || project?.status === '완료';
    const isProjectProcessing = (
        normalizedProjectStatus === 'processing' ||
        normalizedProjectStatus === 'queued' ||
        normalizedProjectStatus === 'running' ||
        project?.status === '진행중' ||
        // '대기'(pending/queued)는 WS가 처리 상태를 확인한 경우에만 처리 중으로 판정
        // (기존: wsStatus !== 'connecting' → WS 끊김 시 오판 발생)
        (project?.status === '대기' && (wsStatus === 'processing' || wsStatus === 'queued'))
    );
    const isCancelled = (!isStarting && (normalizedProjectStatus === 'cancelled' || project?.status === '취소' || wsStatus === 'cancelled')) || hasTriggeredCancel;
    const isComplete = isProjectCompleted || wsStatus === 'complete' || wsStatus === 'completed';
    const isProcessing = !isComplete && !isCancelled && (wsStatus === 'processing' || wsStatus === 'queued' || (wsStatus === 'connecting' && isProjectProcessing) || isProjectProcessing || isStarting);
    const processingImageCount = project?.processingImageCount
        ?? project?.processing_image_count
        ?? project?.upload_completed_count
        ?? project?.imageCount
        ?? 0;
    const fallbackProgress = (wsStatus === 'connecting' && (isProjectProcessing || isStarting))
        ? (project?.progress ?? 0)
        : (isComplete ? 100 : wsProgress);
    const normalizedWsMessage = String(wsMessage || '');
    const displayWsMessage = /^좌표계 변경 예약/.test(normalizedWsMessage)
        ? ''
        : normalizedWsMessage;
    const fallbackMessage =
        displayWsMessage ||
        (isStarting ? '처리 시작 중...' : (wsStatus === 'queued' ? '대기 중...' : (wsStatus === 'processing' ? '처리 진행 중...' : (wsStatus === 'connecting' ? '연결 중...' : ''))));
    const hasPendingCrsCorrection = crsCorrection.status === 'pending' && Boolean(crsCorrection.sourceCrs);
    const isCrsCorrectionLocked = CRS_CORRECTION_LOCKED_STATUSES.has(crsCorrection.status);
    const canEditCrsCorrection = isProcessing && !isCrsCorrectionLocked;
    const crsCorrectionButtonLabel = hasPendingCrsCorrection ? '좌표계 변경/취소' : '좌표계 변경';
    const crsCorrectionStatusLabel = (() => {
        const eoDisplaySourceCrs = crsCorrection.eoDisplaySourceCrs || crsCorrection.sourceCrs;
        const eoDisplayText = eoDisplaySourceCrs ? ` · 지도 EO 위치도 ${formatCrsLabel(eoDisplaySourceCrs)} 기준으로 맞춰졌습니다` : '';
        if (crsCorrection.status === 'pending' && crsCorrection.sourceCrs) return `좌표계 변경 예약됨: ${formatCrsLabel(crsCorrection.sourceCrs)}${eoDisplayText}`;
        if (crsCorrection.status === 'applying' && crsCorrection.sourceCrs) return `좌표계 변경 적용 중: ${formatCrsLabel(crsCorrection.sourceCrs)}${eoDisplayText}`;
        if (crsCorrection.status === 'applied' && crsCorrection.sourceCrs) return `좌표계 변경 완료: ${formatCrsLabel(crsCorrection.sourceCrs)}${eoDisplayText}`;
        if (crsCorrection.status === 'closed') return '좌표계를 바꿀 수 있는 단계가 지났습니다.';
        if (crsCorrection.status === 'failed') return `좌표계 변경 실패${crsCorrection.error ? `: ${crsCorrection.error}` : ''}`;
        return '';
    })();
    const restartCompletedSteps = useMemo(() => {
        if (!Array.isArray(restartChoiceData?.completed_steps)) return [];
        return restartChoiceData.completed_steps
            .map(step => step?.label || step?.script)
            .filter(Boolean);
    }, [restartChoiceData]);
    const restartFailedStepLabel = restartChoiceData?.failed_step?.label || restartChoiceData?.next_step?.label || '';

    useEffect(() => {
        if (!project?.id) {
            setProcessingEvents([]);
            return;
        }

        let cancelled = false;
        const loadProcessingEvents = async () => {
            try {
                const data = await api.getProcessingStatus(project.id);
                if (!cancelled) {
                    const events = data.processing_events || [];
                    setProcessingEvents(events);
                    onProcessingEventsChange?.(project.id, events);
                    setCrsCorrection({
                        sourceCrs: data.crs_correction_source_crs || null,
                        status: data.crs_correction_status || null,
                        requestedAt: data.crs_correction_requested_at || null,
                        appliedAt: data.crs_correction_applied_at || null,
                        eoDisplaySourceCrs: data.eo_display_source_crs || null,
                        eoDisplayUpdatedCount: data.eo_display_updated_count || null,
                        error: data.crs_correction_error || null,
                    });
                    setCurrentSourceCrs(data.current_source_crs || null);

                    const restartJobId = data.id || data.job_id;
                    if (
                        data.restart_choice_required &&
                        selectedPresetId &&
                        !restartChoiceData &&
                        restartChoiceDismissedJobId !== restartJobId &&
                        !startInFlightRef.current
                    ) {
                        setRestartChoiceData(normalizeRestartChoiceData(data));
                    }
                }
            } catch (_error) {
                if (!cancelled) setProcessingEvents([]);
            }
        };

        loadProcessingEvents();
        const timer = setInterval(loadProcessingEvents, isProcessing ? 4000 : 10000);
        return () => {
            cancelled = true;
            clearInterval(timer);
        };
    }, [project?.id, isProcessing, onProcessingEventsChange, restartChoiceData, restartChoiceDismissedJobId, selectedPresetId]);

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

    useEffect(() => {
        setOptions((prev) => {
            const isEngineValid = processingEngines.some((engine) => engine.name === prev.engine && engine.enabled);
            if (isEngineValid) return prev;
            return {
                ...prev,
                engine: defaultAvailableEngine || 'metashape',
            };
        });
    }, [defaultAvailableEngine, processingEngines]);

    const normalizedSelectedEngine = useMemo(() => {
        const selected = String(options.engine || '').trim();
        return selected || defaultAvailableEngine || 'metashape';
    }, [options.engine, defaultAvailableEngine]);

    const selectedEnginePolicy = useMemo(() => {
        return processingEngines.find((engine) => engine.name === normalizedSelectedEngine);
    }, [processingEngines, normalizedSelectedEngine]);

    const isSelectedEngineEnabled = Boolean(selectedEnginePolicy?.enabled);

    // Trigger refresh when processing complete (한 번만 실행)
    // onComplete는 모달에서 사용자가 선택할 때만 호출 (깜빡거림 방지)
    useEffect(() => {
        if (isComplete && !hasTriggeredComplete) {
            setHasTriggeredComplete(true);
            setIsCompletionModalOpen(true);
            // onComplete는 여기서 호출하지 않음 - 모달 버튼에서 호출
        }
    }, [isComplete, hasTriggeredComplete]);

    // 프로젝트가 변경되면 완료 플래그 리셋
    useEffect(() => {
        setHasTriggeredComplete(false);
        setHasTriggeredCancel(false);
        setStartError('');
        setRestartChoiceData(null);
        setRestartChoiceDismissedJobId(null);
        setIsCrsCorrectionModalOpen(false);
        setSelectedCrsCorrection('EPSG:5186');
        setCrsCorrection({
            sourceCrs: null,
            status: null,
            requestedAt: null,
            appliedAt: null,
            eoDisplaySourceCrs: null,
            eoDisplayUpdatedCount: null,
            error: null,
        });
        setCrsCorrectionError('');
    }, [project?.id]);

    useEffect(() => {
        if (isCancelled) {
            setIsStarting(false);
        }
    }, [isCancelled]);

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
        setStartError('');
        setSelectedPresetId(presetId);
        if (!presetId) return;

        const allPresets = [...presets, ...defaultPresets];
        const preset = allPresets.find(p => p.id === presetId);
        if (preset?.options) {
            const candidateEngine = preset.options.engine || normalizedSelectedEngine || defaultAvailableEngine;
            const isEngineEnabled = processingEngines.some((engine) => engine.name === candidateEngine && engine.enabled);

            setOptions((prevOptions) => ({
                ...prevOptions,
                engine: isEngineEnabled ? candidateEngine : defaultAvailableEngine || 'metashape',
                gsd: preset.options.gsd || 5.0,
                output_crs: preset.options.output_crs || 'EPSG:5186',
                process_mode: preset.options.process_mode || 'Normal',
                build_point_cloud: preset.options.build_point_cloud || false
            }));
        }
    };

    // Auto-select default preset (user default first, then system default)
    useEffect(() => {
        if (loadingPresets || selectedPresetId) return;
        const userDefault = presets.find(p => p.is_default);
        const systemDefault = defaultPresets.find(p => p.is_default);
        const defaultPreset = userDefault || systemDefault;
        if (defaultPreset?.id) {
            setSelectedPresetId(defaultPreset.id);
            if (defaultPreset.options) {
                const candidateEngine = defaultPreset.options.engine || normalizedSelectedEngine || defaultAvailableEngine;
                const isEngineEnabled = processingEngines.some((engine) => engine.name === candidateEngine && engine.enabled);

                setOptions((prevOptions) => ({
                    ...prevOptions,
                    engine: isEngineEnabled ? candidateEngine : defaultAvailableEngine || 'metashape',
                    gsd: defaultPreset.options.gsd || 5.0,
                    output_crs: defaultPreset.options.output_crs || 'EPSG:5186',
                    process_mode: defaultPreset.options.process_mode || 'Normal',
                    build_point_cloud: defaultPreset.options.build_point_cloud || false
                }));
            }
        }
    }, [loadingPresets, selectedPresetId, presets, defaultPresets, normalizedSelectedEngine, defaultAvailableEngine, processingEngines]);

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
    const handleStart = async (forceRestart = false, resumeCheckpoint = undefined) => {
        if (forceRestart && typeof forceRestart === 'object') {
            forceRestart.preventDefault?.();
            forceRestart = false;
        }
        forceRestart = Boolean(forceRestart);

        if (startInFlightRef.current) {
            return;
        }
        startInFlightRef.current = true;
        setStartError('');
        if (!selectedPresetId) {
            setStartError('프리셋을 선택해 주세요.');
            startInFlightRef.current = false;
            return;
        }

        const hasEnabledEngine = processingEngines.some((engine) => engine.enabled);
        if (!hasEnabledEngine) {
            setStartError('사용 가능한 처리 엔진이 없습니다. 서버 설정을 확인해 주세요.');
            startInFlightRef.current = false;
            return;
        }

        if (!isSelectedEngineEnabled) {
            const fallbackEngine = enabledEngines[0]?.name;
            if (fallbackEngine && fallbackEngine !== normalizedSelectedEngine) {
                setOptions((prev) => ({ ...prev, engine: fallbackEngine }));
                setStartError(`현재 엔진(${getProcessingEngineLabel(normalizedSelectedEngine)})은 비활성입니다. ${getProcessingEngineLabel(fallbackEngine)}으로 자동 전환합니다.`);
            } else {
                setStartError('현재 엔진이 비활성입니다.');
            }
            startInFlightRef.current = false;
            return;
        }

        if (!forceRestart && resumeCheckpoint === undefined && project?.id) {
            try {
                const statusData = await api.getProcessingStatus(project.id);
                if (statusData?.restart_choice_required) {
                    setRestartChoiceDismissedJobId(null);
                    setRestartChoiceData(normalizeRestartChoiceData(statusData));
                    startInFlightRef.current = false;
                    return;
                }
            } catch (statusError) {
                console.warn('Failed to check restart choice before starting:', statusError);
            }
        }

        setHasTriggeredCancel(false);
        setIsStarting(true);
        const startOptions = resumeCheckpoint === undefined
            ? options
            : { ...options, resume_checkpoint: resumeCheckpoint };
        try {
            await onStartProcessing(startOptions, forceRestart);
            if (reconnect) reconnect();
        } catch (error) {
            console.error('Failed to start processing:', error);

            const errorData = error.data || error.response?.data?.detail || error.response?.data || {};
            if (errorData?.type === 'unsupported_engine') {
                const fallbackEngine = enabledEngines.find((engine) => errorData?.supported_engines?.includes(engine.name))?.name
                    || enabledEngines[0]?.name;
                if (fallbackEngine) {
                    setOptions((prev) => ({ ...prev, engine: fallbackEngine }));
                    setStartError(`요청한 엔진(${getProcessingEngineLabel(errorData.engine)})은 현재 정책에서 비활성입니다. ${getProcessingEngineLabel(fallbackEngine)}으로 자동 전환했습니다.`);
                } else {
                    setStartError(errorData.message || '요청한 처리 엔진이 현재 비활성입니다.');
                }

                setIsStarting(false);
                startInFlightRef.current = false;
                return;
            }

            if (errorData?.type === 'completed_job_restart_requires_explicit_action') {
                setIsStarting(false);
                startInFlightRef.current = false;
                const confirmRerun = window.confirm(
                    `${errorData.confirm_message || '완료된 프로젝트입니다.'}\n\n` +
                    `기존 결과는 유지하고, 업로드된 이미지와 EO를 다시 불러와 새 처리 작업을 시작하시겠습니까?`
                );
                if (confirmRerun) {
                    await handleStart(false);
                    return;
                }
                setStartError(errorData.message || '완료된 프로젝트의 자동 재시작 요청이 차단되었습니다.');
                return;
            }

            if (errorData?.type === 'restart_choice_required') {
                setIsStarting(false);
                startInFlightRef.current = false;
                setRestartChoiceDismissedJobId(null);
                setRestartChoiceData(normalizeRestartChoiceData(errorData));
                return;
            }

            // Handle job_already_running error with force restart option
            if (errorData?.type === 'job_already_running') {
                const confirmRestart = window.confirm(
                    `현재 진행 중인 처리 작업이 있습니다.\n\n` +
                    `상태: ${errorData.job_status === 'queued' ? '대기 중' : '처리 중'}\n` +
                    `진행률: ${errorData.progress || 0}%\n` +
                    `시작 시간: ${errorData.started_at ? new Date(errorData.started_at).toLocaleString() : '아직 시작되지 않음'}\n\n` +
                    `기존 작업을 중단하고 새로 시작하시겠습니까?`
                );
                if (confirmRestart) {
                    startInFlightRef.current = false;
                    setIsStarting(false);
                    await handleStart(true);
                    return;
                }
            }

            const message = errorData?.message || error.message || '처리 시작에 실패했습니다.';
            if (message) {
                setStartError(message);
            }
            setIsStarting(false);
        } finally {
            startInFlightRef.current = false;
        }
    };

    const dismissRestartChoice = () => {
        const jobId = restartChoiceData?.job_id || restartChoiceData?.id || null;
        if (jobId) {
            setRestartChoiceDismissedJobId(jobId);
        }
        setRestartChoiceData(null);
    };

    const handleRestartChoice = async (resumeCheckpoint) => {
        if (!restartChoiceData) return;
        if (resumeCheckpoint && !restartChoiceData.can_resume) return;

        setRestartChoiceData(null);
        setStartError('');
        await handleStart(true, resumeCheckpoint);
    };

    const openCrsCorrectionModal = () => {
        if (!canEditCrsCorrection) {
            alert('최종 결과 저장 단계에 들어간 뒤에는 좌표계를 바꿀 수 없습니다.');
            return;
        }
        setCrsCorrectionError('');
        setSelectedCrsCorrection(crsCorrection.sourceCrs || currentSourceCrs || 'EPSG:5186');
        setIsCrsCorrectionModalOpen(true);
    };

    const handleReserveCrsCorrection = async () => {
        if (!project?.id || !selectedCrsCorrection) return;

        const confirmed = window.confirm(
            'EO 파일에 기록된 원본 좌표가 실제로 사용하는 좌표계를 선택하세요.\n\n' +
            '최종 결과 저장 전까지 다시 바꾸거나 취소할 수 있습니다.\n\n' +
            `기존 처리 좌표계: ${formatCrsLabel(currentSourceCrs)}\n` +
            `선택한 좌표계: ${formatCrsLabel(selectedCrsCorrection)}\n\n` +
            '좌표계 변경을 예약하시겠습니까?'
        );
        if (!confirmed) return;

        setIsSavingCrsCorrection(true);
        setCrsCorrectionError('');
        try {
            const result = await api.reserveCrsCorrection(project.id, selectedCrsCorrection);
            setCrsCorrection({
                sourceCrs: result.source_crs || selectedCrsCorrection,
                status: result.status || 'pending',
                requestedAt: result.requested_at || new Date().toISOString(),
                appliedAt: result.applied_at || null,
                eoDisplaySourceCrs: result.eo_display_source_crs || result.source_crs || selectedCrsCorrection,
                eoDisplayUpdatedCount: result.eo_display_updated_count || null,
                error: result.error || null,
            });
            setCurrentSourceCrs(result.current_source_crs || currentSourceCrs || null);
            try {
                await onEoPointsChanged?.(project.id);
            } catch (refreshError) {
                console.error('Failed to refresh EO points after CRS correction reservation:', refreshError);
            }
            setIsCrsCorrectionModalOpen(false);
        } catch (error) {
            setCrsCorrectionError(error.data?.message || error.data?.detail?.message || error.message || '좌표계 변경 예약에 실패했습니다.');
        } finally {
            setIsSavingCrsCorrection(false);
        }
    };

    const handleCancelCrsCorrection = async () => {
        if (!project?.id) return;
        if (!window.confirm('좌표계 변경 예약을 취소하시겠습니까?')) return;

        setIsSavingCrsCorrection(true);
        setCrsCorrectionError('');
        try {
            const result = await api.cancelCrsCorrection(project.id);
            setCrsCorrection({
                sourceCrs: result.source_crs || null,
                status: result.status || 'cancelled',
                requestedAt: result.requested_at || crsCorrection.requestedAt || null,
                appliedAt: result.applied_at || null,
                eoDisplaySourceCrs: result.eo_display_source_crs || result.current_source_crs || null,
                eoDisplayUpdatedCount: result.eo_display_updated_count || null,
                error: result.error || null,
            });
            setCurrentSourceCrs(result.current_source_crs || currentSourceCrs || null);
            try {
                await onEoPointsChanged?.(project.id);
            } catch (refreshError) {
                console.error('Failed to refresh EO points after CRS correction cancellation:', refreshError);
            }
            setIsCrsCorrectionModalOpen(false);
        } catch (error) {
            setCrsCorrectionError(error.data?.message || error.data?.detail?.message || error.message || '좌표계 변경 예약 취소에 실패했습니다.');
        } finally {
            setIsSavingCrsCorrection(false);
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
            {isProcessing && (
                <div className="px-5 py-3 bg-blue-50 border-b border-blue-100">
                    <div className="flex justify-between items-center text-sm mb-2">
                        <span className="font-medium text-blue-800 flex items-center gap-2">
                            <Loader2 size={14} className="animate-spin" />
                            {wsStatus === 'connecting' ? '연결 중...' : '처리 진행 중'}
                        </span>
                        <span className="font-bold text-blue-600">{fallbackProgress}%</span>
                    </div>
                    <div className="h-2 bg-blue-100 rounded-full overflow-hidden">
                        <div
                            className="h-full bg-blue-600 transition-all duration-500 ease-out"
                            style={{ width: `${fallbackProgress}%` }}
                        />
                    </div>
                    {fallbackMessage && (
                        <p className="text-xs text-blue-600 mt-1 truncate font-medium">{fallbackMessage}</p>
                    )}
                    {crsCorrectionStatusLabel && (
                        <div className={`mt-2 flex items-center gap-1.5 rounded-md border px-2 py-1.5 text-[11px] font-semibold
                            ${crsCorrection.status === 'failed'
                                ? 'border-red-200 bg-red-50 text-red-700'
                                : 'border-amber-200 bg-amber-50 text-amber-700'}`}
                        >
                            <MapPinned size={13} />
                            <span className="min-w-0 truncate">{crsCorrectionStatusLabel}</span>
                        </div>
                    )}

                    {/* Stop / CRS correction buttons */}
                    {(wsStatus === 'processing' || wsStatus === 'queued') && (
                        <div className="mt-4 pt-4 border-t border-blue-100/50">
                            <div className="grid grid-cols-2 gap-2">
                                <button
                                    onClick={async () => {
                                        if (!window.confirm('정말 처리를 중단하시겠습니까?')) return;
                                        try {
                                            setHasTriggeredCancel(true);
                                            setIsStarting(false);
                                            setIsCompletionModalOpen(false);
                                            const cancelledJob = await api.cancelProcessing(project.id);
                                            if (onCancelled) {
                                                await onCancelled({
                                                    id: project.id,
                                                    progress: cancelledJob?.progress ?? project?.progress ?? 0,
                                                    completed_at: new Date().toISOString(),
                                                });
                                            }
                                        } catch (err) {
                                            setHasTriggeredCancel(false);
                                            alert('중단 실패: ' + err.message);
                                        }
                                    }}
                                    className="flex min-h-11 items-center justify-center gap-2 rounded-lg border border-red-200 bg-red-50 px-2 py-2.5 text-xs font-bold text-red-600 shadow-sm transition-all hover:bg-red-100"
                                >
                                    <X size={14} /> 처리 중단
                                </button>
                                <button
                                    type="button"
                                    onClick={openCrsCorrectionModal}
                                    disabled={!canEditCrsCorrection}
                                    title={canEditCrsCorrection ? crsCorrectionButtonLabel : '최종 결과 저장 단계에 들어간 뒤에는 좌표계를 바꿀 수 없습니다.'}
                                    className={`flex min-h-11 items-center justify-center gap-2 rounded-lg border px-2 py-2.5 text-xs font-bold shadow-sm transition-all
                                        ${canEditCrsCorrection
                                            ? 'border-amber-200 bg-amber-50 text-amber-700 hover:bg-amber-100'
                                            : 'cursor-not-allowed border-slate-200 bg-slate-100 text-slate-400'}`}
                                >
                                    <MapPinned size={14} /> {crsCorrectionButtonLabel}
                                </button>
                            </div>
                        </div>
                    )}
                </div>
            )}

            {/* Scheduled Status */}
            {normalizedProjectStatus === 'scheduled' && !isProcessing && !isComplete && (
                <div className="px-5 py-3 bg-amber-50 border-b border-amber-100 flex items-center gap-2 animate-in slide-in-from-top duration-300">
                    <Loader2 size={16} className="text-amber-600 animate-spin" />
                    <div>
                        <span className="text-sm font-bold text-amber-800 block">처리 예약됨</span>
                        <p className="text-[10px] text-amber-600">모든 이미지 업로드가 완료되면 자동으로 처리가 시작됩니다.</p>
                    </div>
                </div>
            )}

            {/* Complete Status */}
            {isComplete && (
                <div className="px-5 py-3 bg-emerald-50 border-b border-emerald-100 flex items-center gap-2 animate-in slide-in-from-top duration-300">
                    <CheckCircle2 size={16} className="text-emerald-600" />
                    <div>
                        <span className="text-sm font-bold text-emerald-800 block">처리가 완료되었습니다!</span>
                        <p className="text-[10px] text-emerald-600">결과물이 저장소에 성공적으로 업로드되었습니다.</p>
                    </div>
                </div>
            )}

            {isCancelled && (
                <div className="px-5 py-3 bg-amber-50 border-b border-amber-100 flex items-center gap-2 animate-in slide-in-from-top duration-300">
                    <AlertTriangle size={16} className="text-amber-600" />
                    <div>
                        <span className="text-sm font-bold text-amber-800 block">처리가 중단되었습니다.</span>
                        <p className="text-[10px] text-amber-600">필요 시 다시 처리 시작할 수 있습니다.</p>
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
                {/* 1. Input Data Info */}
                <div className="space-y-3">
                    <h4 className="text-sm font-bold text-slate-700 border-b pb-2 flex items-center gap-2">
                        1. 입력 데이터 정보
                    </h4>
                    <div className="grid grid-cols-2 gap-3 text-sm font-medium">
                        <div className="bg-slate-50 p-3 rounded-lg border border-slate-100">
                            <span className="text-slate-500 block text-[10px] uppercase tracking-wider mb-1">이미지 수</span>
                            <span className="text-slate-800 font-bold text-lg">{processingImageCount} <span className="text-sm font-normal text-slate-500">장</span></span>
                        </div>
                        <div className="bg-slate-50 p-3 rounded-lg border border-slate-100">
                            <span className="text-slate-500 block text-[10px] uppercase tracking-wider mb-1">EO 데이터</span>
                            {(() => {
                                const eoCount = project?.images?.filter(img => img.hasEo || img.exterior_orientation)?.length || 0;
                                return eoCount > 0
                                    ? <span className="text-emerald-600 font-bold text-lg">{eoCount} <span className="text-sm font-normal">건</span></span>
                                    : <span className="text-slate-400 font-bold">없음</span>;
                            })()}
                        </div>
                        {project?.area > 0 && (
                            <div className="bg-blue-50 p-3 rounded-lg border border-blue-100">
                                <span className="text-blue-500 block text-[10px] uppercase tracking-wider mb-1">촬영 면적</span>
                                <span className="text-blue-700 font-bold text-lg">{project.area.toFixed(2)} <span className="text-sm font-normal">km²</span></span>
                            </div>
                        )}
                        {project?.source_size > 0 && (
                            <div className="bg-slate-50 p-3 rounded-lg border border-slate-100">
                                <span className="text-slate-500 block text-[10px] uppercase tracking-wider mb-1">원본 용량</span>
                                <span className="text-slate-800 font-bold text-lg">{(project.source_size / (1024 * 1024 * 1024)).toFixed(2)} <span className="text-sm font-normal text-slate-500">GB</span></span>
                            </div>
                        )}
                    </div>
                    {(() => {
                        const cameraName = project?.images?.[0]?.camera_model?.name;
                        return cameraName ? (
                            <div className="flex items-center gap-2 text-xs text-slate-500 bg-slate-50 px-3 py-2 rounded-lg border border-slate-100">
                                <Camera size={13} className="text-slate-400" />
                                <span>카메라: <span className="font-semibold text-slate-700">{cameraName}</span></span>
                            </div>
                        ) : null;
                    })()}
                </div>

                {/* 2. 처리 설정 */}
                <div className="space-y-3">
                    <h4 className="text-sm font-bold text-slate-700 border-b pb-2 flex items-center gap-2">
                        2. 처리 설정
                    </h4>

                    {startError && (
                        <div className="px-2 py-1.5 text-xs text-red-700 bg-red-50 border border-red-200 rounded-md">
                            {startError}
                        </div>
                    )}

                    {/* Preset Selector */}
                    <div className="space-y-2">
                        <label className="text-xs text-slate-500 font-medium ml-1">프리셋 불러오기</label>
                        <div className="flex gap-2">
                            <select
                                className="flex-1 border border-slate-200 p-2.5 rounded-lg text-sm bg-white focus:ring-2 focus:ring-blue-500 outline-none transition-all shadow-sm"
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
                                    className="p-2.5 text-red-500 hover:bg-red-50 border border-red-100 rounded-lg transition-colors"
                                    title="프리셋 삭제"
                                >
                                    <Trash2 size={18} />
                                </button>
                            )}
                        </div>
                    </div>

                </div>

                {alertEvents.length > 0 && (
                    <div className="space-y-2">
                        <h4 className="text-sm font-bold text-slate-700 border-b pb-2 flex items-center gap-2">
                            <AlertTriangle size={14} className="text-amber-600" />
                            이미지 처리 알림
                        </h4>
                        <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 shadow-sm max-h-60 overflow-y-auto custom-scrollbar">
                            <div className="space-y-2 text-xs">
                                {alertEvents.slice(-20).map((event) => {
                                    const lv = String(event.level || '').toLowerCase();
                                    const tone = lv === 'error' ? 'text-red-700' : 'text-amber-700';
                                    // Backend emits UTC ISO; if timezone suffix is missing, treat as UTC.
                                    let time = '';
                                    if (event.timestamp) {
                                        const raw = String(event.timestamp);
                                        const hasTz = /[zZ]|[+-]\d{2}:?\d{2}$/.test(raw);
                                        const d = new Date(hasTz ? raw : raw + 'Z');
                                        time = d.toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
                                    }
                                    return (
                                        <div key={event.id} className="flex gap-2 items-start">
                                            <span className="text-slate-500 font-mono text-[10px] mt-0.5 whitespace-nowrap">{time}</span>
                                            <span className={tone}>{event.message}</span>
                                        </div>
                                    );
                                })}
                            </div>
                        </div>
                    </div>
                )}
            </div>
            <div className="p-5 border-t border-slate-200 bg-slate-50 flex gap-3">
                <button onClick={onCancel} className="flex-1 py-3 text-slate-600 font-bold text-sm hover:bg-slate-200 rounded-lg">이전</button>
                {(() => {
                    // 프론트엔드 상태 또는 백엔드 상태로 업로드 진행 여부 확인
                    const frontendUploading = activeUploads.some(u => ACTIVE_UPLOAD_STATUSES.has(u.status));
                    const backendUploading = project?.upload_in_progress ?? false;
                    const uploadsInProgress = frontendUploading || backendUploading;

                    const totalImages = project?.imageCount || project?.image_count || 0;
                    const uploadCompleted = project?.upload_completed_count ?? totalImages;
                    const hasImages = totalImages > 0 && uploadCompleted > 0;
                    const isProcessingNow = isProcessing;
                    const hasEnabledEngine = processingEngines.some((engine) => engine.enabled);
                    const isDisabled = !hasEnabledEngine || !hasImages || uploadsInProgress || isProcessingNow || !selectedPresetId || !isSelectedEngineEnabled;

                    let buttonText;
                    if (frontendUploading) buttonText = `업로드 중... (${activeUploads.filter(u => u.status === 'completed').length}/${activeUploads.length})`;
                    else if (backendUploading) buttonText = `업로드 중... (${uploadCompleted}/${totalImages})`;
                    else if (!hasImages) buttonText = '업로드된 이미지 없음';
                    else if (!hasEnabledEngine) buttonText = '사용 가능한 처리 엔진 없음';
                    else if (!isSelectedEngineEnabled) buttonText = `${getProcessingEngineLabel(normalizedSelectedEngine)} 사용 불가`;
                    else if (!selectedPresetId) buttonText = '프리셋 선택 필요';
                    else if (isProcessingNow) buttonText = '처리 중...';
                    else buttonText = `처리 시작 (${uploadCompleted}장)`;

                    return (
                        <button
                            onClick={() => handleStart()}
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

            {/* Restart Choice Modal */}
            {restartChoiceData && (
                <div
                    className="fixed inset-0 z-[10000] flex items-center justify-center bg-slate-950/45 px-4 backdrop-blur-sm"
                    onClick={dismissRestartChoice}
                >
                    <div
                        className="w-full max-w-lg overflow-hidden rounded-xl border border-slate-200 bg-white shadow-2xl"
                        onClick={(e) => e.stopPropagation()}
                    >
                        <div className="flex items-start gap-3 border-b border-slate-100 px-5 py-4">
                            <div className="mt-0.5 flex h-10 w-10 shrink-0 items-center justify-center rounded-lg border border-amber-100 bg-amber-50 text-amber-600">
                                <AlertTriangle size={20} />
                            </div>
                            <div className="min-w-0 flex-1">
                                <h3 className="text-base font-bold text-slate-900">처리 방식 선택</h3>
                                <p className="mt-1 text-sm leading-5 text-slate-600">
                                    {restartChoiceData.message || '이전 작업이 완료되지 않았습니다.'}
                                </p>
                            </div>
                            <button
                                type="button"
                                onClick={dismissRestartChoice}
                                className="rounded-md p-1.5 text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-700"
                                aria-label="닫기"
                            >
                                <X size={18} />
                            </button>
                        </div>

                        <div className="space-y-4 px-5 py-4">
                            <div className="rounded-md border border-slate-100 bg-slate-50 px-3 py-2 text-sm text-slate-700">
                                {restartFailedStepLabel ? (
                                    <>
                                        마지막 중단/오류 단계{' '}
                                        <span className="font-semibold text-slate-900">{restartFailedStepLabel}</span>
                                    </>
                                ) : (
                                    '마지막 중단/오류 단계 정보가 없습니다.'
                                )}
                            </div>

                            <div>
                                <div className="mb-2 flex items-center justify-between text-xs font-semibold text-slate-500">
                                    <span>재사용 가능한 완료 단계</span>
                                    <span>{restartCompletedSteps.length}개</span>
                                </div>
                                {restartCompletedSteps.length > 0 ? (
                                    <div className="max-h-32 overflow-y-auto rounded-md border border-slate-200 bg-white">
                                        {restartCompletedSteps.map((step, index) => (
                                            <div
                                                key={`${step}-${index}`}
                                                className="flex items-center gap-2 border-b border-slate-100 px-3 py-2 text-sm text-slate-700 last:border-b-0"
                                            >
                                                <CheckCircle2 size={14} className="shrink-0 text-emerald-500" />
                                                <span className="min-w-0 truncate">{step}</span>
                                            </div>
                                        ))}
                                    </div>
                                ) : (
                                    <div className="rounded-md border border-dashed border-slate-200 px-3 py-3 text-sm text-slate-500">
                                        완료된 checkpoint가 없습니다.
                                    </div>
                                )}
                            </div>

                            {!restartChoiceData.can_resume && (
                                <div className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs font-medium text-amber-700">
                                    이어서 처리할 완료 단계가 없어 처음부터 새로 처리해야 합니다.
                                </div>
                            )}
                        </div>

                        <div className="grid grid-cols-1 gap-2 border-t border-slate-100 bg-slate-50 px-5 py-4 sm:grid-cols-2">
                            <button
                                type="button"
                                onClick={() => handleRestartChoice(true)}
                                disabled={!restartChoiceData.can_resume || !selectedPresetId || isStarting}
                                className={`flex min-h-11 items-center justify-center gap-2 rounded-lg px-3 py-2 text-sm font-bold shadow-sm transition-colors
                                    ${restartChoiceData.can_resume && selectedPresetId && !isStarting
                                        ? 'border border-emerald-600 bg-emerald-600 text-white hover:bg-emerald-700'
                                        : 'cursor-not-allowed border border-slate-200 bg-slate-200 text-slate-400'}`}
                            >
                                <CheckCircle2 size={16} />
                                완료된 단계부터 이어서 처리
                            </button>
                            <button
                                type="button"
                                onClick={() => handleRestartChoice(false)}
                                disabled={!selectedPresetId || isStarting}
                                className={`flex min-h-11 items-center justify-center gap-2 rounded-lg border px-3 py-2 text-sm font-bold shadow-sm transition-colors
                                    ${selectedPresetId && !isStarting
                                        ? 'border-blue-600 bg-white text-blue-700 hover:bg-blue-50'
                                        : 'cursor-not-allowed border-slate-200 bg-slate-200 text-slate-400'}`}
                            >
                                <RotateCcw size={16} />
                                처음부터 새로 처리
                            </button>
                        </div>
                    </div>
                </div>
            )}

            <CrsCorrectionModal
                isOpen={isCrsCorrectionModalOpen}
                projectTitle={project?.title || ''}
                currentSourceCrs={currentSourceCrs}
                crsCorrection={crsCorrection}
                eoDisplaySourceCrs={crsCorrection.eoDisplaySourceCrs}
                selectedCrs={selectedCrsCorrection}
                onSelectedCrsChange={setSelectedCrsCorrection}
                onClose={() => setIsCrsCorrectionModalOpen(false)}
                onReserve={handleReserveCrsCorrection}
                onCancel={handleCancelCrsCorrection}
                isSaving={isSavingCrsCorrection}
                error={crsCorrectionError}
            />

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
                                    <span>모드: {options.process_mode}</span>
                                    <span>GSD: {options.gsd} cm</span>
                                    <span>좌표계: {options.output_crs}</span>
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
            {/* Completion Prompt Modal */}
            {isCompletionModalOpen && (
                <div className="fixed inset-0 z-[10000] flex items-center justify-center bg-black/40 backdrop-blur-sm">
                    <div className="bg-white rounded-2xl p-8 max-w-sm w-full shadow-2xl animate-in zoom-in-95 duration-200 text-center">
                        <div className="w-20 h-20 bg-emerald-100 text-emerald-600 rounded-full flex items-center justify-center mx-auto mb-6">
                            <CheckCircle2 size={48} />
                        </div>
                        <h3 className="text-2xl font-bold text-slate-800 mb-2">처리 완료!</h3>
                        <p className="text-slate-500 mb-8 leading-relaxed">
                            정사영상 생성이 성공적으로 완료되었습니다.<br />
                            대시보드로 돌아가 결과를 확인하시겠습니까?
                        </p>
                        <div className="flex flex-col gap-3">
                            <button
                                onClick={(e) => {
                                    e.stopPropagation();
                                    setIsCompletionModalOpen(false);
                                    if (onComplete) onComplete(); // 대시보드 이동 시 데이터 갱신
                                    onCancel(); // Use existing onCancel to go back to main page
                                }}
                                className="w-full py-4 bg-blue-600 text-white rounded-xl font-bold text-lg hover:bg-blue-700 shadow-lg shadow-blue-200 transition-all active:scale-95"
                            >
                                대시보드로 이동
                            </button>
                            <button
                                onClick={(e) => {
                                    e.stopPropagation();
                                    e.preventDefault();
                                    console.log('나중에 확인 클릭됨'); // 디버그용
                                    setIsCompletionModalOpen(false);
                                    // 현재 화면 유지 - 데이터 갱신만 수행
                                    if (onComplete) onComplete();
                                }}
                                className="w-full py-3 text-slate-500 font-medium hover:text-slate-700 hover:bg-slate-100 rounded-lg transition-colors cursor-pointer"
                            >
                                나중에 확인 (현재 화면 유지)
                            </button>
                        </div>
                    </div>
                </div>
            )}
        </aside>
    );
}
