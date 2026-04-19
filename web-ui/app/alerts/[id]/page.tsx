'use client';

import { useEffect, useState } from 'react';
import { useRouter, useParams } from 'next/navigation';
import { Sidebar } from '@/components/sidebar';
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { api } from '@/lib/api';
import { formatDate, severityColor, statusColor } from '@/lib/utils';
import { ArrowLeft, RefreshCcw, Send, Brain, Check, Clock } from 'lucide-react';

export default function AlertDetailPage() {
    const router = useRouter();
    const params = useParams();
    const alertId = params.id as string;
    const [token, setToken] = useState<string | null>(null);
    const [alert, setAlert] = useState<any>(null);
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
        if (token && alertId) loadAlert();
    }, [token, alertId]);

    async function loadAlert() {
        try {
            const data = await api.alert(token!, alertId);
            setAlert(data);
        } catch (e) {
            console.error(e);
        } finally {
            setLoading(false);
        }
    }

    async function updateStatus(status: string) {
        try {
            await api.updateAlertStatus(token!, alertId, status);
            loadAlert();
        } catch (e) {
            console.error(e);
        }
    }

    async function rerunAI() {
        try {
            await api.rerunAI(token!, alertId);
            alert && window.alert('Alert queued for re-analysis');
        } catch (e: any) {
            window.alert(e.message);
        }
    }

    async function resend() {
        try {
            await api.resendAlert(token!, alertId);
            alert && window.alert('Alert queued for resend');
        } catch (e: any) {
            window.alert(e.message);
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
                            </CardContent>
                        </Card>

                        {/* Details */}
                        <div className="grid gap-6 lg:grid-cols-2">
                            <Card>
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
                        </div>

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
