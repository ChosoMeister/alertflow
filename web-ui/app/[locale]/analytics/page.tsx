'use client';

import { useEffect, useState } from 'react';
import { useRouter, Link } from '@/navigation';
import { useTranslations } from 'next-intl';
import { useAuth } from '@/hooks/use-auth';
import { Sidebar } from '@/components/sidebar';
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from '@/components/ui/card';
import { api } from '@/lib/api';
import {
    BarChart3, TrendingUp, Users, Clock, Brain, Shield, CheckCircle, Gauge, BellOff, GitMerge
} from 'lucide-react';

const SEVERITY_COLORS: Record<string, string> = {
    Critical: '#ef4444',
    High: '#f97316',
    Medium: '#eab308',
    Low: '#3b82f6',
    Info: '#6b7280',
    Unknown: '#4b5563',
};

const STATUS_COLORS: Record<string, string> = {
    new: '#3b82f6',
    acknowledged: '#eab308',
    resolved: '#22c55e',
    duplicate: '#8b5cf6',
    redundant: '#6b7280',
};

export default function AnalyticsPage() {
    const router = useRouter();
    const t = useTranslations('Analytics');
    const { token, isLoading: authLoading } = useAuth();
    const [data, setData] = useState<any>(null);
    const [loading, setLoading] = useState(true);

    useEffect(() => {
        if (token) loadAnalytics();
    }, [token]);

    async function loadAnalytics() {
        try {
            const result = await api.analytics(token!);
            setData(result);
        } catch (e) {
            console.error('Analytics load failed:', e);
        } finally {
            setLoading(false);
        }
    }

    if (authLoading || !token) return null;

    const maxDaily = data ? Math.max(...data.daily_trend.map((d: any) => d.count), 1) : 1;
    const maxHourly = data ? Math.max(...data.hourly_distribution.map((h: any) => h.count), 1) : 1;
    const maxSeverity = data ? Math.max(...data.severity_distribution.map((s: any) => s.count), 1) : 1;
    const maxSender = data?.top_senders?.length ? Math.max(...data.top_senders.map((s: any) => s.total), 1) : 1;

    return (
        <div className="flex min-h-screen">
            <Sidebar />
            <main className="flex-1 ltr:ml-64 rtl:mr-64 p-6">
                <div className="flex items-center justify-between mb-6">
                    <div>
                        <h1 className="text-3xl font-bold">{t('title')}</h1>
                        <p className="text-muted-foreground">{t('subtitle')}</p>
                    </div>
                </div>

                {loading ? (
                    <p className="text-muted-foreground">{t('loading')}</p>
                ) : !data ? (
                    <p className="text-muted-foreground">{t('no_data')}</p>
                ) : (
                    <div className="space-y-6">
                        <Card className="overflow-hidden border-cyan-500/20">
                            <div className="h-1 bg-gradient-to-r from-cyan-500 via-violet-500 to-emerald-500" />
                            <CardHeader>
                                <CardTitle className="flex items-center gap-2"><Gauge className="h-5 w-5 text-cyan-400" />{t('reliability_title')}</CardTitle>
                                <CardDescription>{t('reliability_desc')}</CardDescription>
                            </CardHeader>
                            <CardContent className="space-y-5">
                                <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">
                                    {[
                                        [t('operational_score'), data.reliability_scorecard?.operational_score_percent, '%'],
                                        [t('ai_coverage'), data.reliability_scorecard?.ai_analysis_coverage_percent, '%'],
                                        [t('decision_coverage'), data.reliability_scorecard?.decision_trace_coverage_percent, '%'],
                                        [t('prevented_notifications'), data.reliability_scorecard?.prevented_notifications, ''],
                                        [t('merged_updates'), data.reliability_scorecard?.merged_updates, ''],
                                    ].map(([label, value, suffix]) => <div key={String(label)} className="data-tile min-w-0"><span>{label}</span><strong className="text-2xl">{value ?? '—'}{value != null ? suffix : ''}</strong></div>)}
                                </div>
                                <div className="grid gap-3 lg:grid-cols-2">
                                    <div className="rounded-xl border border-white/10 p-4"><div className="flex items-center gap-2 text-sm font-semibold"><BellOff className="h-4 w-4 text-amber-300" />{t('suppression_reasons')}</div><div className="mt-3 flex flex-wrap gap-2">{Object.entries(data.reliability_scorecard?.suppressed_by_reason || {}).length ? Object.entries(data.reliability_scorecard.suppressed_by_reason).map(([reason, count]) => <span key={reason} className="resource-chip">{reason.replaceAll('_', ' ')} · {String(count)}</span>) : <span className="text-xs text-muted-foreground">{t('none_recorded')}</span>}</div></div>
                                    <div className="rounded-xl border border-white/10 p-4"><div className="flex items-center gap-2 text-sm font-semibold"><GitMerge className="h-4 w-4 text-violet-300" />{t('correlation_actions')}</div><div className="mt-3 flex flex-wrap gap-2">{Object.entries(data.reliability_scorecard?.correlation_actions || {}).map(([action, count]) => <span key={action} className="resource-chip">{action} · {String(count)}</span>)}</div></div>
                                </div>
                                <p className="text-xs leading-5 text-muted-foreground">{t('reliability_note')}</p>
                            </CardContent>
                        </Card>
                        <Card>
                            <CardHeader>
                                <CardTitle>{t('slo_title')}</CardTitle>
                                <CardDescription>{t('slo_desc')}</CardDescription>
                            </CardHeader>
                            <CardContent>
                                <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-7 gap-4">
                                    {[
                                        [t('availability'), data.slo?.availability_percent, '%'],
                                        [t('final_delivery_success'), data.slo?.final_delivery_success_percent, '%'],
                                        [t('attempt_delivery_success'), data.slo?.delivery_success_percent, '%'],
                                        [t('ai_success'), data.slo?.ai_success_percent, '%'],
                                        [t('mttr'), data.slo?.mean_time_to_resolve_minutes, 'm'],
                                        [t('fallback_uses'), data.slo?.fallback_uses, ''],
                                        [t('storm_suppressed'), data.slo?.storm_notifications_suppressed, ''],
                                    ].map(([label, value, suffix]) => (
                                        <div key={String(label)} className="rounded-lg border bg-muted/20 p-4">
                                            <p className="text-2xl font-bold">{value ?? '—'}{value != null ? suffix : ''}</p>
                                            <p className="mt-1 text-xs text-muted-foreground">{label}</p>
                                        </div>
                                    ))}
                                </div>
                            </CardContent>
                        </Card>
                        {/* Summary Cards */}
                        <div className="grid grid-cols-1 md:grid-cols-5 gap-4">
                            <Card>
                                <CardContent className="pt-6">
                                    <div className="flex items-center gap-4">
                                        <div className="p-3 rounded-lg bg-blue-500/10">
                                            <Shield className="h-6 w-6 text-blue-400" />
                                        </div>
                                        <div>
                                            <p className="text-3xl font-bold">{data.total_alerts}</p>
                                            <p className="text-sm text-muted-foreground">{t('total_alerts')}</p>
                                        </div>
                                    </div>
                                </CardContent>
                            </Card>
                            <Card>
                                <CardContent className="pt-6">
                                    <div className="flex items-center gap-4">
                                        <div className="p-3 rounded-lg bg-red-500/10">
                                            <TrendingUp className="h-6 w-6 text-red-400" />
                                        </div>
                                        <div>
                                            <p className="text-3xl font-bold">
                                                {data.severity_distribution.find((s: any) => s.severity === 'Critical')?.count || 0}
                                            </p>
                                            <p className="text-sm text-muted-foreground">{t('critical_alerts')}</p>
                                        </div>
                                    </div>
                                </CardContent>
                            </Card>
                            <Card>
                                <CardContent className="pt-6">
                                    <div className="flex items-center gap-4">
                                        <div className="p-3 rounded-lg bg-green-500/10">
                                            <CheckCircle className="h-6 w-6 text-green-400" />
                                        </div>
                                        <div>
                                            <p className="text-3xl font-bold">{data.resolved_count || 0}</p>
                                            <p className="text-sm text-muted-foreground">{t('resolved_alerts')}</p>
                                        </div>
                                    </div>
                                </CardContent>
                            </Card>
                            <Card>
                                <CardContent className="pt-6">
                                    <div className="flex items-center gap-4">
                                        <div className="p-3 rounded-lg bg-orange-500/10">
                                            <Brain className="h-6 w-6 text-orange-400" />
                                        </div>
                                        <div>
                                            <p className="text-3xl font-bold">{data.ai_performance.avg_duration}s</p>
                                            <p className="text-sm text-muted-foreground">{t('avg_ai_time')}</p>
                                        </div>
                                    </div>
                                </CardContent>
                            </Card>
                            <Card>
                                <CardContent className="pt-6">
                                    <div className="flex items-center gap-4">
                                        <div className="p-3 rounded-lg bg-cyan-500/10">
                                            <Users className="h-6 w-6 text-cyan-400" />
                                        </div>
                                        <div>
                                            <p className="text-3xl font-bold">{data.top_senders.length}</p>
                                            <p className="text-sm text-muted-foreground">{t('unique_sources')}</p>
                                        </div>
                                    </div>
                                </CardContent>
                            </Card>
                        </div>

                        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                            {/* Severity Distribution */}
                            <Card>
                                <CardHeader>
                                    <CardTitle className="flex items-center gap-2">
                                        <BarChart3 className="h-5 w-5" />
                                        {t('severity_dist')}
                                    </CardTitle>
                                </CardHeader>
                                <CardContent>
                                    <div className="space-y-3">
                                        {data.severity_distribution.map((item: any) => (
                                            <div key={item.severity} className="space-y-1">
                                                <div className="flex justify-between text-sm">
                                                    <span>{item.severity}</span>
                                                    <span className="text-muted-foreground">{item.count}</span>
                                                </div>
                                                <div className="h-3 bg-muted rounded-full overflow-hidden">
                                                    <div
                                                        className="h-full rounded-full transition-all duration-700"
                                                        style={{
                                                            width: `${(item.count / maxSeverity) * 100}%`,
                                                            backgroundColor: SEVERITY_COLORS[item.severity] || '#6b7280',
                                                        }}
                                                    />
                                                </div>
                                            </div>
                                        ))}
                                    </div>
                                </CardContent>
                            </Card>

                            {/* Status Distribution */}
                            <Card>
                                <CardHeader>
                                    <CardTitle className="flex items-center gap-2">
                                        <Shield className="h-5 w-5" />
                                        {t('status_dist')}
                                    </CardTitle>
                                </CardHeader>
                                <CardContent>
                                    <div className="space-y-3">
                                        {data.status_distribution.map((item: any) => {
                                            const maxStatus = Math.max(...data.status_distribution.map((s: any) => s.count), 1);
                                            return (
                                                <div key={item.status} className="space-y-1">
                                                    <div className="flex justify-between text-sm">
                                                        <span className="capitalize">{item.status}</span>
                                                        <span className="text-muted-foreground">{item.count}</span>
                                                    </div>
                                                    <div className="h-3 bg-muted rounded-full overflow-hidden">
                                                        <div
                                                            className="h-full rounded-full transition-all duration-700"
                                                            style={{
                                                                width: `${(item.count / maxStatus) * 100}%`,
                                                                backgroundColor: STATUS_COLORS[item.status] || '#6b7280',
                                                            }}
                                                        />
                                                    </div>
                                                </div>
                                            );
                                        })}
                                    </div>
                                </CardContent>
                            </Card>
                        </div>

                        {/* Daily Trend (7 days) */}
                        <Card>
                            <CardHeader>
                                <CardTitle className="flex items-center gap-2">
                                    <TrendingUp className="h-5 w-5" />
                                    {t('daily_trend')}
                                </CardTitle>
                                <CardDescription>{t('daily_trend_desc')}</CardDescription>
                            </CardHeader>
                            <CardContent>
                                <div className="flex items-end gap-2 h-48">
                                    {data.daily_trend.map((day: any) => (
                                        <div key={day.date} className="flex-1 flex flex-col items-center gap-1">
                                            <span className="text-xs text-muted-foreground">{day.count}</span>
                                            <div className="w-full bg-muted rounded-t-md overflow-hidden relative" style={{ height: '160px' }}>
                                                <div
                                                    className="absolute bottom-0 w-full rounded-t-md bg-primary/80 transition-all duration-700"
                                                    style={{ height: `${(day.count / maxDaily) * 100}%` }}
                                                />
                                            </div>
                                            <span className="text-xs text-muted-foreground">{day.label}</span>
                                        </div>
                                    ))}
                                </div>
                            </CardContent>
                        </Card>

                        {/* Hourly Distribution (24h) */}
                        <Card>
                            <CardHeader>
                                <CardTitle className="flex items-center gap-2">
                                    <Clock className="h-5 w-5" />
                                    {t('hourly_dist')}
                                </CardTitle>
                                <CardDescription>{t('hourly_dist_desc')}</CardDescription>
                            </CardHeader>
                            <CardContent>
                                <div className="flex items-end gap-0.5 h-32">
                                    {data.hourly_distribution.map((hour: any) => (
                                        <div key={hour.hour} className="flex-1 flex flex-col items-center">
                                            <div className="w-full bg-muted rounded-t-sm overflow-hidden relative" style={{ height: '100px' }}>
                                                <div
                                                    className="absolute bottom-0 w-full rounded-t-sm bg-blue-500/70 transition-all duration-700"
                                                    style={{ height: hour.count > 0 ? `${Math.max((hour.count / maxHourly) * 100, 4)}%` : '0%' }}
                                                />
                                            </div>
                                            {hour.hour % 3 === 0 && (
                                                <span className="text-[10px] text-muted-foreground mt-1">{hour.label}</span>
                                            )}
                                        </div>
                                    ))}
                                </div>
                            </CardContent>
                        </Card>

                        {/* Top Senders */}
                        <Card>
                            <CardHeader>
                                <CardTitle className="flex items-center gap-2">
                                    <Users className="h-5 w-5" />
                                    {t('top_senders')}
                                </CardTitle>
                                <CardDescription>{t('top_senders_desc')}</CardDescription>
                            </CardHeader>
                            <CardContent>
                                {data.top_senders.length === 0 ? (
                                    <p className="text-muted-foreground text-sm">{t('no_data')}</p>
                                ) : (
                                    <div className="overflow-x-auto">
                                        <table className="w-full text-sm">
                                            <thead>
                                                <tr className="border-b border-border">
                                                    <th className="text-left py-2 px-2 text-muted-foreground font-medium">#</th>
                                                    <th className="text-left py-2 px-2 text-muted-foreground font-medium">{t('sender_email')}</th>
                                                    <th className="text-center py-2 px-2 text-muted-foreground font-medium">{t('col_total')}</th>
                                                    <th className="text-center py-2 px-2 text-muted-foreground font-medium">{t('col_resolved')}</th>
                                                    <th className="text-center py-2 px-2 text-muted-foreground font-medium">{t('col_open')}</th>
                                                    <th className="py-2 px-2 text-muted-foreground font-medium w-1/3"></th>
                                                </tr>
                                            </thead>
                                            <tbody>
                                                {data.top_senders.map((sender: any, i: number) => (
                                                    <tr key={sender.email} className="border-b border-border/50 hover:bg-muted/30 transition-colors">
                                                        <td className="py-2.5 px-2 text-muted-foreground">{i + 1}</td>
                                                        <td className="py-2.5 px-2 font-medium">{sender.email}</td>
                                                        <td className="py-2.5 px-2 text-center">{sender.total}</td>
                                                        <td className="py-2.5 px-2 text-center">
                                                            <span className="text-green-400">{sender.resolved}</span>
                                                        </td>
                                                        <td className="py-2.5 px-2 text-center">
                                                            {sender.open > 0 ? (
                                                                <Link
                                                                    href={`/alerts?sender=${encodeURIComponent(sender.email)}&status=open`}
                                                                    className="inline-flex items-center justify-center min-w-[28px] px-2 py-0.5 rounded-full bg-red-500/15 text-red-400 font-semibold hover:bg-red-500/25 transition-colors cursor-pointer"
                                                                >
                                                                    {sender.open}
                                                                </Link>
                                                            ) : (
                                                                <span className="text-muted-foreground">0</span>
                                                            )}
                                                        </td>
                                                        <td className="py-2.5 px-2">
                                                            <div className="h-2 bg-muted rounded-full overflow-hidden flex">
                                                                <div
                                                                    className="h-full bg-green-500/70 transition-all duration-700"
                                                                    style={{ width: `${(sender.resolved / maxSender) * 100}%` }}
                                                                />
                                                                <div
                                                                    className="h-full bg-red-500/50 transition-all duration-700"
                                                                    style={{ width: `${(sender.open / maxSender) * 100}%` }}
                                                                />
                                                            </div>
                                                        </td>
                                                    </tr>
                                                ))}
                                            </tbody>
                                        </table>
                                    </div>
                                )}
                            </CardContent>
                        </Card>
                    </div>
                )}
            </main>
        </div>
    );
}
