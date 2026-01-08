import React from 'react';
import { TrendingUp, TrendingDown } from 'lucide-react';

/**
 * Stats Card Component for dashboard
 * Displays a metric with icon, value, label, and optional trend indicator
 */
export function StatsCard({ icon, value, unit, label, trend, trendLabel, className = '' }) {
    const isPositive = trend > 0;
    const isNegative = trend < 0;

    return (
        <div className={`bg-white rounded-xl p-5 shadow-sm border border-slate-100 hover:shadow-md transition-shadow ${className}`}>
            <div className="flex items-start justify-between">
                <div className="flex items-center gap-3">
                    {icon && (
                        <div className="p-2.5 bg-blue-50 rounded-lg text-blue-600">
                            {icon}
                        </div>
                    )}
                    <div>
                        <div className="flex items-baseline gap-1">
                            <span className="text-2xl font-bold text-slate-800">{value}</span>
                            {unit && <span className="text-sm text-slate-500 font-medium">{unit}</span>}
                        </div>
                        <p className="text-sm text-slate-500 mt-0.5">{label}</p>
                    </div>
                </div>
                {trend !== undefined && trend !== null && (
                    <div className={`flex items-center gap-1 text-xs font-medium px-2 py-1 rounded-full ${isPositive ? 'bg-emerald-50 text-emerald-600' :
                            isNegative ? 'bg-red-50 text-red-600' :
                                'bg-slate-50 text-slate-500'
                        }`}>
                        {isPositive && <TrendingUp size={12} />}
                        {isNegative && <TrendingDown size={12} />}
                        <span>{isPositive ? '+' : ''}{trend}%</span>
                    </div>
                )}
            </div>
            {trendLabel && (
                <p className="text-xs text-slate-400 mt-3 pt-3 border-t border-slate-100">
                    {trendLabel}
                </p>
            )}
        </div>
    );
}

/**
 * Stats Cards Grid - displays multiple stats in a responsive grid
 */
export function StatsCardsGrid({ stats }) {
    return (
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
            {stats.map((stat, index) => (
                <StatsCard key={index} {...stat} />
            ))}
        </div>
    );
}

export default StatsCard;
