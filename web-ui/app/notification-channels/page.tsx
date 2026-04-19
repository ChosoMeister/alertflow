'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { Sidebar } from '@/components/sidebar';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { api } from '@/lib/api';
import { Plus, Trash2, TestTube, Send, MessageSquare, Globe, Phone, Loader2 } from 'lucide-react';
import { useToast } from '@/hooks/use-toast';

interface NotificationChannel {
    id: string;
    name: string;
    type: string;
    config: Record<string, any>;
    is_default: boolean;
}

const CHANNEL_TYPES = [
    { value: 'telegram', label: 'Telegram', icon: Send },
    { value: 'matrix', label: 'Matrix', icon: MessageSquare },
    { value: 'sms', label: 'SMS (Kavenegar)', icon: Phone },
    { value: 'webhook', label: 'Webhook', icon: Globe },
];

export default function NotificationChannelsPage() {
    const router = useRouter();
    const { toast } = useToast();
    const [channels, setChannels] = useState<NotificationChannel[]>([]);
    const [loading, setLoading] = useState(true);
    const [showForm, setShowForm] = useState(false);
    const [editing, setEditing] = useState<NotificationChannel | null>(null);
    const [testing, setTesting] = useState<string | null>(null);

    const [formData, setFormData] = useState({
        name: '',
        type: 'telegram',
        is_default: false,
        config: {} as Record<string, any>,
    });

    useEffect(() => {
        const token = localStorage.getItem('sentinel_token');
        if (!token) {
            router.push('/login');
            return;
        }
        loadChannels();
    }, []);

    async function loadChannels() {
        const token = localStorage.getItem('sentinel_token');
        if (!token) return;
        try {
            const data = await api.notificationChannels(token);
            setChannels(data);
        } catch (err) {
            toast({ title: 'Error', description: 'Failed to load channels', variant: 'destructive' });
        } finally {
            setLoading(false);
        }
    }

    async function handleSubmit(e: React.FormEvent) {
        e.preventDefault();
        const token = localStorage.getItem('sentinel_token');
        if (!token) return;

        try {
            if (editing) {
                await api.updateNotificationChannel(token, editing.id, formData);
                toast({ title: 'Success', description: 'Channel updated' });
            } else {
                await api.createNotificationChannel(token, formData);
                toast({ title: 'Success', description: 'Channel created' });
            }
            setShowForm(false);
            setEditing(null);
            resetForm();
            loadChannels();
        } catch (err) {
            toast({ title: 'Error', description: 'Failed to save channel', variant: 'destructive' });
        }
    }

    async function handleDelete(id: string) {
        const token = localStorage.getItem('sentinel_token');
        if (!token) return;
        if (!confirm('Delete this channel?')) return;

        try {
            await api.deleteNotificationChannel(token, id);
            toast({ title: 'Success', description: 'Channel deleted' });
            loadChannels();
        } catch (err) {
            toast({ title: 'Error', description: 'Failed to delete channel', variant: 'destructive' });
        }
    }

    async function handleTest(id: string) {
        const token = localStorage.getItem('sentinel_token');
        if (!token) return;
        setTesting(id);

        try {
            const result = await api.testNotificationChannel(token, id);
            toast({
                title: result.status === 'success' ? 'Success' : result.status === 'info' ? 'Info' : 'Error',
                description: result.message,
                variant: result.status === 'error' ? 'destructive' : 'default',
            });
        } catch (err) {
            toast({ title: 'Error', description: 'Test failed', variant: 'destructive' });
        } finally {
            setTesting(null);
        }
    }

    function resetForm() {
        setFormData({ name: '', type: 'telegram', is_default: false, config: {} });
    }

    function editChannel(channel: NotificationChannel) {
        setFormData({
            name: channel.name,
            type: channel.type,
            is_default: channel.is_default,
            config: channel.config || {},
        });
        setEditing(channel);
        setShowForm(true);
    }

    function updateConfig(key: string, value: string) {
        setFormData({ ...formData, config: { ...formData.config, [key]: value } });
    }

    function renderConfigFields() {
        switch (formData.type) {
            case 'telegram':
                return (
                    <>
                        <div>
                            <label className="text-sm font-medium">Bot Token</label>
                            <Input
                                value={formData.config.bot_token || ''}
                                onChange={e => updateConfig('bot_token', e.target.value)}
                                placeholder="123456:ABC-DEF..."
                                required
                            />
                        </div>
                        <div>
                            <label className="text-sm font-medium">Default Chat ID</label>
                            <Input
                                value={formData.config.default_chat_id || ''}
                                onChange={e => updateConfig('default_chat_id', e.target.value)}
                                placeholder="-1001234567890"
                            />
                        </div>
                        <div>
                            <label className="text-sm font-medium">Thread ID (optional)</label>
                            <Input
                                value={formData.config.default_thread_id || ''}
                                onChange={e => updateConfig('default_thread_id', e.target.value)}
                                placeholder="0"
                            />
                        </div>
                        <div>
                            <label className="text-sm font-medium">Proxy Base URL (optional)</label>
                            <Input
                                value={formData.config.proxy_base_url || ''}
                                onChange={e => updateConfig('proxy_base_url', e.target.value)}
                                placeholder="https://tg.mydomain.ir"
                            />
                            <p className="text-xs text-gray-400 mt-1">
                                Route through Cloudflare Worker proxy. Leave empty for direct api.telegram.org.
                            </p>
                        </div>
                    </>
                );
            case 'matrix':
                return (
                    <>
                        <div>
                            <label className="text-sm font-medium">Homeserver URL</label>
                            <Input
                                value={formData.config.homeserver_url || ''}
                                onChange={e => updateConfig('homeserver_url', e.target.value)}
                                placeholder="https://matrix.example.com"
                                required
                            />
                        </div>
                        <div>
                            <label className="text-sm font-medium">Access Token</label>
                            <Input
                                value={formData.config.access_token || ''}
                                onChange={e => updateConfig('access_token', e.target.value)}
                                placeholder="syt_..."
                                required
                            />
                        </div>
                        <div>
                            <label className="text-sm font-medium">Default Room ID</label>
                            <Input
                                value={formData.config.default_room_id || ''}
                                onChange={e => updateConfig('default_room_id', e.target.value)}
                                placeholder="!room:matrix.example.com"
                            />
                        </div>
                    </>
                );
            case 'sms':
                return (
                    <>
                        <div>
                            <label className="text-sm font-medium">Kavenegar API Key</label>
                            <Input
                                value={formData.config.api_key || ''}
                                onChange={e => updateConfig('api_key', e.target.value)}
                                placeholder="Your Kavenegar API key"
                                required
                            />
                        </div>
                        <div>
                            <label className="text-sm font-medium">Sender Number</label>
                            <Input
                                value={formData.config.sender || ''}
                                onChange={e => updateConfig('sender', e.target.value)}
                                placeholder="10004346"
                            />
                        </div>
                        <div>
                            <label className="text-sm font-medium">Default Recipient</label>
                            <Input
                                value={formData.config.default_recipient || ''}
                                onChange={e => updateConfig('default_recipient', e.target.value)}
                                placeholder="09123456789"
                            />
                        </div>
                    </>
                );
            case 'webhook':
                return (
                    <>
                        <div>
                            <label className="text-sm font-medium">Webhook URL</label>
                            <Input
                                value={formData.config.url || ''}
                                onChange={e => updateConfig('url', e.target.value)}
                                placeholder="https://example.com/webhook"
                                required
                            />
                        </div>
                        <div>
                            <label className="text-sm font-medium">Method</label>
                            <select
                                className="w-full h-10 px-3 rounded-md border bg-background"
                                value={formData.config.method || 'POST'}
                                onChange={e => updateConfig('method', e.target.value)}
                            >
                                <option value="POST">POST</option>
                                <option value="GET">GET</option>
                            </select>
                        </div>
                        <div>
                            <label className="text-sm font-medium">Headers (JSON)</label>
                            <Input
                                value={formData.config.headers_json || ''}
                                onChange={e => updateConfig('headers_json', e.target.value)}
                                placeholder='{"Authorization": "Bearer token"}'
                            />
                        </div>
                    </>
                );
            default:
                return null;
        }
    }

    const getIcon = (type: string) => {
        const t = CHANNEL_TYPES.find(c => c.value === type);
        return t ? t.icon : Globe;
    };

    if (loading) {
        return <div className="flex items-center justify-center min-h-screen"><Loader2 className="animate-spin" /></div>;
    }

    return (
        <div className="flex min-h-screen">
            <Sidebar />
            <main className="flex-1 ml-64 p-6">
                <div className="flex justify-between items-center mb-6">
                    <div>
                        <h1 className="text-2xl font-bold">Notification Channels</h1>
                        <p className="text-muted-foreground">Telegram bots, Matrix, SMS via Kavenegar, Webhooks</p>
                    </div>
                    <Button onClick={() => { resetForm(); setEditing(null); setShowForm(true); }}>
                        <Plus className="w-4 h-4 mr-2" /> Add Channel
                    </Button>
                </div>

                {showForm && (
                    <Card className="mb-6">
                        <CardHeader>
                            <CardTitle>{editing ? 'Edit Channel' : 'New Channel'}</CardTitle>
                        </CardHeader>
                        <CardContent>
                            <form onSubmit={handleSubmit} className="space-y-4">
                                <div className="grid grid-cols-2 gap-4">
                                    <div>
                                        <label className="text-sm font-medium">Name</label>
                                        <Input
                                            value={formData.name}
                                            onChange={e => setFormData({ ...formData, name: e.target.value })}
                                            placeholder="DevOps Telegram"
                                            required
                                        />
                                    </div>
                                    <div>
                                        <label className="text-sm font-medium">Type</label>
                                        <select
                                            className="w-full h-10 px-3 rounded-md border bg-background"
                                            value={formData.type}
                                            onChange={e => setFormData({ ...formData, type: e.target.value, config: {} })}
                                        >
                                            {CHANNEL_TYPES.map(t => (
                                                <option key={t.value} value={t.value}>{t.label}</option>
                                            ))}
                                        </select>
                                    </div>
                                </div>

                                {renderConfigFields()}

                                <div className="flex items-center gap-2">
                                    <input
                                        type="checkbox"
                                        id="is_default"
                                        checked={formData.is_default}
                                        onChange={e => setFormData({ ...formData, is_default: e.target.checked })}
                                    />
                                    <label htmlFor="is_default" className="text-sm">Set as default channel</label>
                                </div>

                                <div className="flex gap-2">
                                    <Button type="submit">{editing ? 'Update' : 'Create'}</Button>
                                    <Button type="button" variant="outline" onClick={() => { setShowForm(false); setEditing(null); }}>Cancel</Button>
                                </div>
                            </form>
                        </CardContent>
                    </Card>
                )}

                <div className="space-y-4">
                    {channels.length === 0 ? (
                        <Card>
                            <CardContent className="p-8 text-center text-muted-foreground">
                                No notification channels configured. Add one to get started.
                            </CardContent>
                        </Card>
                    ) : (
                        channels.map(channel => {
                            const Icon = getIcon(channel.type);
                            return (
                                <Card key={channel.id} className={channel.is_default ? 'border-primary' : ''}>
                                    <CardContent className="p-4">
                                        <div className="flex justify-between items-start">
                                            <div className="flex items-start gap-3">
                                                <div className="p-2 rounded-lg bg-primary/10">
                                                    <Icon className="w-5 h-5" />
                                                </div>
                                                <div>
                                                    <div className="flex items-center gap-2">
                                                        <h3 className="font-semibold">{channel.name}</h3>
                                                        {channel.is_default && (
                                                            <span className="text-xs bg-primary/20 text-primary px-2 py-0.5 rounded">Default</span>
                                                        )}
                                                    </div>
                                                    <p className="text-sm text-muted-foreground capitalize">{channel.type}</p>
                                                </div>
                                            </div>
                                            <div className="flex gap-2">
                                                <Button
                                                    size="sm"
                                                    variant="outline"
                                                    onClick={() => handleTest(channel.id)}
                                                    disabled={testing === channel.id}
                                                >
                                                    {testing === channel.id ? <Loader2 className="w-4 h-4 animate-spin" /> : <TestTube className="w-4 h-4" />}
                                                </Button>
                                                <Button size="sm" variant="outline" onClick={() => editChannel(channel)}>Edit</Button>
                                                <Button size="sm" variant="destructive" onClick={() => handleDelete(channel.id)}>
                                                    <Trash2 className="w-4 h-4" />
                                                </Button>
                                            </div>
                                        </div>
                                    </CardContent>
                                </Card>
                            );
                        })
                    )}
                </div>
            </main>
        </div>
    );
}
