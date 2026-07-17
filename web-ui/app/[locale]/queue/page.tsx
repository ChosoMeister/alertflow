'use client';

import { useEffect, useState, useCallback } from 'react';
import { useRouter } from '@/navigation';
import { useTranslations } from 'next-intl';
import { Sidebar } from '@/components/sidebar';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import { api } from '@/lib/api';
import { formatDate } from '@/lib/utils';
import { useToast } from '@/hooks/use-toast';
import {
    Layers, AlertTriangle, Clock, RotateCcw, Trash2,
    RefreshCw, CheckCircle, XCircle, Timer, Loader2, Inbox
} from 'lucide-react';

interface QueueMetrics {
    queue_depth: number;
    dlq_depth: number;
    retry_queue_depth: number;
    processed_count: number;
    error_count: number;
    muted_count: number;
    retries_scheduled: number;
    retries_succeeded: number;
}

interface DlqItem {
    index: number;
    sender: string;
    subject: string;
    retry_count: number;
    scheduled_at: string;
    queued_at: string;
}

interface RetryItem {
    sender: string;
    subject: string;
    retry_count: number;
    next_retry_at: string;
    channel: string;
}

export default function QueuePage() {
    const router = useRouter();
    const t = useTranslations('Queue');
    const c = useTranslations('Common');
    const { toast } = useToast();
    const [metrics, setMetrics] = useState<QueueMetrics | null>(null);
    const [dlqItems, setDlqItems] = useState<DlqItem[]>([]);
    const [retryItems, setRetryItems] = useState<RetryItem[]>([]);
    const [loading, setLoading] = useState(true);
    const [refreshing, setRefreshing] = useState(false);
    const [actionLoading, setActionLoading] = useState<string | null>(null);

    const loadData = useCallback(async (showRefresh = false) => {
        const token = localStorage.getItem('alertflow_token');
        if (!token) return;

        if (showRefresh) setRefreshing(true);
        try {
            const [m, dlq, retry] = await Promise.all([
                api.metrics(token),
                api.queueDlq(token),
                api.queueRetry(token),
            ]);
            setMetrics(m);
            setDlqItems(dlq);
            setRetryItems(retry);
        } catch {
            toast({ title: 'Error', description: 'Failed to load queue data', variant: 'destructive' });
        } finally {
            setLoading(false);
            setRefreshing(false);
        }
    }, [toast]);

    useEffect(() => {
        const token = localStorage.getItem('alertflow_token');
        if (!token) { router.push('/login'); return; }
        loadData();
        const interval = setInterval(() => loadData(), 10000);
        return () => clearInterval(interval);
    }, [router, loadData]);

    async function handleFlushDlq() {
        const token = localStorage.getItem('alertflow_token');
        if (!token) return;
        if (!confirm('Are you sure you want to flush the entire DLQ? This cannot be undone.')) return;
        setActionLoading('flush');
        try {
            const result = await api.queueFlushDlq(token);
            toast({ title: 'DLQ Flushed', description: result.message });
            await loadData();
        } catch {
            toast({ title: 'Error', description: 'Failed to flush DLQ', variant: 'destructive' });
        } finally {
            setActionLoading(null);
        }
    }

    async function handleRequeue(index: number) {
        const token = localStorage.getItem('alertflow_token');
        if (!token) return;
        setActionLoading(`requeue-${index}`);
        try {
            const result = await api.queueRequeueDlq(token, index);
            toast({ title: 'Requeued', description: result.message });
            await loadData();
        } catch {
            toast({ title: 'Error', description: 'Failed to requeue item', variant: 'destructive' });
        } finally {
            setActionLoading(null);
        }
    }

    function formatTime(isoStr: string) {
        return formatDate(isoStr);
    }

    function getRetryCountdown(nextRetryAt: string) {
        if (!nextRetryAt) return '—';
        try {
            const target = new Date(nextRetryAt + 'Z').getTime();
            const now = Date.now();
            const diff = Math.max(0, target - now);
            if (diff === 0) return 'imminent';
            const mins = Math.floor(diff / 60000);
            const secs = Math.floor((diff % 60000) / 1000);
            if (mins > 60) return `${Math.floor(mins / 60)}h ${mins % 60}m`;
            if (mins > 0) return `${mins}m ${secs}s`;
            return `${secs}s`;
        } catch {
            return '—';
        }
    }

    if (loading) {
        return (
            <div className="flex min-h-screen">
                <Sidebar />
                <main className="flex-1 ltr:ml-64 rtl:mr-64 p-6 flex items-center justify-center">
                    <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
                </main>
            </div>
        );
    }

    return (
        <div className="flex min-h-screen">
            <Sidebar />
            <main className="flex-1 ltr:ml-64 rtl:mr-64 p-6">
                <div className="flex items-center justify-between mb-6">
                    <div>
                        <h1 className="text-3xl font-bold">{t('title')}</h1>
                        <p className="text-muted-foreground">{t('subtitle')}</p>
                    </div>
                    <Button
                        variant="outline"
                        onClick={() => loadData(true)}
                        disabled={refreshing}
                    >
                        <RefreshCw className={`h-4 w-4 ltr:mr-2 rtl:ml-2 ${refreshing ? 'animate-spin' : ''}`} />
                        {t('refresh')}
                    </Button>
                </div>

                {/* Metric Cards */}
                <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
                    <Card>
                        <CardContent className="pt-4 pb-3">
                            <div className="flex items-center gap-3">
                                <div className="p-2 rounded-lg bg-blue-500/10">
                                    <Layers className="h-5 w-5 text-blue-400" />
                                </div>
                                <div>
                                    <p className="text-2xl font-bold">{metrics?.queue_depth ?? 0}</p>
                                    <p className="text-xs text-muted-foreground">{t('active_queue')}</p>
                                </div>
                            </div>
                        </CardContent>
                    </Card>
                    <Card>
                        <CardContent className="pt-4 pb-3">
                            <div className="flex items-center gap-3">
                                <div className="p-2 rounded-lg bg-yellow-500/10">
                                    <Timer className="h-5 w-5 text-yellow-400" />
                                </div>
                                <div>
                                    <p className="text-2xl font-bold">{metrics?.retry_queue_depth ?? 0}</p>
                                    <p className="text-xs text-muted-foreground">{t('retry_queue')}</p>
                                </div>
                            </div>
                        </CardContent>
                    </Card>
                    <Card>
                        <CardContent className="pt-4 pb-3">
                            <div className="flex items-center gap-3">
                                <div className="p-2 rounded-lg bg-red-500/10">
                                    <AlertTriangle className="h-5 w-5 text-red-400" />
                                </div>
                                <div>
                                    <p className="text-2xl font-bold">{metrics?.dlq_depth ?? 0}</p>
                                    <p className="text-xs text-muted-foreground">{t('dlq')}</p>
                                </div>
                            </div>
                        </CardContent>
                    </Card>
                    <Card>
                        <CardContent className="pt-4 pb-3">
                            <div className="flex items-center gap-3">
                                <div className="p-2 rounded-lg bg-green-500/10">
                                    <CheckCircle className="h-5 w-5 text-green-400" />
                                </div>
                                <div>
                                    <p className="text-2xl font-bold">{metrics?.processed_count ?? 0}</p>
                                    <p className="text-xs text-muted-foreground">{t('total_processed')}</p>
                                </div>
                            </div>
                        </CardContent>
                    </Card>
                </div>

                {/* Stats Row */}
                <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
                    <Card>
                        <CardContent className="pt-3 pb-2 text-center">
                            <p className="text-lg font-semibold">{metrics?.error_count ?? 0}</p>
                            <p className="text-xs text-muted-foreground">{t('total_errors')}</p>
                        </CardContent>
                    </Card>
                    <Card>
                        <CardContent className="pt-3 pb-2 text-center">
                            <p className="text-lg font-semibold">{metrics?.muted_count ?? 0}</p>
                            <p className="text-xs text-muted-foreground">{t('muted')}</p>
                        </CardContent>
                    </Card>
                    <Card>
                        <CardContent className="pt-3 pb-2 text-center">
                            <p className="text-lg font-semibold">{metrics?.retries_scheduled ?? 0}</p>
                            <p className="text-xs text-muted-foreground">{t('retries_scheduled')}</p>
                        </CardContent>
                    </Card>
                    <Card>
                        <CardContent className="pt-3 pb-2 text-center">
                            <p className="text-lg font-semibold">{metrics?.retries_succeeded ?? 0}</p>
                            <p className="text-xs text-muted-foreground">{t('retries_succeeded')}</p>
                        </CardContent>
                    </Card>
                </div>

                {/* Retry Queue */}
                <Card className="mb-6">
                    <CardHeader>
                        <CardTitle className="flex items-center gap-2 text-lg">
                            <Timer className="h-5 w-5 text-yellow-400" />
                            {t('retry_queue_title')}
                            {retryItems.length > 0 && (
                                <span className="ltr:ml-2 rtl:mr-2 px-2 py-0.5 bg-yellow-500/20 text-yellow-400 text-xs rounded-full">
                                    {retryItems.length}
                                </span>
                            )}
                        </CardTitle>
                        <CardDescription>
                            {t('retry_queue_desc')}
                        </CardDescription>
                    </CardHeader>
                    <CardContent>
                        {retryItems.length === 0 ? (
                            <div className="text-center py-8 text-muted-foreground">
                                <Inbox className="h-10 w-10 mx-auto mb-2 opacity-30" />
                                <p>{t('no_retry_items')}</p>
                            </div>
                        ) : (
                            <div className="overflow-x-auto">
                                <table className="w-full text-sm">
                                    <thead>
                                        <tr className="border-b border-border">
                                            <th className="ltr:text-left rtl:text-right py-2 px-3 text-muted-foreground font-medium">{t('table_sender')}</th>
                                            <th className="ltr:text-left rtl:text-right py-2 px-3 text-muted-foreground font-medium">{t('table_subject')}</th>
                                            <th className="text-center py-2 px-3 text-muted-foreground font-medium">{t('table_attempt')}</th>
                                            <th className="ltr:text-left rtl:text-right py-2 px-3 text-muted-foreground font-medium">{t('table_channel')}</th>
                                            <th className="ltr:text-left rtl:text-right py-2 px-3 text-muted-foreground font-medium">{t('table_next_retry')}</th>
                                            <th className="ltr:text-right rtl:text-left py-2 px-3 text-muted-foreground font-medium">{t('table_countdown')}</th>
                                        </tr>
                                    </thead>
                                    <tbody>
                                        {retryItems.map((item, i) => (
                                            <tr key={i} className="border-b border-border/50 hover:bg-muted/30">
                                                <td className="py-2 px-3 font-mono text-xs truncate max-w-[200px]">{item.sender || '—'}</td>
                                                <td className="py-2 px-3 truncate max-w-[250px]">{item.subject || '—'}</td>
                                                <td className="py-2 px-3 text-center">
                                                    <span className="px-2 py-0.5 bg-yellow-500/20 text-yellow-400 text-xs rounded-full">
                                                        {item.retry_count}/4
                                                    </span>
                                                </td>
                                                <td className="py-2 px-3 text-xs">{item.channel}</td>
                                                <td className="py-2 px-3 text-xs">{formatTime(item.next_retry_at)}</td>
                                                <td className="py-2 px-3 text-right">
                                                    <span className="text-yellow-400 font-mono text-xs">
                                                        {getRetryCountdown(item.next_retry_at)}
                                                    </span>
                                                </td>
                                            </tr>
                                        ))}
                                    </tbody>
                                </table>
                            </div>
                        )}
                    </CardContent>
                </Card>

                {/* DLQ */}
                <Card>
                    <CardHeader>
                        <div className="flex items-center justify-between">
                            <div>
                                <CardTitle className="flex items-center gap-2 text-lg">
                                    <XCircle className="h-5 w-5 text-red-400" />
                                    {t('dlq_title')}
                                    {dlqItems.length > 0 && (
                                        <span className="ltr:ml-2 rtl:mr-2 px-2 py-0.5 bg-red-500/20 text-red-400 text-xs rounded-full">
                                            {dlqItems.length}
                                        </span>
                                    )}
                                </CardTitle>
                                <CardDescription>
                                    {t('dlq_desc')}
                                </CardDescription>
                            </div>
                            {dlqItems.length > 0 && (
                                <Button
                                    variant="destructive"
                                    size="sm"
                                    onClick={handleFlushDlq}
                                    disabled={actionLoading === 'flush'}
                                >
                                    {actionLoading === 'flush' ? (
                                        <Loader2 className="h-4 w-4 ltr:mr-2 rtl:ml-2 animate-spin" />
                                    ) : (
                                        <Trash2 className="h-4 w-4 ltr:mr-2 rtl:ml-2" />
                                    )}
                                    {t('flush_all')}
                                </Button>
                            )}
                        </div>
                    </CardHeader>
                    <CardContent>
                        {dlqItems.length === 0 ? (
                            <div className="text-center py-8 text-muted-foreground">
                                <CheckCircle className="h-10 w-10 mx-auto mb-2 opacity-30 text-green-400" />
                                <p>{t('no_dlq_items')}</p>
                            </div>
                        ) : (
                            <div className="overflow-x-auto">
                                <table className="w-full text-sm">
                                    <thead>
                                        <tr className="border-b border-border">
                                            <th className="ltr:text-left rtl:text-right py-2 px-3 text-muted-foreground font-medium">#</th>
                                            <th className="ltr:text-left rtl:text-right py-2 px-3 text-muted-foreground font-medium">{t('table_sender')}</th>
                                            <th className="ltr:text-left rtl:text-right py-2 px-3 text-muted-foreground font-medium">{t('table_subject')}</th>
                                            <th className="text-center py-2 px-3 text-muted-foreground font-medium">{t('table_retries')}</th>
                                            <th className="ltr:text-left rtl:text-right py-2 px-3 text-muted-foreground font-medium">{t('table_failed_at')}</th>
                                            <th className="ltr:text-right rtl:text-left py-2 px-3 text-muted-foreground font-medium">{t('table_actions')}</th>
                                        </tr>
                                    </thead>
                                    <tbody>
                                        {dlqItems.map((item) => (
                                            <tr key={item.index} className="border-b border-border/50 hover:bg-muted/30">
                                                <td className="py-2 px-3 text-muted-foreground">{item.index + 1}</td>
                                                <td className="py-2 px-3 font-mono text-xs truncate max-w-[200px]">{item.sender || '—'}</td>
                                                <td className="py-2 px-3 truncate max-w-[250px]">{item.subject || '—'}</td>
                                                <td className="py-2 px-3 text-center">
                                                    <span className="px-2 py-0.5 bg-red-500/20 text-red-400 text-xs rounded-full">
                                                        {item.retry_count}/4
                                                    </span>
                                                </td>
                                                <td className="py-2 px-3 text-xs">
                                                    {formatTime(item.scheduled_at || item.queued_at)}
                                                </td>
                                                <td className="py-2 px-3 text-right">
                                                    <Button
                                                        variant="outline"
                                                        size="sm"
                                                        onClick={() => handleRequeue(item.index)}
                                                        disabled={actionLoading === `requeue-${item.index}`}
                                                    >
                                                        {actionLoading === `requeue-${item.index}` ? (
                                                            <Loader2 className="h-3 w-3 animate-spin" />
                                                        ) : (
                                                            <RotateCcw className="h-3 w-3 ltr:mr-1 rtl:ml-1" />
                                                        )}
                                                        {t('requeue')}
                                                    </Button>
                                                </td>
                                            </tr>
                                        ))}
                                    </tbody>
                                </table>
                            </div>
                        )}
                    </CardContent>
                </Card>
            </main>
        </div>
    );
}
