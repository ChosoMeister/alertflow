'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { Sidebar } from '@/components/sidebar';
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { api } from '@/lib/api';
import { Send, Route, CheckCircle, XCircle, ArrowRight } from 'lucide-react';

export default function SmtpDebuggerPage() {
    const router = useRouter();
    const [token, setToken] = useState<string | null>(null);

    // Form state
    const [fromEmail, setFromEmail] = useState('test@example.com');
    const [toEmail, setToEmail] = useState('sentinel@localhost');
    const [subject, setSubject] = useState('Test Alert');
    const [body, setBody] = useState('This is a test alert message.');
    const [sending, setSending] = useState(false);
    const [result, setResult] = useState<any>(null);
    const [preview, setPreview] = useState<any>(null);

    useEffect(() => {
        const storedToken = localStorage.getItem('sentinel_token');
        if (!storedToken) {
            router.push('/login');
            return;
        }
        setToken(storedToken);
    }, [router]);

    async function previewRouting() {
        if (!token) return;
        try {
            const routing = await api.previewRouting(token, {
                from_email: fromEmail,
                to_email: toEmail,
                subject,
                body,
            });
            setPreview(routing);
        } catch (e: any) {
            console.error(e);
        }
    }

    async function sendTestEmail() {
        if (!token) return;
        setSending(true);
        setResult(null);
        try {
            const res = await api.sendTestEmail(token, {
                from_email: fromEmail,
                to_email: toEmail,
                subject,
                body,
            });
            setResult(res);
        } catch (e: any) {
            setResult({ error: e.message });
        } finally {
            setSending(false);
        }
    }

    if (!token) return null;

    return (
        <div className="flex min-h-screen">
            <Sidebar />
            <main className="flex-1 ml-64 p-6">
                <h1 className="text-3xl font-bold mb-2">SMTP Debugger</h1>
                <p className="text-muted-foreground mb-6">
                    Send test emails and preview routing before sending
                </p>

                <div className="grid gap-6 lg:grid-cols-2">
                    {/* Send Test Email */}
                    <Card>
                        <CardHeader>
                            <CardTitle className="flex items-center gap-2">
                                <Send className="h-5 w-5" />
                                Send Test Email
                            </CardTitle>
                            <CardDescription>
                                Queue a test email for processing
                            </CardDescription>
                        </CardHeader>
                        <CardContent className="space-y-4">
                            <div className="space-y-2">
                                <label className="text-sm font-medium">FROM Email</label>
                                <Input
                                    value={fromEmail}
                                    onChange={(e) => setFromEmail(e.target.value)}
                                    placeholder="alert@zabbix.local"
                                />
                                <p className="text-xs text-muted-foreground">
                                    This determines routing rules (sender pattern matching)
                                </p>
                            </div>

                            <div className="space-y-2">
                                <label className="text-sm font-medium">TO Email</label>
                                <Input
                                    value={toEmail}
                                    onChange={(e) => setToEmail(e.target.value)}
                                    placeholder="sentinel@localhost"
                                />
                            </div>

                            <div className="space-y-2">
                                <label className="text-sm font-medium">Subject</label>
                                <Input
                                    value={subject}
                                    onChange={(e) => setSubject(e.target.value)}
                                    placeholder="[CRITICAL] Server Down"
                                />
                            </div>

                            <div className="space-y-2">
                                <label className="text-sm font-medium">Body</label>
                                <textarea
                                    value={body}
                                    onChange={(e) => setBody(e.target.value)}
                                    placeholder="Alert message content..."
                                    rows={4}
                                    className="w-full px-3 py-2 rounded-md border border-input bg-background text-sm resize-none"
                                />
                            </div>

                            <div className="flex gap-3">
                                <Button variant="outline" onClick={previewRouting}>
                                    <Route className="h-4 w-4 mr-2" />
                                    Preview Routing
                                </Button>
                                <Button onClick={sendTestEmail} disabled={sending}>
                                    <Send className="h-4 w-4 mr-2" />
                                    {sending ? 'Sending...' : 'Send'}
                                </Button>
                            </div>
                        </CardContent>
                    </Card>

                    {/* Routing Preview + Result */}
                    <div className="space-y-6">
                        {/* Routing Preview */}
                        <Card>
                            <CardHeader>
                                <CardTitle className="flex items-center gap-2">
                                    <Route className="h-5 w-5" />
                                    Routing Preview
                                </CardTitle>
                            </CardHeader>
                            <CardContent>
                                {!preview ? (
                                    <p className="text-muted-foreground text-sm">
                                        Click "Preview Routing" to see where this email would be sent
                                    </p>
                                ) : (
                                    <div className="space-y-4">
                                        {preview.matched ? (
                                            <div className="flex items-start gap-3 p-3 rounded-lg bg-green-500/10 border border-green-500/30">
                                                <CheckCircle className="h-5 w-5 text-green-400 mt-0.5" />
                                                <div>
                                                    <p className="font-medium text-green-400">
                                                        Rule Matched: {preview.rule_name}
                                                    </p>
                                                    <p className="text-sm text-muted-foreground mt-1">
                                                        Pattern: {preview.email_pattern}
                                                    </p>
                                                </div>
                                            </div>
                                        ) : (
                                            <div className="flex items-start gap-3 p-3 rounded-lg bg-yellow-500/10 border border-yellow-500/30">
                                                <XCircle className="h-5 w-5 text-yellow-400 mt-0.5" />
                                                <div>
                                                    <p className="font-medium text-yellow-400">No Rule Matched</p>
                                                    <p className="text-sm text-muted-foreground mt-1">
                                                        Using default destinations
                                                    </p>
                                                </div>
                                            </div>
                                        )}

                                        <div className="space-y-2">
                                            <p className="text-sm font-medium">Destination:</p>
                                            <div className="p-3 rounded-lg bg-muted/50 border border-border">
                                                <p className="text-sm">
                                                    <span className="text-muted-foreground">Channel:</span>{' '}
                                                    <span className="font-mono">{preview.channels}</span>
                                                </p>
                                                {preview.telegram_chat_id && (
                                                    <p className="text-sm mt-1">
                                                        <span className="text-muted-foreground">Telegram:</span>{' '}
                                                        <span className="font-mono">{preview.telegram_chat_id}</span>
                                                        {preview.telegram_thread_id && preview.telegram_thread_id !== '0' &&
                                                            <span className="text-muted-foreground"> (thread {preview.telegram_thread_id})</span>
                                                        }
                                                    </p>
                                                )}
                                                {preview.matrix_room_id && (
                                                    <p className="text-sm mt-1">
                                                        <span className="text-muted-foreground">Matrix:</span>{' '}
                                                        <span className="font-mono">{preview.matrix_room_id}</span>
                                                    </p>
                                                )}
                                            </div>
                                        </div>
                                    </div>
                                )}
                            </CardContent>
                        </Card>

                        {/* Send Result */}
                        {result && (
                            <Card>
                                <CardHeader>
                                    <CardTitle>
                                        {result.error ? 'Error' : 'Email Queued'}
                                    </CardTitle>
                                </CardHeader>
                                <CardContent>
                                    {result.error ? (
                                        <div className="p-3 rounded-lg bg-red-500/10 border border-red-500/30 text-red-400">
                                            {result.error}
                                        </div>
                                    ) : (
                                        <div className="space-y-3">
                                            <div className="flex items-center gap-2 text-green-400">
                                                <CheckCircle className="h-5 w-5" />
                                                <span>Email queued successfully!</span>
                                            </div>
                                            <div className="p-3 rounded-lg bg-muted/50 border border-border">
                                                <p className="text-sm">
                                                    <span className="text-muted-foreground">Trace ID:</span>{' '}
                                                    <span className="font-mono text-primary">{result.trace_id}</span>
                                                </p>
                                            </div>

                                            {result.routing_preview && (
                                                <div className="mt-4">
                                                    <p className="text-sm font-medium mb-2">Routing Applied:</p>
                                                    <div className="flex items-center gap-2 text-sm">
                                                        <span className="font-mono">{fromEmail}</span>
                                                        <ArrowRight className="h-4 w-4 text-muted-foreground" />
                                                        <span className={result.routing_preview.matched ? 'text-green-400' : 'text-yellow-400'}>
                                                            {result.routing_preview.matched
                                                                ? result.routing_preview.rule_name
                                                                : 'Default'}
                                                        </span>
                                                        <ArrowRight className="h-4 w-4 text-muted-foreground" />
                                                        <span>{result.routing_preview.channels}</span>
                                                    </div>
                                                </div>
                                            )}
                                        </div>
                                    )}
                                </CardContent>
                            </Card>
                        )}
                    </div>
                </div>
            </main>
        </div>
    );
}
