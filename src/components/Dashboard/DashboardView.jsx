import React, { useMemo, useState, useRef, useEffect } from 'react';
import { MapPin, FolderCheck, HardDrive, Camera, BarChart3, LayoutGrid, LayoutList, LayoutTemplate } from 'lucide-react';
import { StatsCard } from './StatsCard';
import { TrendLineChart, DistributionPieChart, ProgressDonutChart, MonthlyBarChart } from './Charts';
import { FootprintMap } from './FootprintMap';

// Mock data for demonstration (will be replaced with API data)
const MOCK_MONTHLY_DATA = [
    { name: 'Jan', value: 40, completed: 35, processing: 15 },
    { name: 'Feb', value: 55, completed: 45, processing: 20 },
    { name: 'Mar', value: 75, completed: 60, processing: 25 },
    { name: 'Apr', value: 90, completed: 70, processing: 30 },
    { name: 'May', value: 85, completed: 65, processing: 28 },
    { name: 'Jun', value: 100, completed: 80, processing: 35 },
];

const MOCK_REGION_DATA = [
    { name: '경기', value: 52.1 },
    { name: '강원', value: 22.8 },
    { name: '충남', value: 13.9 },
    { name: '경북', value: 11.2 },
];

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
    const completedCount = stats.completed || 15;
    const totalCount = (stats.completed || 15) + (stats.processing || 10);
    const progressPercent = Math.round((completedCount / totalCount) * 100);

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
                    value={stats.area || '232.5'}
                    unit="km²"
                    label="처리 완료 면적"
                    progress={35}
                    progressLabel="전체 국토 면적 대비 35%"
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
                        <span className="px-2 py-0.5 text-xs font-medium bg-blue-100 text-blue-700 rounded">진행 {stats.processing || 10}</span>
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
 * Main Dashboard View Component
 * Displays footprint map, statistics, and charts
 * Layout can be forced to wide/narrow or auto-adapt based on container width
 */
export default function DashboardView({
    projects = [],
    sidebarWidth = 320,
    onProjectClick,
    highlightProjectId = null,
    onHighlightEnd = null
}) {
    const containerRef = useRef(null);
    const [containerWidth, setContainerWidth] = useState(800);
    const [layoutMode, setLayoutMode] = useState('auto'); // 'wide', 'narrow', or 'auto'

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
            }, 3500); // 3.5 seconds
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

    // Calculate stats from projects
    const stats = useMemo(() => {
        const processing = projects.filter(p => p.status === '진행중').length;
        const completed = projects.filter(p => p.status === '완료').length;
        const totalImages = projects.reduce((sum, p) => sum + (p.imageCount || 0), 0);

        // Mock area calculation (in production: sum of actual footprint areas)
        const area = (completed * 15.5 + processing * 8.3).toFixed(1);
        const dataSize = (completed * 3.2 + processing * 1.1).toFixed(1);

        return {
            processing: processing || 10,
            completed: completed || 15,
            area: area || '232.5',
            dataSize: dataSize || '51.7',
            photoCount: totalImages || 7305,
            avgPhotos: Math.round(totalImages / Math.max(1, completed + processing)) || 292,
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
                        />
                    </div>

                    {/* Right Column - Stats */}
                    <div className="flex flex-col gap-6">
                        {/* Stats Summary (4 cards in 2x2 grid) */}
                        <StatsSummary stats={stats} isCompact={true} />

                        {/* Additional Charts */}
                        <TrendLineChart data={MOCK_MONTHLY_DATA} height={180} />
                        <div className="grid grid-cols-2 gap-4">
                            <DistributionPieChart data={MOCK_REGION_DATA} height={160} />
                            <ProgressDonutChart
                                completed={stats.completed}
                                total={stats.completed + stats.processing}
                                height={160}
                            />
                        </div>
                    </div>
                </div>
            ) : (
                /* NARROW LAYOUT: Map on top, Stats below (stacked) */
                <div className="flex flex-col gap-6">
                    {/* Top - Footprint Map (full width) */}
                    <FootprintMap
                        projects={projects}
                        height={350}
                        onProjectClick={onProjectClick}
                        highlightProjectId={highlightProjectId}
                    />

                    {/* Stats Summary (4 cards in a row) */}
                    <StatsSummary stats={stats} isCompact={false} />

                    {/* Additional Charts */}
                    <TrendLineChart data={MOCK_MONTHLY_DATA} height={200} />

                    <div className={`grid gap-4 ${containerWidth > 600 ? 'grid-cols-3' : containerWidth > 400 ? 'grid-cols-2' : 'grid-cols-1'}`}>
                        <DistributionPieChart data={MOCK_REGION_DATA} height={180} />
                        <ProgressDonutChart
                            completed={stats.completed}
                            total={stats.completed + stats.processing}
                            height={180}
                        />
                        <MonthlyBarChart data={MOCK_MONTHLY_DATA} height={180} />
                    </div>
                </div>
            )}
        </div>
    );
}
