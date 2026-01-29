import React, { useMemo, useState, useRef, useEffect, useCallback } from 'react';
import { MapPin, FolderCheck, HardDrive, Camera, BarChart3, LayoutGrid, LayoutList, LayoutTemplate, ArrowLeft, GripHorizontal, Eye } from 'lucide-react';
import { StatsCard } from './StatsCard';
import { TrendLineChart, DistributionPieChart, ProgressDonutChart, MonthlyBarChart } from './Charts';
import { FootprintMap } from './FootprintMap';
import { api } from '../../api/client';

// Month names for chart display
const MONTH_NAMES = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];


/**
 * Enhanced Stats Card for dashboard - larger with more details
 */
function DashboardStatsCard({ icon, value, unit, label, subLabel, progress, progressLabel, children }) {
    return (
        <div className="bg-white rounded-xl p-4 shadow-sm border border-slate-100">
            <div className="flex items-start gap-3">
                {icon && (
                    <div className="p-2 bg-slate-50 rounded-lg text-slate-500">
                        {icon}
                    </div>
                )}
                <div className="flex-1 min-w-0">
                    <p className="text-xs text-slate-500 mb-1">{label}</p>
                    <div className="flex items-baseline gap-1">
                        <span className="text-2xl font-bold text-slate-800">{value}</span>
                        {unit && <span className="text-sm text-slate-500">{unit}</span>}
                    </div>
                    {subLabel && <p className="text-xs text-slate-400 mt-1">{subLabel}</p>}
                </div>
            </div>

            {/* Progress bar if provided */}
            {progress !== undefined && (
                <div className="mt-3 pt-3 border-t border-slate-100">
                    <div className="h-1.5 bg-slate-100 rounded-full overflow-hidden">
                        <div
                            className="h-full bg-blue-500 rounded-full transition-all"
                            style={{ width: `${Math.min(100, progress)}%` }}
                        />
                    </div>
                    {progressLabel && (
                        <p className="text-xs text-slate-400 mt-1.5">{progressLabel}</p>
                    )}
                </div>
            )}

            {/* Additional content like badges */}
            {children}
        </div>
    );
}

/**
 * Stats summary section with 4 key metrics
 */
function StatsSummary({ stats, isCompact = false }) {
    const completedCount = stats.completed;
    const totalCount = stats.total || (stats.completed + stats.processing);
    const progressPercent = totalCount > 0 ? Math.round((completedCount / totalCount) * 100) : 0;

    return (
        <div className="bg-white rounded-xl p-5 shadow-sm border border-slate-100">
            <div className="flex items-center gap-2 mb-4">
                <BarChart3 size={18} className="text-blue-600" />
                <h3 className="text-sm font-bold text-slate-700">전체 처리 통계 현황</h3>
            </div>

            <div className={`grid gap-4 ${isCompact ? 'grid-cols-2' : 'grid-cols-4'}`}>
                {/* 처리 완료 면적 */}
                <DashboardStatsCard
                    icon={<MapPin size={18} />}
                    value={stats.area || '0'}
                    unit="km²"
                    label="처리 완료 면적"
                    progress={parseFloat(stats.area) > 0 ? Math.min(100, (parseFloat(stats.area) / 1003.2 * 100)) : 0}
                    progressLabel={`전체 국토 면적 대비 ${parseFloat(stats.area) > 0 ? (parseFloat(stats.area) / 1003.2 * 100).toFixed(2) : 0}%`}
                />

                {/* 프로젝트 진행 */}
                <DashboardStatsCard
                    icon={<FolderCheck size={18} />}
                    value={completedCount}
                    unit={`/ ${totalCount} 건`}
                    label="프로젝트 진행"
                >
                    <div className="flex gap-2 mt-3 pt-3 border-t border-slate-100">
                        <span className="px-2 py-0.5 text-xs font-medium bg-emerald-100 text-emerald-700 rounded">완료 {completedCount}</span>
                        <span className="px-2 py-0.5 text-xs font-medium bg-blue-100 text-blue-700 rounded">진행 {stats.processing}</span>
                    </div>
                </DashboardStatsCard>

                {/* 총 데이터 용량 */}
                <DashboardStatsCard
                    icon={<HardDrive size={18} />}
                    value={stats.dataSize || '51.7'}
                    unit="GB"
                    label="총 데이터 용량"
                    subLabel="정사영상 결과물 기준"
                />

                {/* 총 원본 사진 */}
                <DashboardStatsCard
                    icon={<Camera size={18} />}
                    value={stats.photoCount?.toLocaleString() || '7,305'}
                    unit="장"
                    label="총 원본 사진"
                    subLabel={`평균 ${stats.avgPhotos || 292}장 / 블록`}
                />
            </div>
        </div>
    );
}

/**
 * Layout toggle button component - allows user to set default layout preference
 */
function LayoutToggle({ layout, onToggle }) {
    return (
        <div className="flex items-center gap-0.5 bg-white rounded-lg p-0.5 shadow-sm border border-slate-200">
            <button
                onClick={() => onToggle('wide')}
                className={`p-1.5 rounded transition-colors ${layout === 'wide' ? 'bg-blue-100 text-blue-600' : 'text-slate-400 hover:text-slate-600 hover:bg-slate-50'}`}
                title="가로 레이아웃 (Wide)"
            >
                <LayoutGrid size={16} />
            </button>
            <button
                onClick={() => onToggle('narrow')}
                className={`p-1.5 rounded transition-colors ${layout === 'narrow' ? 'bg-blue-100 text-blue-600' : 'text-slate-400 hover:text-slate-600 hover:bg-slate-50'}`}
                title="세로 레이아웃 (Narrow)"
            >
                <LayoutList size={16} />
            </button>
            <button
                onClick={() => onToggle('auto')}
                className={`p-1.5 rounded transition-colors ${layout === 'auto' ? 'bg-blue-100 text-blue-600' : 'text-slate-400 hover:text-slate-600 hover:bg-slate-50'}`}
                title="자동 레이아웃"
            >
                <LayoutTemplate size={16} />
            </button>
        </div>
    );
}

/**
 * Project Detail View - shows when a project is selected via single click
 * Replaces the statistics section with project-specific information
 */
function ProjectDetailView({ project, onBack }) {
    if (!project) return null;

    const statusColor = {
        '완료': 'bg-emerald-100 text-emerald-700',
        '진행중': 'bg-blue-100 text-blue-700',
        '대기': 'bg-slate-100 text-slate-600',
        '오류': 'bg-red-100 text-red-700'
    }[project.status] || 'bg-slate-100 text-slate-600';

    return (
        <div className="bg-white rounded-xl p-5 shadow-sm border border-slate-100">
            <div className="flex items-center justify-between mb-4">
                <div className="flex items-center gap-3">
                    {onBack && (
                        <button
                            onClick={onBack}
                            className="p-1.5 rounded-lg hover:bg-slate-100 transition-colors text-slate-500 hover:text-slate-700"
                            title="통계 화면으로 돌아가기"
                        >
                            <ArrowLeft size={20} />
                        </button>
                    )}
                    <div>
                        <div className="flex items-center gap-2 mb-0.5">
                            <h3 className="text-lg font-bold text-slate-800">{project.title}</h3>
                            <span className="text-[10px] px-1.5 py-0.5 bg-slate-100 text-slate-500 rounded font-mono uppercase tracking-tighter">ID: {project.id?.slice(0, 8)}...</span>
                        </div>
                        <p className="text-sm text-slate-500">{project.region} · {project.company}</p>
                    </div>
                </div>
                <div className="flex flex-col items-end gap-2">
                    <span className={`px-3 py-1 text-sm font-medium rounded-full ${statusColor}`}>
                        {project.status}
                    </span>
                    {(project.status === '완료' || project.status === 'completed') && (
                        <span className="px-2 py-0.5 text-[10px] font-bold bg-emerald-500 text-white rounded shadow-sm flex items-center gap-1 animate-pulse">
                            <Eye size={10} /> 정사영상 사용 가능
                        </span>
                    )}
                </div>
            </div>

            <div className="grid grid-cols-2 gap-4">
                <DashboardStatsCard
                    icon={<Camera size={18} />}
                    value={project.imageCount?.toLocaleString() || project.image_count?.toLocaleString() || '0'}
                    unit="장"
                    label="원본 사진"
                />
                <DashboardStatsCard
                    icon={<MapPin size={18} />}
                    value={project.area?.toFixed(2) || '0'}
                    unit="km²"
                    label="촬영 면적"
                />
                <DashboardStatsCard
                    icon={<HardDrive size={18} />}
                    value={project.ortho_size ? (project.ortho_size / (1024 * 1024)).toFixed(1) : (project.source_size ? (project.source_size / (1024 * 1024 * 1024)).toFixed(2) : '0')}
                    unit={project.ortho_size ? "MB" : "GB"}
                    label={project.ortho_size ? "정사영상 용량" : "원본 총 용량"}
                />
                <DashboardStatsCard
                    icon={<FolderCheck size={18} />}
                    value={project.created_at ? new Date(project.created_at).toLocaleDateString() : '-'}
                    label="생성일"
                />
            </div>

            {/* Additional info if available */}
            {project.description && (
                <div className="mt-4 pt-4 border-t border-slate-100">
                    <p className="text-sm text-slate-600">{project.description}</p>
                </div>
            )}
        </div>
    );
}

/**
 * Main Dashboard View Component
 * Displays footprint map, statistics, and charts
 * When a project is selected, shows project details instead of statistics
 * Layout can be forced to wide/narrow or auto-adapt based on container width
 */
export default function DashboardView({
    projects = [],
    selectedProject = null,
    sidebarWidth = 320,
    onProjectClick,
    onDeselectProject,
    highlightProjectId = null,
    onHighlightEnd = null,
    showInspector = false,
    renderInspector = null,
    regionFilter = 'ALL',
    onRegionClick
}) {
    const containerRef = useRef(null);
    const [containerWidth, setContainerWidth] = useState(800);
    const [layoutMode, setLayoutMode] = useState('auto'); // 'wide', 'narrow', or 'auto'

    // Map height for narrow layout (draggable)
    const [mapHeight, setMapHeight] = useState(350);
    const isDragging = useRef(false);
    const startY = useRef(0);
    const startHeight = useRef(350);

    // Statistics data from API
    const [monthlyData, setMonthlyData] = useState([]);
    const [regionalData, setRegionalData] = useState([]);
    const [statsLoading, setStatsLoading] = useState(true);

    // Fetch statistics data from API
    useEffect(() => {
        const fetchStats = async () => {
            setStatsLoading(true);
            try {
                const [monthlyRes, regionalRes] = await Promise.all([
                    api.getMonthlyStats(),
                    api.getRegionalStats()
                ]);

                // Transform monthly data for charts
                const transformedMonthly = monthlyRes.data.map(item => ({
                    name: MONTH_NAMES[item.month - 1],
                    value: item.count,
                    completed: item.completed,
                    processing: item.processing
                }));
                setMonthlyData(transformedMonthly);

                // Transform regional data for charts
                const transformedRegional = regionalRes.data.map(item => ({
                    name: item.region,
                    value: item.percentage
                }));
                setRegionalData(transformedRegional);
            } catch (error) {
                console.error('Failed to fetch statistics:', error);
                // Use empty data on error
                setMonthlyData([]);
                setRegionalData([]);
            } finally {
                setStatsLoading(false);
            }
        };

        fetchStats();
    }, [projects.length, projects.map(p => p.status).join(',')]); // Refetch when projects count or status changes

    // Observe container width changes
    useEffect(() => {
        if (!containerRef.current) return;

        const resizeObserver = new ResizeObserver((entries) => {
            for (const entry of entries) {
                setContainerWidth(entry.contentRect.width);
            }
        });

        resizeObserver.observe(containerRef.current);
        return () => resizeObserver.disconnect();
    }, []);

    // Handle highlight timeout
    useEffect(() => {
        if (highlightProjectId && onHighlightEnd) {
            const timer = setTimeout(() => {
                onHighlightEnd();
            }, 2000); // 2 seconds (~3-4 blinks)
            return () => clearTimeout(timer);
        }
    }, [highlightProjectId, onHighlightEnd]);

    // Determine layout based on user preference or auto-detect
    // When in auto mode, prioritize sidebarWidth (if provided) over containerWidth
    const isWideLayout = useMemo(() => {
        if (layoutMode === 'wide') return true;
        if (layoutMode === 'narrow') return false;
        // Auto mode: if sidebar is wide, use narrow layout for main content
        // Sidebar > 450px means less space for content => narrow layout
        if (sidebarWidth > 450) return false;
        return containerWidth > 700; // Lowered threshold for better responsiveness
    }, [layoutMode, containerWidth, sidebarWidth]);

    // Calculate stats from projects (use real values, no fallbacks)
    const stats = useMemo(() => {
        // Count by status - handle various status names
        const processing = projects.filter(p =>
            p.status === '진행중' || p.status === 'processing' || p.status === 'running'
        ).length;
        const completed = projects.filter(p =>
            p.status === '완료' || p.status === 'completed'
        ).length;
        const pending = projects.filter(p =>
            p.status === '대기' || p.status === 'pending' || p.status === '준비'
        ).length;
        const failed = projects.filter(p =>
            p.status === '오류' || p.status === 'error' || p.status === 'failed'
        ).length;

        // Total is ALL projects, not just processing + completed
        const total = projects.length;

        const totalImages = projects.reduce((sum, p) => sum + (p.imageCount || p.image_count || 0), 0);
        // dataSize is based on ortho_size (MB to GB conversion)
        const totalSizeMB = projects.reduce((sum, p) => sum + (p.ortho_size ? p.ortho_size / (1024 * 1024) : 0), 0);
        const dataSize = (totalSizeMB / 1024).toFixed(1);

        // Area calculation based on actual projects
        const area = projects.reduce((sum, p) => sum + (p.area || 0), 0).toFixed(1);

        return {
            processing,
            completed,
            pending,
            failed,
            total,
            area: area || '0',
            dataSize: dataSize !== '0.0' ? dataSize : '0',
            photoCount: totalImages,
            avgPhotos: total > 0 ? Math.round(totalImages / total) : 0,
        };
    }, [projects]);

    return (
        <div ref={containerRef} className="flex-1 overflow-y-auto bg-slate-50 p-6">
            {/* Header with layout toggle */}
            <div className="flex items-center justify-between mb-4">
                <h2 className="text-lg font-bold text-slate-800">대시보드</h2>
                <LayoutToggle layout={layoutMode} onToggle={setLayoutMode} />
            </div>

            {/* WIDE LAYOUT: Map (left) + Stats (right) side by side */}
            {isWideLayout ? (
                <div className="grid grid-cols-2 gap-6" style={{ minHeight: 'calc(100vh - 180px)' }}>
                    {/* Left Column - Footprint Map (full height) */}
                    <div className="flex flex-col">
                        <FootprintMap
                            projects={projects}
                            height="100%"
                            style={{ flex: 1, minHeight: '500px' }}
                            onProjectClick={onProjectClick}
                            highlightProjectId={highlightProjectId}
                            selectedProjectId={selectedProject?.id}
                            onRegionClick={onRegionClick}
                            activeRegionName={regionFilter}
                        />
                    </div>

                    {/* Right Column - Stats or Project Details or Inspector */}
                    <div className="flex flex-col gap-6">
                        {selectedProject ? (
                            showInspector && renderInspector ? (
                                <div className="panel-slide-in-right">
                                    {renderInspector(selectedProject)}
                                </div>
                            ) : (
                                <ProjectDetailView project={selectedProject} onBack={onDeselectProject} />
                            )
                        ) : (
                            <>
                                {/* Stats Summary (4 cards in 2x2 grid) */}
                                <StatsSummary stats={stats} isCompact={true} />

                                {/* Additional Charts */}
                                <TrendLineChart data={monthlyData} height={180} />
                                <div className="grid grid-cols-2 gap-4">
                                    <DistributionPieChart data={regionalData} height={160} />
                                    <ProgressDonutChart
                                        completed={stats.completed}
                                        total={stats.completed + stats.processing}
                                        height={160}
                                    />
                                </div>
                            </>
                        )}
                    </div>
                </div>
            ) : (
                /* NARROW LAYOUT: Map on top, Stats below (stacked) */
                <div className="flex flex-col gap-0">
                    {/* Top - Footprint Map (full width, draggable height) */}
                    <FootprintMap
                        projects={projects}
                        height={mapHeight}
                        onProjectClick={onProjectClick}
                        highlightProjectId={highlightProjectId}
                        selectedProjectId={selectedProject?.id}
                        onRegionClick={onRegionClick}
                        activeRegionName={regionFilter}
                    />

                    {/* Drag Handle */}
                    <div
                        className="flex items-center justify-center h-4 cursor-ns-resize hover:bg-slate-200 bg-slate-100 rounded-b-lg -mt-2 mx-2 mb-4 transition-colors"
                        onMouseDown={(e) => {
                            isDragging.current = true;
                            startY.current = e.clientY;
                            startHeight.current = mapHeight;
                            document.body.style.cursor = 'ns-resize';
                            document.body.style.userSelect = 'none';

                            const handleMouseMove = (moveEvent) => {
                                if (!isDragging.current) return;
                                const deltaY = moveEvent.clientY - startY.current;
                                const newHeight = Math.max(200, Math.min(600, startHeight.current + deltaY));
                                setMapHeight(newHeight);
                            };

                            const handleMouseUp = () => {
                                isDragging.current = false;
                                document.body.style.cursor = '';
                                document.body.style.userSelect = '';
                                document.removeEventListener('mousemove', handleMouseMove);
                                document.removeEventListener('mouseup', handleMouseUp);
                            };

                            document.addEventListener('mousemove', handleMouseMove);
                            document.addEventListener('mouseup', handleMouseUp);
                        }}
                    >
                        <GripHorizontal size={16} className="text-slate-400" />
                    </div>

                    {/* Stats or Project Details or Inspector */}
                    {selectedProject ? (
                        showInspector && renderInspector ? (
                            <div className="panel-slide-in-right">
                                {renderInspector(selectedProject)}
                            </div>
                        ) : (
                            <ProjectDetailView project={selectedProject} onBack={onDeselectProject} />
                        )
                    ) : (
                        <>
                            {/* Stats Summary (4 cards in a row) */}
                            <StatsSummary stats={stats} isCompact={false} />

                            {/* Additional Charts */}
                            <TrendLineChart data={monthlyData} height={200} />

                            <div className={`grid gap-4 ${containerWidth > 600 ? 'grid-cols-3' : containerWidth > 400 ? 'grid-cols-2' : 'grid-cols-1'}`}>
                                <DistributionPieChart data={regionalData} height={180} />
                                <ProgressDonutChart
                                    completed={stats.completed}
                                    total={stats.completed + stats.processing}
                                    height={180}
                                />
                                <MonthlyBarChart data={monthlyData} height={180} />
                            </div>
                        </>
                    )}
                </div>
            )}
        </div>
    );
}
