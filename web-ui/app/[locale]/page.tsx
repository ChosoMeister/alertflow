'use client';

import { useEffect, useState, useRef } from 'react';
import { useRouter } from '@/navigation';
import { useTranslations } from 'next-intl';
import { useAuth } from '@/hooks/use-auth';
import { Sidebar } from '@/components/sidebar';
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { api } from '@/lib/api';
import {
    Mail, Database, Cpu, Brain,
    AlertCircle, AlertTriangle, Bell, Info,
    Play, Pause, Send, Wifi, WifiOff
} from 'lucide-react';

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

export default function DashboardPage() {
    const router = useRouter();
    const t = useTranslations('Dashboard');
    const { token, isLoading: authLoading } = useAuth();
    const [status, setStatus] = useState<any>(null);
    const [metrics, setMetrics] = useState<any>(null);
    const [alerts, setAlerts] = useState<any[]>([]);
    const [loading, setLoading] = useState(true);
    const [isLive, setIsLive] = useState(false);
    const eventSourceRef = useRef<EventSource | null>(null);

    useEffect(() => {
        if (!token) return;

        // Try SSE first
        const sseUrl = `${API_URL}/api/sse/dashboard?token=${token}`;
        const es = new EventSource(sseUrl);
        eventSourceRef.current = es;

        es.onmessage = (event) => {
            try {
                const data = JSON.parse(event.data);
                if (data.error) return;
                setStatus(data.status);
                setMetrics(data.metrics);
                setAlerts(data.alerts || []);
                setLoading(false);
                setIsLive(true);
            } catch {
                // ignore parse errors
            }
        };

        es.onerror = () => {
            // SSE failed — fallback to polling
            es.close();
            setIsLive(false);
            fallbackPolling();
        };

        return () => {
            es.close();
            eventSourceRef.current = null;
        };
    }, [token]);

    function fallbackPolling() {
        loadData();
        const interval = setInterval(loadData, 10000);
        // Store cleanup in ref
        return () => clearInterval(interval);
    }

    async function loadData() {
        if (!token) return;
        try {
            const [statusData, metricsData, alertsData] = await Promise.all([
                api.status(token),
                api.metrics(token),
                api.alerts(token, { limit: 5 }),
            ]);
            setStatus(statusData);
            setMetrics(metricsData);
            setAlerts(alertsData);
        } catch (e) {
            console.error(e);
        } finally {
            setLoading(false);
        }
    }

    if (authLoading || !token) return null;


    const statusColor = (s: string) => {
        switch (s) {
            case 'online': return 'text-green-400';
            case 'offline': return 'text-red-400';
            default: return 'text-yellow-400';
        }
    };

    return (
        <div className="flex min-h-screen">
            <Sidebar />
            <main className="flex-1 ltr:ml-64 rtl:mr-64 p-6">
                <div className="flex items-center justify-between mb-6">
                    <div>
                        <h1 className="text-3xl font-bold">{t('title')}</h1>
                        <p className="text-muted-foreground">{t('subtitle')}</p>
                    </div>
                    <div className="flex gap-3 items-center">
                        <span className={`flex items-center gap-1.5 text-xs px-2.5 py-1 rounded-full ${isLive ? 'bg-green-500/15 text-green-400' : 'bg-yellow-500/15 text-yellow-400'}`}>
                            {isLive ? <Wifi className="h-3 w-3" /> : <WifiOff className="h-3 w-3" />}
                            {isLive ? 'Live' : 'Polling'}
                        </span>
                        <Button variant="outline" onClick={() => router.push('/smtp')}>
                            <Send className="h-4 w-4 ltr:mr-2 rtl:ml-2" />
                            {t('test_email')}
                        </Button>
                    </div>
                </div>

                {loading ? (
                    <p className="text-muted-foreground">{t('loading')}</p>
                ) : (
                    <div className="space-y-6">
                        {/* System Health */}
                        <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
                            <Card>
                                <CardContent className="pt-6">
                                    <div className="flex items-center gap-4">
                                        <div className="p-3 rounded-lg bg-blue-500/10">
                                            <Mail className="h-6 w-6 text-blue-400" />
                                        </div>
                                        <div>
                                            <p className="text-sm text-muted-foreground">{t('smtp_ingestor')}</p>
                                            <p className={`font-semibold ${statusColor(status?.smtp_ingestor)}`}>
                                                {status?.smtp_ingestor || t('unknown')}
                                            </p>
                                        </div>
                                    </div>
                                </CardContent>
                            </Card>

                            <Card>
                                <CardContent className="pt-6">
                                    <div className="flex items-center gap-4">
                                        <div className="p-3 rounded-lg bg-purple-500/10">
                                            <Database className="h-6 w-6 text-purple-400" />
                                        </div>
                                        <div>
                                            <p className="text-sm text-muted-foreground">{t('redis')}</p>
                                            <p className={`font-semibold ${statusColor(status?.redis)}`}>
                                                {status?.redis || t('unknown')}
                                            </p>
                                        </div>
                                    </div>
                                </CardContent>
                            </Card>

                            <Card>
                                <CardContent className="pt-6">
                                    <div className="flex items-center gap-4">
                                        <div className="p-3 rounded-lg bg-green-500/10">
                                            <Cpu className="h-6 w-6 text-green-400" />
                                        </div>
                                        <div>
                                            <p className="text-sm text-muted-foreground">{t('processor')}</p>
                                            <p className={`font-semibold ${statusColor(status?.alert_processor)}`}>
                                                {status?.alert_processor || t('unknown')}
                                            </p>
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
                                            <p className="text-sm text-muted-foreground">{t('ollama_ai')}</p>
                                            <p className={`font-semibold ${statusColor(status?.ollama)}`}>
                                                {status?.ollama || t('unknown')}
                                            </p>
                                        </div>
                                    </div>
                                </CardContent>
                            </Card>
                        </div>

                        {/* Queue Metrics */}
                        <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
                            <Card>
                                <CardContent className="pt-6">
                                    <p className="text-3xl font-bold text-primary">{metrics?.queue_depth || 0}</p>
                                    <p className="text-sm text-muted-foreground">{t('queue_depth')}</p>
                                </CardContent>
                            </Card>
                            <Card>
                                <CardContent className="pt-6">
                                    <p className="text-3xl font-bold text-green-400">{metrics?.processed_count || 0}</p>
                                    <p className="text-sm text-muted-foreground">{t('processed')}</p>
                                </CardContent>
                            </Card>
                            <Card>
                                <CardContent className="pt-6">
                                    <p className="text-3xl font-bold text-red-400">{metrics?.error_count || 0}</p>
                                    <p className="text-sm text-muted-foreground">{t('errors')}</p>
                                </CardContent>
                            </Card>
                            <Card>
                                <CardContent className="pt-6">
                                    <p className="text-3xl font-bold text-yellow-400">{metrics?.dlq_depth || 0}</p>
                                    <p className="text-sm text-muted-foreground">{t('dlq')}</p>
                                </CardContent>
                            </Card>
                        </div>

                        {/* Recent Alerts */}
                        <Card>
                            <CardHeader>
                                <CardTitle>{t('recent_alerts')}</CardTitle>
                                <CardDescription>{t('recent_alerts_desc')}</CardDescription>
                            </CardHeader>
                            <CardContent>
                                {alerts.length === 0 ? (
                                    <p className="text-muted-foreground">{t('no_alerts')}</p>
                                ) : (
                                    <div className="space-y-3">
                                        {alerts.map((alert) => (
                                            <div
                                                key={alert.id}
                                                className="flex items-center justify-between p-3 rounded-lg border border-border bg-muted/30 cursor-pointer hover:bg-muted/50"
                                                onClick={() => router.push(`/alerts/${alert.id}`)}
                                            >
                                                <div className="flex items-center gap-3">
                                                    <div className={`p-2 rounded-lg ${alert.severity === 'Critical' ? 'bg-red-500/10' :
                                                            alert.severity === 'High' ? 'bg-orange-500/10' :
                                                                alert.severity === 'Medium' ? 'bg-yellow-500/10' :
                                                                    'bg-blue-500/10'
                                                        }`}>
                                                        <AlertCircle className={`h-4 w-4 ${alert.severity === 'Critical' ? 'text-red-400' :
                                                                alert.severity === 'High' ? 'text-orange-400' :
                                                                    alert.severity === 'Medium' ? 'text-yellow-400' :
                                                                        'text-blue-400'
                                                            }`} />
                                                    </div>
                                                    <div>
                                                        <p className="font-medium text-sm">{alert.subject?.slice(0, 60) || t('no_subject')}</p>
                                                        <p className="text-xs text-muted-foreground">{alert.from_email}</p>
                                                    </div>
                                                </div>
                                                <div className="text-right">
                                                    <span className={`text-xs px-2 py-1 rounded ${alert.status === 'new' ? 'bg-blue-500/20 text-blue-400' :
                                                            alert.status === 'acknowledged' ? 'bg-yellow-500/20 text-yellow-400' :
                                                                'bg-green-500/20 text-green-400'
                                                        }`}>
                                                        {alert.status}
                                                    </span>
                                                </div>
                                            </div>
                                        ))}
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
