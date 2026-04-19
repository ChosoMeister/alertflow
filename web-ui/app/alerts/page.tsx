'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { Sidebar } from '@/components/sidebar';
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { api } from '@/lib/api';
import { formatDate, truncate, severityColor, statusColor } from '@/lib/utils';
import { AlertCircle, ChevronRight, RefreshCcw } from 'lucide-react';

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
    const [token, setToken] = useState<string | null>(null);
    const [alerts, setAlerts] = useState<Alert[]>([]);
    const [loading, setLoading] = useState(true);
    const [filter, setFilter] = useState<{ status?: string; severity?: string }>({});

    useEffect(() => {
        const storedToken = localStorage.getItem('sentinel_token');
        if (!storedToken) {
            router.push('/login');
            return;
        }
        setToken(storedToken);
    }, [router]);

    useEffect(() => {
        if (token) loadAlerts();
    }, [token, filter]);

    async function loadAlerts() {
        try {
            const data = await api.alerts(token!, { ...filter, limit: 100 });
            setAlerts(data);
        } catch (e) {
            console.error(e);
        } finally {
            setLoading(false);
        }
    }

    if (!token) return null;

    return (
        <div className="flex min-h-screen">
            <Sidebar />
            <main className="flex-1 ml-64 p-6">
                <div className="flex items-center justify-between mb-6">
                    <div>
                        <h1 className="text-3xl font-bold">Alerts</h1>
                        <p className="text-muted-foreground">All processed alerts</p>
                    </div>
                    <div className="flex gap-3">
                        <select
                            value={filter.severity || ''}
                            onChange={(e) => setFilter({ ...filter, severity: e.target.value || undefined })}
                            className="h-10 px-3 rounded-md border border-input bg-background text-sm"
                        >
                            <option value="">All Severities</option>
                            <option value="Critical">Critical</option>
                            <option value="High">High</option>
                            <option value="Medium">Medium</option>
                            <option value="Low">Low</option>
                            <option value="Info">Info</option>
                        </select>
                        <select
                            value={filter.status || ''}
                            onChange={(e) => setFilter({ ...filter, status: e.target.value || undefined })}
                            className="h-10 px-3 rounded-md border border-input bg-background text-sm"
                        >
                            <option value="">All Status</option>
                            <option value="new">New</option>
                            <option value="acknowledged">Acknowledged</option>
                            <option value="resolved">Resolved</option>
                        </select>
                        <Button variant="outline" onClick={loadAlerts}>
                            <RefreshCcw className="h-4 w-4 mr-2" />
                            Refresh
                        </Button>
                    </div>
                </div>

                {loading ? (
                    <p className="text-muted-foreground">Loading...</p>
                ) : alerts.length === 0 ? (
                    <Card>
                        <CardContent className="py-12 text-center">
                            <AlertCircle className="h-12 w-12 mx-auto text-muted-foreground mb-4" />
                            <p className="text-muted-foreground">No alerts found</p>
                        </CardContent>
                    </Card>
                ) : (
                    <div className="space-y-3">
                        {alerts.map((alert) => (
                            <Card
                                key={alert.id}
                                className="cursor-pointer hover:border-primary/50 transition-colors"
                                onClick={() => router.push(`/alerts/${alert.id}`)}
                            >
                                <CardContent className="py-4">
                                    <div className="flex items-center justify-between">
                                        <div className="flex items-center gap-4">
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
                                                        {alert.severity || 'Unknown'}
                                                    </span>
                                                    <span className="text-xs text-muted-foreground">
                                                        {alert.category}
                                                    </span>
                                                </div>
                                                <p className="font-medium mt-1 truncate">
                                                    {truncate(alert.subject || alert.main_message || 'No subject', 80)}
                                                </p>
                                                <p className="text-sm text-muted-foreground mt-0.5">
                                                    {alert.from_email} • {alert.system_name || 'Unknown System'}
                                                </p>
                                            </div>
                                        </div>
                                        <div className="flex items-center gap-4">
                                            <div className="text-right">
                                                <span className={`text-xs px-2 py-1 rounded border ${statusColor(alert.status)}`}>
                                                    {alert.status}
                                                </span>
                                                <p className="text-xs text-muted-foreground mt-2">
                                                    {formatDate(alert.created_at)}
                                                </p>
                                            </div>
                                            <ChevronRight className="h-5 w-5 text-muted-foreground" />
                                        </div>
                                    </div>
                                </CardContent>
                            </Card>
                        ))}
                    </div>
                )}
            </main>
        </div>
    );
}
