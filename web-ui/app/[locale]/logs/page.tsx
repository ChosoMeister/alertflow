'use client';

import { useEffect, useState } from 'react';
import { useRouter } from '@/navigation';
import { useTranslations } from 'next-intl';
import { Sidebar } from '@/components/sidebar';
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { api } from '@/lib/api';
import { formatDate } from '@/lib/utils';
import { ScrollText, RefreshCcw } from 'lucide-react';

export default function LogsPage() {
    const router = useRouter();
    const t = useTranslations('Logs');
    const [token, setToken] = useState<string | null>(null);
    const [logs, setLogs] = useState<any[]>([]);
    const [serviceFilter, setServiceFilter] = useState<string>('');
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
    }, [token, serviceFilter]);

    async function loadLogs() {
        try {
            const data = await api.logs(token!, {
                limit: 200,
                service: serviceFilter || undefined
            });
            setLogs(data);
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
            <main className="flex-1 ltr:ml-64 rtl:mr-64 p-6">
                <div className="flex items-center justify-between mb-6">
                    <div>
                        <h1 className="text-3xl font-bold">{t('title')}</h1>
                        <p className="text-muted-foreground">{t('subtitle')}</p>
                    </div>
                    <div className="flex gap-3">
                        <select
                            value={serviceFilter}
                            onChange={(e) => setServiceFilter(e.target.value)}
                            className="h-10 px-3 rounded-md border border-input bg-background text-sm"
                        >
                            <option value="">{t('all_services')}</option>
                            <option value="smtp-ingestor">{t('smtp_ingestor')}</option>
                            <option value="alert-processor">{t('alert_processor')}</option>
                            <option value="api">{t('api')}</option>
                        </select>
                        <Button variant="outline" onClick={loadLogs}>
                            <RefreshCcw className="h-4 w-4 ltr:mr-2 rtl:ml-2" />
                            {t('refresh')}
                        </Button>
                    </div>
                </div>

                <Card>
                    <CardHeader>
                        <CardTitle className="flex items-center gap-2">
                            <ScrollText className="h-5 w-5" />
                            {t('logs_count', { count: logs.length })}
                        </CardTitle>
                    </CardHeader>
                    <CardContent>
                        {loading ? (
                            <p className="text-muted-foreground">{t('loading')}</p>
                        ) : logs.length === 0 ? (
                            <p className="text-muted-foreground">{t('no_logs')}</p>
                        ) : (
                            <div className="space-y-2 max-h-[600px] overflow-auto">
                                {logs.map((log, idx) => (
                                    <div
                                        key={idx}
                                        className="flex items-start gap-4 p-3 rounded-lg bg-muted/30 border border-border font-mono text-sm"
                                    >
                                        <span className="text-muted-foreground shrink-0 w-36">
                                            {formatDate(log.timestamp)}
                                        </span>
                                        <span className={`shrink-0 w-16 font-medium ${levelColor(log.level)}`}>
                                            {log.level}
                                        </span>
                                        <span className="text-muted-foreground shrink-0 w-32">
                                            [{log.service}]
                                        </span>
                                        <span className="flex-1">{log.message}</span>
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
