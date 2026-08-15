'use client';

import { useEffect, useState } from 'react';
import { useRouter } from '@/navigation';
import { useSearchParams } from 'next/navigation';
import { useTranslations } from 'next-intl';
import { Sidebar } from '@/components/sidebar';
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { api } from '@/lib/api';
import { formatDate, truncate, severityColor, statusColor } from '@/lib/utils';
import { AlertCircle, ChevronRight, RefreshCcw, Search, Send } from 'lucide-react';
import useSWR from 'swr';
import { Skeleton } from '@/components/ui/skeleton';
import { toast } from 'sonner';
import { IncidentDrawer } from '@/components/incident-drawer';
import { Bookmark, Command, SlidersHorizontal } from 'lucide-react';

interface Alert {
    id: string;
    from_email: string;
    to_email: string;
    subject: string;
    severity: string;
    category: string;
    status: string;
    channel: string;
    system_name: string;
    main_message: string;
    created_at: string;
}

export default function AlertsPage() {
    const router = useRouter();
    const searchParams = useSearchParams();
    const t = useTranslations('Alerts');
    const c = useTranslations('Common');
    const [token, setToken] = useState<string | null>(null);
    const [filter, setFilter] = useState<{ status?: string; severity?: string; q?: string }>({ status: 'open' });
    const [searchInput, setSearchInput] = useState('');
    const [isSendingSummary, setIsSendingSummary] = useState(false);
    const [selectedAlert, setSelectedAlert] = useState<string | null>(null);
    const [density, setDensity] = useState<'comfortable' | 'compact'>('comfortable');

    // Read query params on mount (from Analytics clickable links)
    useEffect(() => {
        const senderParam = searchParams.get('sender');
        const statusParam = searchParams.get('status');
        if (senderParam || statusParam) {
            if (senderParam) setSearchInput(senderParam);
            setFilter(prev => ({
                ...prev,
                q: senderParam || undefined,
                status: statusParam || undefined,
            }));
        }
    }, [searchParams]);

    useEffect(() => {
        const storedToken = localStorage.getItem('alertflow_token');
        if (!storedToken) {
            router.push('/login');
            return;
        }
        setToken(storedToken);
    }, [router]);

    // Debounce search input
    useEffect(() => {
        const timer = setTimeout(() => {
            setFilter(prev => ({ ...prev, q: searchInput || undefined }));
        }, 500);
        return () => clearTimeout(timer);
    }, [searchInput]);

    const fetcher = async ([_, authToken, filterObj]: [string, string, any]): Promise<Alert[]> => {
        return api.alerts(authToken, { ...filterObj, limit: 100 });
    };

    const { data: alerts, error, isLoading, mutate } = useSWR<Alert[]>(
        token ? ['/api/alerts', token, filter] : null,
        fetcher,
        { refreshInterval: 30000 }
    );

    const handleForceSummary = async () => {
        if (!token) return;
        setIsSendingSummary(true);
        try {
            await api.forceSummary(token);
            toast.success(t('summary_sent_success') || 'Summary generation triggered');
        } catch (error: any) {
            toast.error(error.message || 'Failed to trigger summary');
        } finally {
            setIsSendingSummary(false);
        }
    };

    if (!token) return null;

    return (
        <div className="flex min-h-screen">
            <Sidebar />
            <main className="flex-1 ltr:ml-64 rtl:mr-64 p-6">
                <div className="flex flex-col gap-6 mb-6">
                    <div className="flex items-center justify-between">
                        <div>
                            <p className="eyebrow">Incident workspace</p>
                            <h1 className="mt-2 text-3xl font-semibold tracking-tight">{t('title')}</h1>
                            <p className="mt-1 text-muted-foreground">Prioritize, investigate and respond without losing context.</p>
                        </div>
                        <div className="flex items-center gap-2">
                            <Button variant="secondary" onClick={handleForceSummary} disabled={isSendingSummary}>
                                <Send className={`h-4 w-4 ltr:mr-2 rtl:ml-2 ${isSendingSummary ? 'opacity-50' : ''}`} />
                                {t('force_summary') || 'Force Summary'}
                            </Button>
                            <Button variant="outline" onClick={() => mutate()}>
                                <RefreshCcw className={`h-4 w-4 ltr:mr-2 rtl:ml-2 ${isLoading && alerts ? 'animate-spin' : ''}`} />
                                {t('refresh')}
                            </Button>
                            <button onClick={() => setDensity(value => value === 'compact' ? 'comfortable' : 'compact')} className="icon-button" title="Toggle density"><SlidersHorizontal className="h-4 w-4"/></button>
                        </div>
                    </div>

                    <div className="flex flex-col xl:flex-row items-start xl:items-center justify-between gap-4">
                        <div className="flex bg-white/[.03] p-1 rounded-xl border border-white/10 w-full xl:w-auto overflow-x-auto">
                            <button
                                onClick={() => setFilter({ ...filter, status: undefined })}
                                className={`px-4 py-1.5 text-sm font-medium rounded-sm transition-all whitespace-nowrap ${!filter.status ? 'bg-background shadow-sm text-foreground' : 'text-muted-foreground hover:text-foreground'}`}
                            >
                                {t('all_alerts')}
                            </button>
                            <button
                                onClick={() => setFilter({ ...filter, status: 'open' })}
                                className={`px-4 py-1.5 text-sm font-medium rounded-sm transition-all flex items-center gap-1.5 whitespace-nowrap ${filter.status === 'open' ? 'bg-background shadow-sm text-foreground' : 'text-muted-foreground hover:text-foreground'}`}
                            >
                                <span className="w-2 h-2 rounded-full bg-red-500"></span>
                                {t('status_open')}
                            </button>
                            <button
                                onClick={() => setFilter({ ...filter, status: 'resolved' })}
                                className={`px-4 py-1.5 text-sm font-medium rounded-sm transition-all flex items-center gap-1.5 whitespace-nowrap ${filter.status === 'resolved' ? 'bg-background shadow-sm text-foreground' : 'text-muted-foreground hover:text-foreground'}`}
                            >
                                <span className="w-2 h-2 rounded-full bg-green-500"></span>
                                {t('status_resolved')}
                            </button>
                        </div>

                        <div className="flex gap-3 items-center flex-wrap xl:flex-nowrap">
                            <div className="relative">
                                <Search className="absolute ltr:left-2.5 rtl:right-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
                                <input
                                    type="text"
                                    placeholder={t('search')}
                                    value={searchInput}
                                    onChange={(e) => setSearchInput(e.target.value)}
                                    className="h-10 ltr:pl-9 ltr:pr-4 rtl:pr-9 rtl:pl-4 w-48 xl:w-64 rounded-md border border-input bg-background text-sm focus:outline-none focus:ring-2 focus:ring-primary/50"
                                />
                            </div>
                            <select
                                value={filter.severity || ''}
                                onChange={(e) => setFilter({ ...filter, severity: e.target.value || undefined })}
                                className="h-10 px-3 rounded-md border border-input bg-background text-sm focus:outline-none focus:ring-2 focus:ring-primary/50"
                            >
                                <option value="">{t('all_severities')}</option>
                                <option value="Critical">{t('severity_critical')}</option>
                                <option value="High">{t('severity_high')}</option>
                                <option value="Medium">{t('severity_medium')}</option>
                                <option value="Low">{t('severity_low')}</option>
                                <option value="Info">{t('severity_info')}</option>
                            </select>
                            <select
                                value={filter.status || ''}
                                onChange={(e) => setFilter({ ...filter, status: e.target.value || undefined })}
                                className="h-10 px-3 rounded-md border border-input bg-background text-sm focus:outline-none focus:ring-2 focus:ring-primary/50"
                            >
                                <option value="">{t('all_status')}</option>
                                <option value="open">🔴 {t('status_open')}</option>
                                <option value="new">{t('status_new')}</option>
                                <option value="acknowledged">{t('status_acknowledged')}</option>
                                <option value="resolved">✅ {t('status_resolved')}</option>
                                <option value="duplicate">{t('status_duplicate')}</option>
                                <option value="redundant">{t('status_redundant')}</option>
                            </select>
                        </div>
                    </div>
                    <div className="flex flex-wrap items-center gap-2"><span className="me-1 flex items-center gap-1.5 text-xs text-slate-500"><Bookmark className="h-3.5 w-3.5"/>Saved views</span>{[
                        ['Critical open', { status: 'open', severity: 'Critical' }], ['Outside SLA', { status: 'open', q: 'SLA' }], ['AI failed', { q: 'analysis failed' }], ['Delivery failed', { q: 'delivery failed' }]
                    ].map(([label, view]: any) => <button key={label} onClick={() => { setFilter(view); setSearchInput(view.q || ''); }} className="rounded-full border border-white/10 px-3 py-1.5 text-xs text-slate-400 transition hover:border-cyan-400/30 hover:text-cyan-200">{label}</button>)}<span className="ms-auto hidden items-center gap-1 text-[11px] text-slate-600 lg:flex"><Command className="h-3 w-3"/>⌘K for quick navigation</span></div>
                </div>

                {isLoading && !alerts ? (
                    <div className="space-y-3">
                        {[...Array(5)].map((_, i) => (
                            <Card key={i}>
                                <CardContent className="py-4">
                                    <div className="flex items-center justify-between">
                                        <div className="flex items-center gap-4 w-full">
                                            <Skeleton className="h-10 w-10 rounded-lg" />
                                            <div className="flex-1 space-y-2">
                                                <Skeleton className="h-4 w-1/3" />
                                                <Skeleton className="h-3 w-1/4" />
                                            </div>
                                            <Skeleton className="h-4 w-24" />
                                            <Skeleton className="h-4 w-4 rounded-full" />
                                        </div>
                                    </div>
                                </CardContent>
                            </Card>
                        ))}
                    </div>
                ) : error ? (
                    <Card>
                        <CardContent className="py-12 text-center">
                            <AlertCircle className="h-12 w-12 mx-auto text-red-500 mb-4" />
                            <p className="text-red-500">Failed to load alerts</p>
                        </CardContent>
                    </Card>
                ) : alerts?.length === 0 ? (
                    <Card>
                        <CardContent className="py-12 text-center">
                            <AlertCircle className="h-12 w-12 mx-auto text-muted-foreground mb-4" />
                            <p className="text-muted-foreground">{t('no_alerts_found')}</p>
                        </CardContent>
                    </Card>
                ) : (
                    <div className="space-y-3">
                        {alerts?.map((alert) => (
                            <Card
                                key={alert.id}
                                className="cursor-pointer overflow-hidden border-white/10 bg-slate-900/50 transition-all hover:-translate-y-0.5 hover:border-cyan-400/30 hover:shadow-lg hover:shadow-cyan-950/20"
                                onClick={() => setSelectedAlert(alert.id)}
                            >
                                <CardContent className={density === 'compact' ? 'py-3' : 'py-5'}>
                                    <div className="grid gap-4 md:grid-cols-[1fr_auto] md:items-center">
                                        <div className="flex min-w-0 items-start gap-4">
                                            <div className={`p-2 rounded-lg ${alert.severity === 'Critical' ? 'bg-red-500/10' :
                                                    alert.severity === 'High' ? 'bg-orange-500/10' :
                                                        alert.severity === 'Medium' ? 'bg-yellow-500/10' :
                                                            alert.severity === 'Low' ? 'bg-green-500/10' :
                                                                'bg-blue-500/10'
                                                }`}>
                                                <AlertCircle className={`h-5 w-5 ${severityColor(alert.severity)}`} />
                                            </div>
                                            <div className="flex-1 min-w-0">
                                                <div className="flex items-center gap-2">
                                                    <span className={`text-xs font-medium px-2 py-0.5 rounded ${severityColor(alert.severity)}`}>
                                                        {alert.severity ? t(`severity_${alert.severity.toLowerCase()}`) : 'Unknown'}
                                                    </span>
                                                    <span className="text-xs text-muted-foreground">
                                                        {alert.category}
                                                    </span>
                                                </div>
                                                <p className="font-medium mt-2 line-clamp-2 leading-6" dir="auto">
                                                    {truncate(alert.main_message || alert.subject || t('no_subject'), 180)}
                                                </p>
                                                <div className="mt-2 flex flex-wrap gap-2"><span className="resource-chip">{alert.system_name || t('unknown_system')}</span><span className="truncate text-xs text-muted-foreground" dir="ltr">{alert.from_email}</span></div>
                                            </div>
                                        </div>
                                        <div className="flex items-center justify-between gap-4 md:justify-end">
                                            <div className="ltr:text-right rtl:text-left">
                                                <span className={`text-xs px-2 py-1 rounded border ${statusColor(alert.status)}`}>
                                                    {alert.status ? t(`status_${alert.status.replace(' (Merged)', '').toLowerCase()}`) : alert.status}
                                                </span>
                                                <p className="text-xs text-muted-foreground mt-2" dir="ltr">
                                                    {formatDate(alert.created_at)}
                                                </p>
                                            </div>
                                            <ChevronRight className="h-5 w-5 text-cyan-400/60 ltr:rotate-0 rtl:rotate-180" />
                                        </div>
                                    </div>
                                </CardContent>
                            </Card>
                        ))}
                    </div>
                )}
                <IncidentDrawer alertId={selectedAlert} token={token} onClose={() => setSelectedAlert(null)} onChanged={() => mutate()} />
            </main>
        </div>
    );
}
