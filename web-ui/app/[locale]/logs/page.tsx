'use client';

import { useEffect, useState } from 'react';
import { useRouter } from '@/navigation';
import { useTranslations } from 'next-intl';
import { Sidebar } from '@/components/sidebar';
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { api } from '@/lib/api';
import { formatDate } from '@/lib/utils';
import { ScrollText, RefreshCcw } from 'lucide-react';

export default function LogsPage() {
    const router = useRouter();
    const t = useTranslations('Logs');
    const [token, setToken] = useState<string | null>(null);
    const [logs, setLogs] = useState<any[]>([]);
    const [serviceFilter, setServiceFilter] = useState<string>('');
    const [levelFilter, setLevelFilter] = useState<string>('');
    const [sinceMinutes, setSinceMinutes] = useState<number>(60);
    const [search, setSearch] = useState('');
    const [source, setSource] = useState<'loki' | 'redis'>('loki');
    const [lokiAvailable, setLokiAvailable] = useState(true);
    const [loading, setLoading] = useState(true);

    useEffect(() => {
        const storedToken = localStorage.getItem('alertflow_token');
        if (!storedToken) {
            router.push('/login');
            return;
        }
        setToken(storedToken);
    }, [router]);

    useEffect(() => {
        if (token) loadLogs();
    }, [token, serviceFilter, levelFilter, sinceMinutes]);

    async function loadLogs() {
        try {
            setLoading(true);
            const data = await api.searchLogs(token!, {
                limit: 200,
                service: serviceFilter || undefined,
                level: levelFilter || undefined,
                q: search || undefined,
                sinceMinutes,
            });
            setLogs(data.logs);
            setSource(data.source);
            setLokiAvailable(data.available);
        } catch (e) {
            console.error(e);
        } finally {
            setLoading(false);
        }
    }

    if (!token) return null;

    const levelColor = (level: string) => {
        switch (level?.toUpperCase()) {
            case 'ERROR': return 'text-red-400';
            case 'WARNING': return 'text-yellow-400';
            case 'INFO': return 'text-blue-400';
            case 'DEBUG': return 'text-gray-400';
            default: return 'text-muted-foreground';
        }
    };

    return (
        <div className="flex min-h-screen">
            <Sidebar />
            <main className="min-w-0 max-w-full flex-1 overflow-x-hidden ltr:ml-64 rtl:mr-64 p-6">
                <div className="mb-6 flex flex-col gap-4 xl:flex-row xl:items-center xl:justify-between">
                    <div className="min-w-0">
                        <h1 className="text-3xl font-bold">{t('title')}</h1>
                        <p className="text-muted-foreground">{t('subtitle')}</p>
                    </div>
                    <div className="flex w-full min-w-0 flex-wrap gap-3 xl:w-auto xl:justify-end">
                        <Input
                            value={search}
                            onChange={(e) => setSearch(e.target.value)}
                            onKeyDown={(e) => e.key === 'Enter' && loadLogs()}
                            placeholder={t('search_placeholder')}
                            className="min-w-0 flex-1 basis-56 xl:w-56 xl:flex-none"
                        />
                        <select
                            value={serviceFilter}
                            onChange={(e) => setServiceFilter(e.target.value)}
                            className="h-10 px-3 rounded-md border border-input bg-background text-sm"
                        >
                            <option value="">{t('all_services')}</option>
                            <option value="alertflow-smtp">{t('smtp_ingestor')}</option>
                            <option value="alertflow-processor">{t('alert_processor')}</option>
                            <option value="alertflow-api">{t('api')}</option>
                            <option value="alertflow-ui">{t('ui')}</option>
                            <option value="alertflow-redis">{t('redis')}</option>
                        </select>
                        <select
                            value={levelFilter}
                            onChange={(e) => setLevelFilter(e.target.value)}
                            className="h-10 px-3 rounded-md border border-input bg-background text-sm"
                        >
                            <option value="">{t('all_levels')}</option>
                            <option value="error">ERROR</option>
                            <option value="warning">WARNING</option>
                            <option value="info">INFO</option>
                            <option value="debug">DEBUG</option>
                        </select>
                        <select
                            value={sinceMinutes}
                            onChange={(e) => setSinceMinutes(Number(e.target.value))}
                            className="h-10 px-3 rounded-md border border-input bg-background text-sm"
                        >
                            <option value={15}>{t('last_15m')}</option>
                            <option value={60}>{t('last_1h')}</option>
                            <option value={360}>{t('last_6h')}</option>
                            <option value={1440}>{t('last_24h')}</option>
                            <option value={4320}>{t('last_3d')}</option>
                        </select>
                        <Button variant="outline" onClick={loadLogs}>
                            <RefreshCcw className="h-4 w-4 ltr:mr-2 rtl:ml-2" />
                            {t('refresh')}
                        </Button>
                    </div>
                </div>

                <Card className="min-w-0 max-w-full overflow-hidden">
                    <CardHeader>
                        <CardTitle className="flex items-center gap-2">
                            <ScrollText className="h-5 w-5" />
                            {t('logs_count', { count: logs.length })}
                            <span className={`text-xs px-2 py-1 rounded-full ${lokiAvailable ? 'bg-emerald-500/10 text-emerald-400' : 'bg-yellow-500/10 text-yellow-400'}`}>
                                {source === 'loki' ? 'Loki' : t('redis_fallback')}
                            </span>
                        </CardTitle>
                    </CardHeader>
                    <CardContent>
                        {loading ? (
                            <p className="text-muted-foreground">{t('loading')}</p>
                        ) : logs.length === 0 ? (
                            <p className="text-muted-foreground">{t('no_logs')}</p>
                        ) : (
                            <div className="max-h-[600px] min-w-0 space-y-2 overflow-x-hidden overflow-y-auto">
                                {logs.map((log, idx) => (
                                    <div
                                        key={idx}
                                        dir="ltr"
                                        className="grid min-w-0 grid-cols-1 gap-1 rounded-lg border border-border bg-muted/30 p-3 text-left font-mono text-sm md:grid-cols-[11.5rem_5rem_10rem_minmax(0,1fr)] md:gap-3"
                                    >
                                        <span className="min-w-0 whitespace-nowrap text-muted-foreground">
                                            {formatDate(log.timestamp)}
                                        </span>
                                        <span className={`min-w-0 font-medium ${levelColor(log.level)}`}>
                                            {log.level}
                                        </span>
                                        <span className="min-w-0 truncate text-muted-foreground" title={log.service}>
                                            [{log.service}]
                                        </span>
                                        <span className="min-w-0 whitespace-pre-wrap break-words [overflow-wrap:anywhere]">
                                            {log.message}
                                        </span>
                                    </div>
                                ))}
                            </div>
                        )}
                    </CardContent>
                </Card>
            </main>
        </div>
    );
}
