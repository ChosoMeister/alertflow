'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { Sidebar } from '@/components/sidebar';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { api } from '@/lib/api';
import { Plus, Trash2, TestTube, Bot, Globe, Loader2 } from 'lucide-react';
import { useToast } from '@/hooks/use-toast';

interface AIProvider {
    id: string;
    name: string;
    type: string;
    base_url: string;
    model: string;
    api_key?: string;
    timeout: number;
    is_default: boolean;
}

export default function AIProvidersPage() {
    const router = useRouter();
    const { toast } = useToast();
    const [providers, setProviders] = useState<AIProvider[]>([]);
    const [loading, setLoading] = useState(true);
    const [showForm, setShowForm] = useState(false);
    const [editing, setEditing] = useState<AIProvider | null>(null);
    const [testing, setTesting] = useState<string | null>(null);

    // Form state
    const [formData, setFormData] = useState({
        name: '',
        type: 'ollama',
        base_url: '',
        model: '',
        api_key: '',
        timeout: 120,
        is_default: false,
    });

    useEffect(() => {
        const token = localStorage.getItem('sentinel_token');
        if (!token) {
            router.push('/login');
            return;
        }
        loadProviders();
    }, []);

    async function loadProviders() {
        const token = localStorage.getItem('sentinel_token');
        if (!token) return;
        try {
            const data = await api.aiProviders(token);
            setProviders(data);
        } catch (err) {
            toast({ title: 'Error', description: 'Failed to load AI providers', variant: 'destructive' });
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
                await api.updateAIProvider(token, editing.id, formData);
                toast({ title: 'Success', description: 'Provider updated' });
            } else {
                await api.createAIProvider(token, formData);
                toast({ title: 'Success', description: 'Provider created' });
            }
            setShowForm(false);
            setEditing(null);
            resetForm();
            loadProviders();
        } catch (err) {
            toast({ title: 'Error', description: 'Failed to save provider', variant: 'destructive' });
        }
    }

    async function handleDelete(id: string) {
        const token = localStorage.getItem('sentinel_token');
        if (!token) return;
        if (!confirm('Delete this provider?')) return;

        try {
            await api.deleteAIProvider(token, id);
            toast({ title: 'Success', description: 'Provider deleted' });
            loadProviders();
        } catch (err) {
            toast({ title: 'Error', description: 'Failed to delete provider', variant: 'destructive' });
        }
    }

    async function handleTest(id: string) {
        const token = localStorage.getItem('sentinel_token');
        if (!token) return;
        setTesting(id);

        try {
            const result = await api.testAIProvider(token, id);
            toast({
                title: result.status === 'success' ? 'Success' : 'Error',
                description: result.message,
                variant: result.status === 'success' ? 'default' : 'destructive',
            });
        } catch (err) {
            toast({ title: 'Error', description: 'Test failed', variant: 'destructive' });
        } finally {
            setTesting(null);
        }
    }

    function resetForm() {
        setFormData({
            name: '',
            type: 'ollama',
            base_url: '',
            model: '',
            api_key: '',
            timeout: 120,
            is_default: false,
        });
    }

    function editProvider(provider: AIProvider) {
        setFormData({
            name: provider.name,
            type: provider.type,
            base_url: provider.base_url,
            model: provider.model,
            api_key: provider.api_key || '',
            timeout: provider.timeout,
            is_default: provider.is_default,
        });
        setEditing(provider);
        setShowForm(true);
    }

    if (loading) {
        return <div className="flex items-center justify-center min-h-screen"><Loader2 className="animate-spin" /></div>;
    }

    return (
        <div className="flex min-h-screen">
            <Sidebar />
            <main className="flex-1 ml-64 p-6">
                <div className="flex justify-between items-center mb-6">
                    <div>
                        <h1 className="text-2xl font-bold">AI Providers</h1>
                        <p className="text-muted-foreground">Manage Ollama, OpenAI, and custom AI models</p>
                    </div>
                    <Button onClick={() => { resetForm(); setEditing(null); setShowForm(true); }}>
                        <Plus className="w-4 h-4 mr-2" /> Add Provider
                    </Button>
                </div>

                {showForm && (
                    <Card className="mb-6">
                        <CardHeader>
                            <CardTitle>{editing ? 'Edit Provider' : 'New AI Provider'}</CardTitle>
                        </CardHeader>
                        <CardContent>
                            <form onSubmit={handleSubmit} className="space-y-4">
                                <div className="grid grid-cols-2 gap-4">
                                    <div>
                                        <label className="text-sm font-medium">Name</label>
                                        <Input
                                            value={formData.name}
                                            onChange={e => setFormData({ ...formData, name: e.target.value })}
                                            placeholder="Ollama Qwen3"
                                            required
                                        />
                                    </div>
                                    <div>
                                        <label className="text-sm font-medium">Type</label>
                                        <select
                                            className="w-full h-10 px-3 rounded-md border bg-background"
                                            value={formData.type}
                                            onChange={e => setFormData({ ...formData, type: e.target.value })}
                                        >
                                            <option value="ollama">Ollama</option>
                                            <option value="openai">OpenAI</option>
                                            <option value="custom">Custom</option>
                                        </select>
                                    </div>
                                </div>

                                <div>
                                    <label className="text-sm font-medium">Base URL</label>
                                    <Input
                                        value={formData.base_url}
                                        onChange={e => setFormData({ ...formData, base_url: e.target.value })}
                                        placeholder="https://ollamaoss.example.com/v1/chat/completions"
                                        required
                                    />
                                </div>

                                <div className="grid grid-cols-2 gap-4">
                                    <div>
                                        <label className="text-sm font-medium">Model</label>
                                        <Input
                                            value={formData.model}
                                            onChange={e => setFormData({ ...formData, model: e.target.value })}
                                            placeholder="gpt-4 or qwen3:latest"
                                            required
                                        />
                                    </div>
                                    <div>
                                        <label className="text-sm font-medium">Timeout (seconds)</label>
                                        <Input
                                            type="number"
                                            value={formData.timeout}
                                            onChange={e => setFormData({ ...formData, timeout: parseInt(e.target.value) })}
                                            min={10}
                                            max={600}
                                        />
                                    </div>
                                </div>

                                {(formData.type === 'openai' || formData.type === 'custom') && (
                                    <div>
                                        <label className="text-sm font-medium">API Key</label>
                                        <Input
                                            type="password"
                                            value={formData.api_key}
                                            onChange={e => setFormData({ ...formData, api_key: e.target.value })}
                                            placeholder="sk-..."
                                        />
                                    </div>
                                )}

                                <div className="flex items-center gap-2">
                                    <input
                                        type="checkbox"
                                        id="is_default"
                                        checked={formData.is_default}
                                        onChange={e => setFormData({ ...formData, is_default: e.target.checked })}
                                    />
                                    <label htmlFor="is_default" className="text-sm">Set as default provider</label>
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
                    {providers.length === 0 ? (
                        <Card>
                            <CardContent className="p-8 text-center text-muted-foreground">
                                No AI providers configured. Add one to get started.
                            </CardContent>
                        </Card>
                    ) : (
                        providers.map(provider => (
                            <Card key={provider.id} className={provider.is_default ? 'border-primary' : ''}>
                                <CardContent className="p-4">
                                    <div className="flex justify-between items-start">
                                        <div className="flex items-start gap-3">
                                            <div className="p-2 rounded-lg bg-primary/10">
                                                {provider.type === 'openai' ? <Globe className="w-5 h-5" /> : <Bot className="w-5 h-5" />}
                                            </div>
                                            <div>
                                                <div className="flex items-center gap-2">
                                                    <h3 className="font-semibold">{provider.name}</h3>
                                                    {provider.is_default && (
                                                        <span className="text-xs bg-primary/20 text-primary px-2 py-0.5 rounded">Default</span>
                                                    )}
                                                </div>
                                                <p className="text-sm text-muted-foreground">{provider.type} • {provider.model}</p>
                                                <p className="text-xs text-muted-foreground mt-1 truncate max-w-md">{provider.base_url}</p>
                                            </div>
                                        </div>
                                        <div className="flex gap-2">
                                            <Button
                                                size="sm"
                                                variant="outline"
                                                onClick={() => handleTest(provider.id)}
                                                disabled={testing === provider.id}
                                            >
                                                {testing === provider.id ? <Loader2 className="w-4 h-4 animate-spin" /> : <TestTube className="w-4 h-4" />}
                                            </Button>
                                            <Button size="sm" variant="outline" onClick={() => editProvider(provider)}>Edit</Button>
                                            <Button size="sm" variant="destructive" onClick={() => handleDelete(provider.id)}>
                                                <Trash2 className="w-4 h-4" />
                                            </Button>
                                        </div>
                                    </div>
                                </CardContent>
                            </Card>
                        ))
                    )}
                </div>
            </main>
        </div>
    );
}
