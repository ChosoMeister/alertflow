'use client';

import { useEffect, useState } from 'react';
import { useParams } from 'next/navigation';
import { useRouter } from '@/navigation';
import { Sidebar } from '@/components/sidebar';
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { api } from '@/lib/api';
import { formatDate, severityColor, statusColor } from '@/lib/utils';
import { ArrowLeft, RefreshCcw, Send, Brain, Check, Clock, Activity } from 'lucide-react';
import { useToast } from '@/hooks/use-toast';

export default function AlertDetailPage() {
    const router = useRouter();
    const params = useParams();
    const alertId = params.id as string;
    const { toast } = useToast();
    const [token, setToken] = useState<string | null>(null);
    const [alert, setAlert] = useState<any>(null);
    const [timeline, setTimeline] = useState<any[]>([]);
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
        if (token && alertId) loadAlert();
    }, [token, alertId]);

    async function loadAlert() {
        try {
            const [data, timelineData] = await Promise.all([
                api.alert(token!, alertId), api.alertTimeline(token!, alertId),
            ]);
            setAlert(data);
            setTimeline(timelineData.events || []);
        } catch (e) {
            console.error(e);
        } finally {
            setLoading(false);
        }
    }

    async function updateStatus(status: string) {
        try {
            await api.updateAlertStatus(token!, alertId, status);
            toast({ title: 'Success', description: `Status updated to ${status}` });
            loadAlert();
        } catch (e: any) {
            toast({ title: 'Error', description: e.message || 'Failed to update status', variant: 'destructive' });
        }
    }

    async function rerunAI() {
        try {
            await api.rerunAI(token!, alertId);
            toast({ title: 'Success', description: 'Alert queued for re-analysis' });
        } catch (e: any) {
            toast({ title: 'Error', description: e.message, variant: 'destructive' });
        }
    }

    async function resend() {
        try {
            await api.resendAlert(token!, alertId);
            toast({ title: 'Success', description: 'Alert queued for resend' });
        } catch (e: any) {
            toast({ title: 'Error', description: e.message, variant: 'destructive' });
        }
    }

    if (!token) return null;

    return (
        <div className="flex min-h-screen">
            <Sidebar />
            <main className="flex-1 ml-64 p-6">
                <Button variant="ghost" onClick={() => router.push('/alerts')} className="mb-4">
                    <ArrowLeft className="h-4 w-4 mr-2" />
                    Back to Alerts
                </Button>

                {loading ? (
                    <p className="text-muted-foreground">Loading...</p>
                ) : !alert ? (
                    <p className="text-muted-foreground">Alert not found</p>
                ) : (
                    <div className="space-y-6">
                        {/* Header */}
                        <div className="flex items-center justify-between">
                            <div>
                                <div className="flex items-center gap-3 mb-2">
                                    <span className={`px-2 py-1 rounded text-sm font-medium ${severityColor(alert.severity)}`}>
                                        {alert.severity || 'Unknown'}
                                    </span>
                                    <span className="text-muted-foreground">{alert.category || 'Unknown'}</span>
                                    <span className={`px-2 py-1 rounded text-xs border ${statusColor(alert.status)}`}>
                                        {alert.status}
                                    </span>
                                </div>
                                <h1 className="text-2xl font-bold">{alert.subject || 'No subject'}</h1>
                            </div>
                            <div className="flex gap-2">
                                <Button variant="outline" size="sm" onClick={rerunAI}>
                                    <Brain className="h-4 w-4 mr-2" />
                                    Re-run AI
                                </Button>
                                <Button variant="outline" size="sm" onClick={resend}>
                                    <Send className="h-4 w-4 mr-2" />
                                    Resend
                                </Button>
                            </div>
                        </div>

                        {/* Status Actions */}
                        <Card>
                            <CardContent className="pt-6">
                                {alert.system_resolved === 'true' ? (
                                    <div className="bg-muted p-4 rounded-lg flex items-center gap-3">
                                        <Check className="h-5 w-5 text-green-500" />
                                        <div className="text-sm">
                                            <p className="font-medium text-foreground">System Resolved</p>
                                            <p className="text-muted-foreground mt-0.5">This alert has been automatically resolved by the monitoring system. Manual status updates are disabled.</p>
                                        </div>
                                    </div>
                                ) : (
                                    <div className="flex items-center gap-3">
                                        <span className="text-sm text-muted-foreground">Update Status:</span>
                                        <Button
                                            size="sm"
                                            variant={alert.status === 'new' ? 'default' : 'outline'}
                                            onClick={() => updateStatus('new')}
                                        >
                                            <Clock className="h-4 w-4 mr-1" />
                                            New
                                        </Button>
                                        <Button
                                            size="sm"
                                            variant={alert.status === 'acknowledged' ? 'default' : 'outline'}
                                            onClick={() => updateStatus('acknowledged')}
                                        >
                                            <RefreshCcw className="h-4 w-4 mr-1" />
                                            Acknowledged
                                        </Button>
                                        <Button
                                            size="sm"
                                            variant={alert.status === 'resolved' ? 'default' : 'outline'}
                                            onClick={() => updateStatus('resolved')}
                                        >
                                            <Check className="h-4 w-4 mr-1" />
                                            Resolved
                                        </Button>
                                    </div>
                                )}
                            </CardContent>
                        </Card>

                        {/* Details */}
                        <div className="grid gap-6 lg:grid-cols-3">
                            <Card className="lg:col-span-2">
                                <CardHeader>
                                    <CardTitle>Email Details</CardTitle>
                                </CardHeader>
                                <CardContent className="space-y-3">
                                    <div>
                                        <p className="text-sm text-muted-foreground">From</p>
                                        <p className="font-mono">{alert.from_email}</p>
                                    </div>
                                    <div>
                                        <p className="text-sm text-muted-foreground">To</p>
                                        <p className="font-mono">{alert.to_email}</p>
                                    </div>
                                    <div>
                                        <p className="text-sm text-muted-foreground">Received</p>
                                        <p>{formatDate(alert.created_at)}</p>
                                    </div>
                                    <div>
                                        <p className="text-sm text-muted-foreground">Channel</p>
                                        <p>{alert.channel}</p>
                                    </div>
                                </CardContent>
                            </Card>

                            <div className="space-y-6">
                                <Card>
                                    <CardHeader>
                                        <CardTitle>AI Analysis</CardTitle>
                                    </CardHeader>
                                    <CardContent className="space-y-3">
                                        <div>
                                            <p className="text-sm text-muted-foreground">System</p>
                                            <p>{alert.system_name || '-'}</p>
                                        </div>
                                        <div>
                                            <p className="text-sm text-muted-foreground">Summary</p>
                                            <p>{alert.main_message || '-'}</p>
                                        </div>
                                        <div>
                                            <p className="text-sm text-muted-foreground">Details</p>
                                            <p className="text-sm">{alert.details || '-'}</p>
                                        </div>
                                        <div>
                                            <p className="text-sm text-muted-foreground">Confidence</p>
                                            <p>{alert.confidence ? `${(parseFloat(alert.confidence) * 100).toFixed(0)}%` : '-'}</p>
                                        </div>
                                    </CardContent>
                                </Card>

                                <Card>
                                    <CardHeader>
                                        <CardTitle>Channel Delivery</CardTitle>
                                    </CardHeader>
                                    <CardContent className="space-y-3">
                                        {Object.keys(alert.delivery || {}).length === 0 ? (
                                            <p className="text-sm text-muted-foreground">No delivery state recorded</p>
                                        ) : Object.entries(alert.delivery).map(([channelId, raw]: [string, any]) => (
                                            <div key={channelId} className="rounded border p-2">
                                                <div className="flex items-center justify-between gap-2">
                                                    <span className="font-mono text-xs break-all">{channelId}</span>
                                                    <span className={`text-xs font-medium ${raw.status === 'delivered' ? 'text-green-400' : 'text-red-400'}`}>
                                                        {raw.status}
                                                    </span>
                                                </div>
                                                <p className="mt-1 text-xs text-muted-foreground">Attempt {raw.attempt || 1} · {raw.detail || '-'}</p>
                                            </div>
                                        ))}
                                    </CardContent>
                                </Card>

                                <Card>
                                    <CardHeader>
                                        <CardTitle>Incident Correlation</CardTitle>
                                    </CardHeader>
                                    <CardContent className="space-y-3">
                                        <div>
                                            <p className="text-sm text-muted-foreground">Incident Key</p>
                                            <p className="font-mono text-xs break-all bg-muted p-1 rounded mt-1">
                                                {alert.incident_key || '-'}
                                            </p>
                                        </div>
                                        <div>
                                            <p className="text-sm text-muted-foreground">Correlation Action</p>
                                            <span className={`inline-block mt-1 px-2 py-1 rounded text-xs border ${
                                                alert.correlation_action === 'MERGE' ? 'bg-purple-500/20 text-purple-400 border-purple-500/30' :
                                                alert.correlation_action === 'IGNORE' ? 'bg-gray-700/20 text-gray-500 border-gray-700/30' :
                                                'bg-blue-500/20 text-blue-400 border-blue-500/30'
                                            }`}>
                                                {alert.correlation_action || 'NEW'}
                                            </span>
                                        </div>
                                    </CardContent>
                                </Card>
                            </div>
                        </div>

                        <Card>
                            <CardHeader>
                                <CardTitle className="flex items-center gap-2"><Activity className="h-5 w-5" />Incident Timeline</CardTitle>
                            </CardHeader>
                            <CardContent>
                                {timeline.length === 0 ? <p className="text-sm text-muted-foreground">No events recorded</p> : (
                                    <div className="space-y-3">
                                        {timeline.map((event: any, idx: number) => (
                                            <div key={`${event.id || event.occurred_at}-${idx}`} className="grid grid-cols-[10rem_7rem_1fr] gap-3 rounded border p-3 text-sm">
                                                <span className="text-muted-foreground">{event.occurred_at ? formatDate(event.occurred_at) : '-'}</span>
                                                <span className="font-medium">{event.type || event.action}</span>
                                                <div className="min-w-0">
                                                    <span className="break-words">{event.detail || event.status || '-'}</span>
                                                    {event.actor && <span className="ml-2 text-muted-foreground">by {event.actor}</span>}
                                                    {event.channel_id && <span className="ml-2 font-mono text-xs text-muted-foreground">{event.channel_id}</span>}
                                                </div>
                                            </div>
                                        ))}
                                    </div>
                                )}
                            </CardContent>
                        </Card>

                        {/* Action History Log */}
                        {alert.action_history && (() => {
                            let history = [];
                            try {
                                history = JSON.parse(alert.action_history);
                            } catch (e) {}

                            if (history.length === 0) return null;

                            return (
                                <Card>
                                    <CardHeader>
                                        <CardTitle>User Action Log</CardTitle>
                                    </CardHeader>
                                    <CardContent>
                                        <div className="space-y-4">
                                            {history.map((act: any, idx: number) => (
                                                <div key={idx} className="flex gap-4">
                                                    <div className="flex flex-col items-center">
                                                        <div className={`h-8 w-8 rounded-full flex items-center justify-center ${
                                                            act.status === 'acknowledged' ? 'bg-blue-500/10 text-blue-500' :
                                                            act.status === 'resolved' ? 'bg-green-500/10 text-green-500' :
                                                            'bg-gray-500/10 text-gray-500'
                                                        }`}>
                                                            {act.status === 'acknowledged' ? <RefreshCcw className="h-4 w-4" /> :
                                                             act.status === 'resolved' ? <Check className="h-4 w-4" /> :
                                                             <Clock className="h-4 w-4" />}
                                                        </div>
                                                        {idx !== history.length - 1 && (
                                                            <div className="w-px h-full bg-border mt-2"></div>
                                                        )}
                                                    </div>
                                                    <div className="pb-4">
                                                        <p className="text-sm font-medium">
                                                            {act.status === 'acknowledged' ? 'Acknowledged' :
                                                             act.status === 'resolved' ? 'Resolved' : 'Reverted to New'}
                                                        </p>
                                                        <p className="text-sm text-muted-foreground mt-0.5">
                                                            by <span className="font-medium text-foreground">{act.user}</span> at {act.timestamp}
                                                        </p>
                                                    </div>
                                                </div>
                                            ))}
                                        </div>
                                    </CardContent>
                                </Card>
                            );
                        })()}

                        {/* Body */}
                        <Card>
                            <CardHeader>
                                <CardTitle>Email Body</CardTitle>
                            </CardHeader>
                            <CardContent>
                                <pre className="p-4 rounded-lg bg-muted/50 text-sm whitespace-pre-wrap overflow-auto max-h-96">
                                    {alert.body || 'No body content'}
                                </pre>
                            </CardContent>
                        </Card>
                    </div>
                )}
            </main>
        </div>
    );
}
