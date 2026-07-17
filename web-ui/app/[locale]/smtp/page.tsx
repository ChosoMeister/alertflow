'use client';

import { useEffect, useState } from 'react';
import { useRouter } from '@/navigation';
import { useTranslations } from 'next-intl';
import { Sidebar } from '@/components/sidebar';
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { api } from '@/lib/api';
import { Send, Route, CheckCircle, XCircle, ArrowRight } from 'lucide-react';
import { useToast } from '@/hooks/use-toast';

export default function SmtpDebuggerPage() {
    const router = useRouter();
    const t = useTranslations('Smtp');
    const { toast } = useToast();
    const [token, setToken] = useState<string | null>(null);

    // Form state
    const [fromEmail, setFromEmail] = useState('test@example.com');
    const [toEmail, setToEmail] = useState('alertflow@localhost');
    const [subject, setSubject] = useState('Test Alert');
    const [body, setBody] = useState('This is a test alert message.');
    const [sending, setSending] = useState(false);
    const [result, setResult] = useState<any>(null);
    const [preview, setPreview] = useState<any>(null);

    useEffect(() => {
        const storedToken = localStorage.getItem('alertflow_token');
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
            toast({ title: 'Error', description: e.message || 'Failed to preview routing', variant: 'destructive' });
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
            toast({ title: 'Success', description: t('success_msg') });
        } catch (e: any) {
            toast({ title: 'Error', description: e.message || 'Failed to send email', variant: 'destructive' });
            setResult(null);
        } finally {
            setSending(false);
        }
    }

    if (!token) return null;

    return (
        <div className="flex min-h-screen">
            <Sidebar />
            <main className="flex-1 ltr:ml-64 rtl:mr-64 p-6">
                <h1 className="text-3xl font-bold mb-2">{t('title')}</h1>
                <p className="text-muted-foreground mb-6">
                    {t('subtitle')}
                </p>

                <div className="grid gap-6 lg:grid-cols-2">
                    {/* Send Test Email */}
                    <Card>
                        <CardHeader>
                            <CardTitle className="flex items-center gap-2">
                                <Send className="h-5 w-5" />
                                {t('send_test')}
                            </CardTitle>
                            <CardDescription>
                                {t('send_desc')}
                            </CardDescription>
                        </CardHeader>
                        <CardContent className="space-y-4">
                            <div className="space-y-2">
                                <label className="text-sm font-medium">{t('from_email')}</label>
                                <Input
                                    value={fromEmail}
                                    onChange={(e) => setFromEmail(e.target.value)}
                                    placeholder={t('from_email_placeholder')}
                                />
                                <p className="text-xs text-muted-foreground">
                                    {t('from_email_desc')}
                                </p>
                            </div>

                            <div className="space-y-2">
                                <label className="text-sm font-medium">{t('to_email')}</label>
                                <Input
                                    value={toEmail}
                                    onChange={(e) => setToEmail(e.target.value)}
                                    placeholder={t('to_email_placeholder')}
                                />
                            </div>

                            <div className="space-y-2">
                                <label className="text-sm font-medium">{t('subject')}</label>
                                <Input
                                    value={subject}
                                    onChange={(e) => setSubject(e.target.value)}
                                    placeholder={t('subject_placeholder')}
                                />
                            </div>

                            <div className="space-y-2">
                                <label className="text-sm font-medium">{t('body')}</label>
                                <textarea
                                    value={body}
                                    onChange={(e) => setBody(e.target.value)}
                                    placeholder={t('body_placeholder')}
                                    rows={4}
                                    className="w-full px-3 py-2 rounded-md border border-input bg-background text-sm resize-none"
                                />
                            </div>

                            <div className="flex gap-3">
                                <Button variant="outline" onClick={previewRouting}>
                                    <Route className="h-4 w-4 ltr:mr-2 rtl:ml-2" />
                                    {t('preview_routing')}
                                </Button>
                                <Button onClick={sendTestEmail} disabled={sending}>
                                    <Send className="h-4 w-4 ltr:mr-2 rtl:ml-2" />
                                    {sending ? t('sending') : t('send')}
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
                                    {t('preview_title')}
                                </CardTitle>
                            </CardHeader>
                            <CardContent>
                                {!preview ? (
                                    <p className="text-muted-foreground text-sm">
                                        {t('preview_desc')}
                                    </p>
                                ) : (
                                    <div className="space-y-4">
                                        {preview.matched ? (
                                            <div className="flex items-start gap-3 p-3 rounded-lg bg-green-500/10 border border-green-500/30">
                                                <CheckCircle className="h-5 w-5 text-green-400 mt-0.5" />
                                                <div>
                                                    <p className="font-medium text-green-400">
                                                        {t('rule_matched')} {preview.rule_name}
                                                    </p>
                                                    <p className="text-sm text-muted-foreground mt-1">
                                                        {t('pattern')} {preview.email_pattern}
                                                    </p>
                                                </div>
                                            </div>
                                        ) : (
                                            <div className="flex items-start gap-3 p-3 rounded-lg bg-yellow-500/10 border border-yellow-500/30">
                                                <XCircle className="h-5 w-5 text-yellow-400 mt-0.5" />
                                                <div>
                                                    <p className="font-medium text-yellow-400">{t('no_rule')}</p>
                                                    <p className="text-sm text-muted-foreground mt-1">
                                                        {t('no_rule_desc')}
                                                    </p>
                                                </div>
                                            </div>
                                        )}

                                        <div className="space-y-2">
                                            <p className="text-sm font-medium">{t('destination')}</p>
                                            <div className="p-3 rounded-lg bg-muted/50 border border-border">
                                                <p className="text-sm">
                                                    <span className="text-muted-foreground">{t('channel')}</span>{' '}
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
                                        {t('email_queued')}
                                    </CardTitle>
                                </CardHeader>
                                <CardContent>
                                        <div className="space-y-3">
                                            <div className="flex items-center gap-2 text-green-400">
                                                <CheckCircle className="h-5 w-5" />
                                                <span>{t('success_msg')}</span>
                                            </div>
                                            <div className="p-3 rounded-lg bg-muted/50 border border-border">
                                                <p className="text-sm">
                                                    <span className="text-muted-foreground">{t('trace_id')}</span>{' '}
                                                    <span className="font-mono text-primary">{result.trace_id}</span>
                                                </p>
                                            </div>

                                            {result.routing_preview && (
                                                <div className="mt-4">
                                                    <p className="text-sm font-medium mb-2">{t('routing_applied')}</p>
                                                    <div className="flex items-center gap-2 text-sm">
                                                        <span className="font-mono">{fromEmail}</span>
                                                        <ArrowRight className="h-4 w-4 text-muted-foreground rotate-0 rtl:rotate-180" />
                                                        <span className={result.routing_preview.matched ? 'text-green-400' : 'text-yellow-400'}>
                                                            {result.routing_preview.matched
                                                                ? result.routing_preview.rule_name
                                                                : 'Default'}
                                                        </span>
                                                        <ArrowRight className="h-4 w-4 text-muted-foreground rotate-0 rtl:rotate-180" />
                                                        <span>{result.routing_preview.channels}</span>
                                                    </div>
                                                </div>
                                            )}
                                        </div>
                                </CardContent>
                            </Card>
                        )}
                    </div>
                </div>
            </main>
        </div>
    );
}
