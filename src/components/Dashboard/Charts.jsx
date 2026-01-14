import React from 'react';
import {
    LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
    PieChart, Pie, Cell, Legend,
    BarChart, Bar
} from 'recharts';

// Color palette
const COLORS = {
    primary: '#3b82f6',
    success: '#10b981',
    warning: '#f59e0b',
    danger: '#ef4444',
    slate: '#64748b',
    blue: ['#3b82f6', '#60a5fa', '#93c5fd', '#bfdbfe'],
    multi: ['#3b82f6', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6', '#06b6d4']
};

/**
 * Line Chart for time series data (e.g., monthly processing trends)
 */
export function TrendLineChart({ data, dataKey = 'value', xAxisKey = 'name', height = 200, showLegend = false }) {
    return (
        <div className="bg-white rounded-xl p-5 shadow-sm border border-slate-100">
            <h3 className="text-sm font-bold text-slate-700 mb-4">월별 처리 현황</h3>
            <ResponsiveContainer width="100%" height={height}>
                <LineChart data={data} margin={{ top: 5, right: 20, left: 0, bottom: 5 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                    <XAxis dataKey={xAxisKey} tick={{ fontSize: 12, fill: '#64748b' }} axisLine={{ stroke: '#e2e8f0' }} />
                    <YAxis tick={{ fontSize: 12, fill: '#64748b' }} axisLine={{ stroke: '#e2e8f0' }} />
                    <Tooltip
                        contentStyle={{
                            backgroundColor: 'white',
                            border: '1px solid #e2e8f0',
                            borderRadius: '8px',
                            boxShadow: '0 4px 6px -1px rgba(0,0,0,0.1)'
                        }}
                    />
                    <Line
                        type="monotone"
                        dataKey={dataKey}
                        stroke={COLORS.primary}
                        strokeWidth={2}
                        dot={{ fill: COLORS.primary, strokeWidth: 2, r: 4 }}
                        activeDot={{ r: 6, fill: COLORS.primary }}
                    />
                    {showLegend && <Legend />}
                </LineChart>
            </ResponsiveContainer>
        </div>
    );
}

/**
 * Pie Chart for distribution data (e.g., regional distribution)
 */
export function DistributionPieChart({ data, title = '지역별 분포', height = 200 }) {
    return (
        <div className="bg-white rounded-xl p-5 shadow-sm border border-slate-100">
            <h3 className="text-sm font-bold text-slate-700 mb-4">{title}</h3>
            <ResponsiveContainer width="100%" height={height}>
                <PieChart>
                    <Pie
                        data={data}
                        cx="35%"
                        cy="50%"
                        innerRadius={0}
                        outerRadius={50}
                        paddingAngle={2}
                        dataKey="value"
                    >
                        {data.map((entry, index) => (
                            <Cell key={`cell-${index}`} fill={COLORS.multi[index % COLORS.multi.length]} />
                        ))}
                    </Pie>
                    <Tooltip formatter={(value) => `${value.toFixed(1)}%`} />
                    <Legend
                        layout="vertical"
                        align="right"
                        verticalAlign="middle"
                        wrapperStyle={{ fontSize: '11px', fontFamily: 'inherit', paddingLeft: '10px' }}
                        formatter={(value, entry) => `${value} (${entry.payload.value?.toFixed(1) || 0}%)`}
                    />
                </PieChart>
            </ResponsiveContainer>
        </div>
    );
}

/**
 * Donut Chart for progress/status (e.g., processing completion rate)
 */
export function ProgressDonutChart({ completed, total, title = '처리 현황', height = 200 }) {
    const percentage = total > 0 ? Math.round((completed / total) * 100) : 0;
    const remaining = total - completed;

    const data = [
        { name: '완료', value: completed },
        { name: '미완료', value: remaining }
    ];

    return (
        <div className="bg-white rounded-xl p-5 shadow-sm border border-slate-100">
            <h3 className="text-sm font-bold text-slate-700 mb-4">{title}</h3>
            <div className="relative" style={{ height }}>
                <ResponsiveContainer width="100%" height="100%">
                    <PieChart>
                        <Pie
                            data={data}
                            cx="50%"
                            cy="50%"
                            innerRadius={50}
                            outerRadius={70}
                            startAngle={90}
                            endAngle={-270}
                            dataKey="value"
                        >
                            <Cell fill={COLORS.success} />
                            <Cell fill="#e2e8f0" />
                        </Pie>
                    </PieChart>
                </ResponsiveContainer>
                <div className="absolute inset-0 flex flex-col items-center justify-center">
                    <span className="text-3xl font-bold text-slate-800">{percentage}%</span>
                    <span className="text-xs text-slate-500">완료율</span>
                </div>
            </div>
            <div className="flex justify-center gap-6 mt-2 text-xs">
                <div className="flex items-center gap-1.5">
                    <div className="w-2.5 h-2.5 rounded-full bg-emerald-500"></div>
                    <span className="text-slate-600">완료 {completed.toLocaleString()}건</span>
                </div>
                <div className="flex items-center gap-1.5">
                    <div className="w-2.5 h-2.5 rounded-full bg-slate-200"></div>
                    <span className="text-slate-600">미완료 {remaining.toLocaleString()}건</span>
                </div>
            </div>
        </div>
    );
}

/**
 * Bar Chart for monthly data comparison
 */
export function MonthlyBarChart({ data, title = '월별 처리량', height = 200 }) {
    return (
        <div className="bg-white rounded-xl p-5 shadow-sm border border-slate-100">
            <h3 className="text-sm font-bold text-slate-700 mb-4">{title}</h3>
            <ResponsiveContainer width="100%" height={height}>
                <BarChart data={data} margin={{ top: 5, right: 20, left: 0, bottom: 5 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" vertical={false} />
                    <XAxis dataKey="name" tick={{ fontSize: 11, fill: '#64748b' }} axisLine={false} tickLine={false} />
                    <YAxis tick={{ fontSize: 11, fill: '#64748b' }} axisLine={false} tickLine={false} />
                    <Tooltip
                        contentStyle={{
                            backgroundColor: 'white',
                            border: '1px solid #e2e8f0',
                            borderRadius: '8px'
                        }}
                        cursor={{ fill: 'rgba(59, 130, 246, 0.1)' }}
                    />
                    <Bar dataKey="completed" fill={COLORS.primary} radius={[4, 4, 0, 0]} name="완료" />
                    <Bar dataKey="processing" fill={COLORS.success} radius={[4, 4, 0, 0]} name="진행중" />
                </BarChart>
            </ResponsiveContainer>
        </div>
    );
}

export default { TrendLineChart, DistributionPieChart, ProgressDonutChart, MonthlyBarChart };
