'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { Sidebar } from '@/components/sidebar';
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { api } from '@/lib/api';
import {
    Mail, Database, Cpu, Brain,
    AlertCircle, AlertTriangle, Bell, Info,
    Play, Pause, Send
} from 'lucide-react';

export default function DashboardPage() {
    const router = useRouter();
    const [token, setToken] = useState<string | null>(null);
    const [status, setStatus] = useState<any>(null);
    const [metrics, setMetrics] = useState<any>(null);
    const [alerts, setAlerts] = useState<any[]>([]);
    const [loading, setLoading] = useState(true);

    useEffect(() => {
        const storedToken = localStorage.getItem('sentinel_token');
        if (!storedToken) {
            router.push('/login');
            return;
        }
        setToken(storedToken);
    }, [router]);

    useEffect(() => {
        if (token) {
            loadData();
            const interval = setInterval(loadData, 10000);
            return () => clearInterval(interval);
        }
    }, [token]);

    async function loadData() {
        try {
            const [statusData, metricsData, alertsData] = await Promise.all([
                api.status(token!),
                api.metrics(token!),
                api.alerts(token!, { limit: 5 }),
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

    if (!token) return null;

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
            <main className="flex-1 ml-64 p-6">
                <div className="flex items-center justify-between mb-6">
                    <div>
                        <h1 className="text-3xl font-bold">Dashboard</h1>
                        <p className="text-muted-foreground">System overview and real-time monitoring</p>
                    </div>
                    <div className="flex gap-3">
                        <Button variant="outline" onClick={() => router.push('/smtp')}>
                            <Send className="h-4 w-4 mr-2" />
                            Test Email
                        </Button>
                    </div>
                </div>

                {loading ? (
                    <p className="text-muted-foreground">Loading...</p>
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
                                            <p className="text-sm text-muted-foreground">SMTP Ingestor</p>
                                            <p className={`font-semibold ${statusColor(status?.smtp_ingestor)}`}>
                                                {status?.smtp_ingestor || 'Unknown'}
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
                                            <p className="text-sm text-muted-foreground">Redis</p>
                                            <p className={`font-semibold ${statusColor(status?.redis)}`}>
                                                {status?.redis || 'Unknown'}
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
                                            <p className="text-sm text-muted-foreground">Processor</p>
                                            <p className={`font-semibold ${statusColor(status?.alert_processor)}`}>
                                                {status?.alert_processor || 'Unknown'}
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
                                            <p className="text-sm text-muted-foreground">Ollama AI</p>
                                            <p className={`font-semibold ${statusColor(status?.ollama)}`}>
                                                {status?.ollama || 'Unknown'}
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
                                    <p className="text-sm text-muted-foreground">Queue Depth</p>
                                </CardContent>
                            </Card>
                            <Card>
                                <CardContent className="pt-6">
                                    <p className="text-3xl font-bold text-green-400">{metrics?.processed_count || 0}</p>
                                    <p className="text-sm text-muted-foreground">Processed</p>
                                </CardContent>
                            </Card>
                            <Card>
                                <CardContent className="pt-6">
                                    <p className="text-3xl font-bold text-red-400">{metrics?.error_count || 0}</p>
                                    <p className="text-sm text-muted-foreground">Errors</p>
                                </CardContent>
                            </Card>
                            <Card>
                                <CardContent className="pt-6">
                                    <p className="text-3xl font-bold text-yellow-400">{metrics?.dlq_depth || 0}</p>
                                    <p className="text-sm text-muted-foreground">Dead Letter Queue</p>
                                </CardContent>
                            </Card>
                        </div>

                        {/* Recent Alerts */}
                        <Card>
                            <CardHeader>
                                <CardTitle>Recent Alerts</CardTitle>
                                <CardDescription>Latest processed alerts</CardDescription>
                            </CardHeader>
                            <CardContent>
                                {alerts.length === 0 ? (
                                    <p className="text-muted-foreground">No alerts yet</p>
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
                                                        <p className="font-medium text-sm">{alert.subject?.slice(0, 60) || 'No subject'}</p>
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
