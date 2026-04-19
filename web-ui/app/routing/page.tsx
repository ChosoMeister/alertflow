
'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { Sidebar } from '@/components/sidebar';
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { api } from '@/lib/api';
import { Plus, Trash2, Route, Send, MessageSquare, Search, Bell, Phone, Globe, ChevronDown, ChevronUp, Settings2, Edit, Save, X } from 'lucide-react';

interface RoutingRule {
    id: string;
    name: string;
    enabled: boolean;
    priority: number;
    match_field: string;
    email_pattern: string;
    telegram_chat_id: string;
    telegram_thread_id: string;
    matrix_room_id: string;
    channels: string;
    notification_channel_ids: string[];
    channel_overrides: Record<string, ChannelOverride>;
    severity_matrix: Record<string, { channels: string[], channel_overrides: Record<string, ChannelOverride> }>;
    ai_provider_id?: string;
    notes: string;
    created_at: string;
}

interface ChannelOverride {
    chat_id?: string;
    thread_id?: string;
    room_id?: string;
    url?: string;
    receptor?: string;
}

interface NotificationChannel {
    id: string;
    name: string;
    type: string;
    is_default: boolean;
}

interface AIProvider {
    id: string;
    name: string;
    type: string;
}

export default function RoutingPage() {
    const router = useRouter();
    const [token, setToken] = useState<string | null>(null);
    const [rules, setRules] = useState<RoutingRule[]>([]);
    const [loading, setLoading] = useState(true);
    const [channels, setChannels] = useState<NotificationChannel[]>([]);
    const [aiProviders, setAiProviders] = useState<AIProvider[]>([]);

    // Form state
    const [name, setName] = useState('');
    const [pattern, setPattern] = useState('');
    const [matchField, setMatchField] = useState('from');
    const [selectedChannelIds, setSelectedChannelIds] = useState<string[]>([]);
    const [channelOverrides, setChannelOverrides] = useState<Record<string, ChannelOverride>>({});
    const [severityMatrix, setSeverityMatrix] = useState<Record<string, { channels: string[], channel_overrides: Record<string, ChannelOverride> }>>({});
    const [expandedSeverityChannels, setExpandedSeverityChannels] = useState<Set<string>>(new Set());
    const [selectedAiProviderId, setSelectedAiProviderId] = useState<string>('');
    const [expandedChannels, setExpandedChannels] = useState<Set<string>>(new Set());
    const [priority, setPriority] = useState('0');
    const [adding, setAdding] = useState(false);
    const [editingRuleId, setEditingRuleId] = useState<string | null>(null);

    // Test match state
    const [testEmail, setTestEmail] = useState('');
    const [testResult, setTestResult] = useState<any>(null);

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
            loadRules();
            loadChannels();
            loadAiProviders();
        }
    }, [token]);

    async function loadRules() {
        try {
            const data = await api.routingRules(token!);
            setRules(data);
        } catch (e) {
            console.error(e);
        } finally {
            setLoading(false);
        }
    }

    async function loadChannels() {
        try {
            const data = await api.notificationChannels(token!);
            setChannels(data);
        } catch (e) {
            console.error(e);
        }
    }

    async function loadAiProviders() {
        try {
            const data = await api.aiProviders(token!);
            setAiProviders(data);
        } catch (e) {
            console.error(e);
        }
    }

    function toggleChannel(channelId: string) {
        setSelectedChannelIds(prev => {
            if (prev.includes(channelId)) {
                // Remove from overrides when unchecked
                const newOverrides = { ...channelOverrides };
                delete newOverrides[channelId];
                setChannelOverrides(newOverrides);
                setExpandedChannels(prev => {
                    const next = new Set(prev);
                    next.delete(channelId);
                    return next;
                });
                return prev.filter(id => id !== channelId);
            }
            return [...prev, channelId];
        });
    }

    function toggleExpanded(channelId: string) {
        setExpandedChannels(prev => {
            const next = new Set(prev);
            if (next.has(channelId)) {
                next.delete(channelId);
            } else {
                next.add(channelId);
            }
            return next;
        });
    }

    function updateOverride(channelId: string, field: string, value: string) {
        setChannelOverrides(prev => ({
            ...prev,
            [channelId]: {
                ...prev[channelId],
                [field]: value
            }
        }));
    }

    function toggleSeverityChannel(severity: string, channelId: string) {
        setSeverityMatrix(prev => {
            const entry = prev[severity] || { channels: [], channel_overrides: {} };
            const currentChannels = entry.channels;
            if (currentChannels.includes(channelId)) {
                const newOverrides = { ...entry.channel_overrides };
                delete newOverrides[channelId];
                setExpandedSeverityChannels(p => { const n = new Set(p); n.delete(`${severity}:${channelId}`); return n; });
                return { ...prev, [severity]: { channels: currentChannels.filter(id => id !== channelId), channel_overrides: newOverrides } };
            } else {
                return { ...prev, [severity]: { ...entry, channels: [...currentChannels, channelId] } };
            }
        });
    }

    function updateSeverityOverride(severity: string, channelId: string, field: string, value: string) {
        setSeverityMatrix(prev => {
            const entry = prev[severity] || { channels: [], channel_overrides: {} };
            return {
                ...prev,
                [severity]: {
                    ...entry,
                    channel_overrides: {
                        ...entry.channel_overrides,
                        [channelId]: { ...entry.channel_overrides[channelId], [field]: value }
                    }
                }
            };
        });
    }

    function toggleSeverityExpanded(severity: string, channelId: string) {
        const key = `${severity}:${channelId}`;
        setExpandedSeverityChannels(prev => {
            const next = new Set(prev);
            if (next.has(key)) { next.delete(key); } else { next.add(key); }
            return next;
        });
    }

    function removeSeverityOverride(severity: string) {
        setSeverityMatrix(prev => {
            const next = { ...prev };
            delete next[severity];
            return next;
        });
        setExpandedSeverityChannels(prev => {
            const next = new Set(prev);
            prev.forEach(k => { if (k.startsWith(`${severity}:`)) next.delete(k); });
            return next;
        });
    }

    function resetForm() {
        setName('');
        setPattern('');
        setMatchField('from');
        setSelectedChannelIds([]);
        setChannelOverrides({});
        setSeverityMatrix({});
        setExpandedSeverityChannels(new Set());
        setSelectedAiProviderId('');
        setExpandedChannels(new Set());
        setPriority('0');
        setEditingRuleId(null);
    }

    function startEditing(rule: RoutingRule) {
        setName(rule.name);
        setPattern(rule.email_pattern);
        setMatchField(rule.match_field);
        setPriority(rule.priority.toString());
        setSelectedChannelIds(rule.notification_channel_ids || []);
        setChannelOverrides(rule.channel_overrides || {});
        // Normalise severity_matrix from old flat format (string[]) to new nested format
        const rawMatrix = rule.severity_matrix || {};
        const normalisedMatrix: Record<string, { channels: string[], channel_overrides: Record<string, ChannelOverride> }> = {};
        for (const [sev, val] of Object.entries(rawMatrix)) {
            if (Array.isArray(val)) {
                // Old flat format: convert ["ch1","ch2"] → { channels: ["ch1","ch2"], channel_overrides: {} }
                normalisedMatrix[sev] = { channels: val as unknown as string[], channel_overrides: {} };
            } else if (val && typeof val === 'object' && 'channels' in val) {
                normalisedMatrix[sev] = val as { channels: string[], channel_overrides: Record<string, ChannelOverride> };
            } else {
                normalisedMatrix[sev] = { channels: [], channel_overrides: {} };
            }
        }
        setSeverityMatrix(normalisedMatrix);
        setSelectedAiProviderId(rule.ai_provider_id || '');
        setEditingRuleId(rule.id);

        // Auto-expand channels with overrides
        const channelsWithOverrides = new Set<string>();
        if (rule.channel_overrides) {
            Object.keys(rule.channel_overrides).forEach(id => channelsWithOverrides.add(id));
        }
        setExpandedChannels(channelsWithOverrides);

        // Scroll to form
        window.scrollTo({ top: 0, behavior: 'smooth' });
    }

    async function saveRule() {
        if (!name || !pattern || selectedChannelIds.length === 0) return;
        setAdding(true);

        const ruleData = {
            name,
            email_pattern: pattern,
            match_field: matchField,
            notification_channel_ids: selectedChannelIds,
            channel_overrides: channelOverrides,
            severity_matrix: severityMatrix,
            channels: 'dynamic',
            ai_provider_id: selectedAiProviderId || null,
            telegram_chat_id: '',
            telegram_thread_id: '0',
            matrix_room_id: '',
            priority: parseInt(priority) || 0,
            enabled: true
        };

        try {
            if (editingRuleId) {
                await api.updateRoutingRule(token!, editingRuleId, ruleData);
            } else {
                await api.createRoutingRule(token!, ruleData);
            }
            resetForm();
            await loadRules();
        } catch (e: any) {
            alert(e.message);
        } finally {
            setAdding(false);
        }
    }

    async function deleteRule(ruleId: string) {
        if (!confirm('Delete this rule?')) return;
        try {
            await api.deleteRoutingRule(token!, ruleId);
            await loadRules();
        } catch (e) {
            console.error(e);
        }
    }

    async function testMatch() {
        if (!testEmail) return;
        try {
            const result = await api.testRoutingMatch(token!, testEmail, 'from');
            setTestResult(result);
        } catch (e) {
            console.error(e);
        }
    }

    function getChannelIcon(type: string) {
        switch (type) {
            case 'telegram': return <Send className="h-4 w-4 text-blue-500" />;
            case 'matrix': return <MessageSquare className="h-4 w-4 text-green-500" />;
            case 'sms': return <Phone className="h-4 w-4 text-purple-500" />;
            case 'webhook': return <Globe className="h-4 w-4 text-orange-500" />;
            default: return <Bell className="h-4 w-4" />;
        }
    }

    function getChannelNames(channelIds: string[]): string {
        return channelIds
            .map(id => channels.find(c => c.id === id)?.name || id)
            .join(', ');
    }

    function needsOverride(type: string): boolean {
        return ['telegram', 'matrix', 'webhook', 'sms'].includes(type);
    }

    if (!token) return null;

    return (
        <div className="flex min-h-screen">
            <Sidebar />
            <main className="flex-1 ml-64 p-6">
                <h1 className="text-3xl font-bold mb-2">Routing Rules</h1>
                <p className="text-muted-foreground mb-6">
                    Define where alerts from specific senders should be routed.
                </p>

                <div className="grid gap-6">
                    {/* Add/Edit Rule */}
                    <Card className={editingRuleId ? "border-primary" : ""}>
                        <CardHeader>
                            <CardTitle className="flex items-center gap-2">
                                {editingRuleId ? <Edit className="h-5 w-5 text-primary" /> : <Plus className="h-5 w-5" />}
                                {editingRuleId ? 'Edit Routing Rule' : 'Add Routing Rule'}
                            </CardTitle>
                            <CardDescription>
                                Route emails matching a pattern to selected notification channels
                            </CardDescription>
                        </CardHeader>
                        <CardContent className="space-y-4">
                            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                                <div className="space-y-2">
                                    <label className="text-sm font-medium">Rule Name</label>
                                    <Input
                                        value={name}
                                        onChange={(e) => setName(e.target.value)}
                                        placeholder="Zabbix Alerts"
                                    />
                                </div>
                                <div className="space-y-2">
                                    <label className="text-sm font-medium">Email Pattern (glob)</label>
                                    <Input
                                        value={pattern}
                                        onChange={(e) => setPattern(e.target.value)}
                                        placeholder="*@zabbix.local or alert@nagios.com"
                                    />
                                </div>
                                <div className="space-y-2">
                                    <label className="text-sm font-medium">Match Field</label>
                                    <select
                                        value={matchField}
                                        onChange={(e) => setMatchField(e.target.value)}
                                        className="w-full h-10 px-3 rounded-md border border-input bg-background text-sm"
                                    >
                                        <option value="from">FROM (sender)</option>
                                        <option value="to">TO (recipient)</option>
                                    </select>
                                </div>
                            </div>

                            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                                <div className="space-y-2">
                                    <label className="text-sm font-medium">Priority (lower = first)</label>
                                    <Input
                                        type="number"
                                        value={priority}
                                        onChange={(e) => setPriority(e.target.value)}
                                        placeholder="0"
                                    />
                                </div>
                                <div className="space-y-2">
                                    <label className="text-sm font-medium">AI Provider (Optional)</label>
                                    <select
                                        value={selectedAiProviderId}
                                        onChange={(e) => setSelectedAiProviderId(e.target.value)}
                                        className="w-full h-10 px-3 rounded-md border border-input bg-background text-sm"
                                    >
                                        <option value="">Default (Global Setting)</option>
                                        {aiProviders.map(p => (
                                            <option key={p.id} value={p.id}>
                                                {p.name} ({p.type})
                                            </option>
                                        ))}
                                    </select>
                                </div>
                            </div>

                            {/* Dynamic Notification Channels Selection with Override Settings */}
                            <div className="space-y-2">
                                <label className="text-sm font-medium">
                                    Notification Channels ({selectedChannelIds.length} selected)
                                </label>
                                {channels.length === 0 ? (
                                    <p className="text-sm text-muted-foreground p-4 border rounded-lg bg-muted/30">
                                        No notification channels configured.
                                        <a href="/notification-channels" className="text-primary ml-1 hover:underline">
                                            Add channels first →
                                        </a>
                                    </p>
                                ) : (
                                    <div className="space-y-2">
                                        {channels.map(channel => (
                                            <div key={channel.id} className="rounded-lg border border-border overflow-hidden">
                                                {/* Channel Selection Row */}
                                                <div
                                                    className={`flex items-center gap-3 p-3 cursor-pointer transition-colors ${selectedChannelIds.includes(channel.id)
                                                        ? 'bg-primary/10'
                                                        : 'hover:bg-muted/50'
                                                        }`}
                                                    onClick={() => toggleChannel(channel.id)}
                                                >
                                                    <input
                                                        type="checkbox"
                                                        checked={selectedChannelIds.includes(channel.id)}
                                                        onChange={() => toggleChannel(channel.id)}
                                                        onClick={(e) => e.stopPropagation()}
                                                        className="w-4 h-4"
                                                    />
                                                    {getChannelIcon(channel.type)}
                                                    <div className="flex-1 min-w-0">
                                                        <p className="font-medium text-sm truncate">{channel.name}</p>
                                                        <p className="text-xs text-muted-foreground capitalize">{channel.type}</p>
                                                    </div>
                                                    {channel.is_default && (
                                                        <span className="text-xs bg-primary/20 text-primary px-2 py-0.5 rounded">Default</span>
                                                    )}
                                                    {/* Settings Toggle Button (only for channels that need overrides) */}
                                                    {selectedChannelIds.includes(channel.id) && needsOverride(channel.type) && (
                                                        <Button
                                                            variant="ghost"
                                                            size="sm"
                                                            onClick={(e) => {
                                                                e.stopPropagation();
                                                                toggleExpanded(channel.id);
                                                            }}
                                                            className="h-8 px-2"
                                                        >
                                                            <Settings2 className="h-4 w-4 mr-1" />
                                                            {expandedChannels.has(channel.id) ? (
                                                                <ChevronUp className="h-4 w-4" />
                                                            ) : (
                                                                <ChevronDown className="h-4 w-4" />
                                                            )}
                                                        </Button>
                                                    )}
                                                </div>

                                                {/* Expandable Override Settings */}
                                                {selectedChannelIds.includes(channel.id) && expandedChannels.has(channel.id) && (
                                                    <div className="p-4 border-t border-border bg-muted/30 space-y-3">
                                                        <p className="text-xs text-muted-foreground">
                                                            Override settings for this rule (leave empty to use channel defaults)
                                                        </p>
                                                        {channel.type === 'telegram' && (
                                                            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                                                                <div className="space-y-1">
                                                                    <label className="text-xs font-medium">Chat ID Override</label>
                                                                    <Input
                                                                        value={channelOverrides[channel.id]?.chat_id || ''}
                                                                        onChange={(e) => updateOverride(channel.id, 'chat_id', e.target.value)}
                                                                        placeholder="-100123456789"
                                                                        className="h-8 text-sm"
                                                                    />
                                                                </div>
                                                                <div className="space-y-1">
                                                                    <label className="text-xs font-medium">Thread ID Override</label>
                                                                    <Input
                                                                        value={channelOverrides[channel.id]?.thread_id || ''}
                                                                        onChange={(e) => updateOverride(channel.id, 'thread_id', e.target.value)}
                                                                        placeholder="0 (no thread)"
                                                                        className="h-8 text-sm"
                                                                    />
                                                                </div>
                                                            </div>
                                                        )}
                                                        {channel.type === 'matrix' && (
                                                            <div className="space-y-1">
                                                                <label className="text-xs font-medium">Room ID Override</label>
                                                                <Input
                                                                    value={channelOverrides[channel.id]?.room_id || ''}
                                                                    onChange={(e) => updateOverride(channel.id, 'room_id', e.target.value)}
                                                                    placeholder="!roomid:matrix.org"
                                                                    className="h-8 text-sm"
                                                                />
                                                            </div>
                                                        )}
                                                        {channel.type === 'webhook' && (
                                                            <div className="space-y-1">
                                                                <label className="text-xs font-medium">Webhook URL Override</label>
                                                                <Input
                                                                    value={channelOverrides[channel.id]?.url || ''}
                                                                    onChange={(e) => updateOverride(channel.id, 'url', e.target.value)}
                                                                    placeholder="https://api.example.com/hook"
                                                                    className="h-8 text-sm"
                                                                />
                                                            </div>
                                                        )}
                                                        {channel.type === 'sms' && (
                                                            <div className="space-y-1">
                                                                <label className="text-xs font-medium">Receptor (Phone) Override</label>
                                                                <Input
                                                                    value={channelOverrides[channel.id]?.receptor || ''}
                                                                    onChange={(e) => updateOverride(channel.id, 'receptor', e.target.value)}
                                                                    placeholder="09123456789"
                                                                    className="h-8 text-sm"
                                                                />
                                                            </div>
                                                        )}
                                                    </div>
                                                )}
                                            </div>
                                        ))}
                                    </div>
                                )}
                            </div>

                            {/* Severity Overrides */}
                            <div className="space-y-4 pt-4 border-t border-border">
                                <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
                                    <div>
                                        <label className="text-sm font-medium">Severity Overrides (Optional)</label>
                                        <p className="text-xs text-muted-foreground">
                                            Route to different channels based on alert severity.
                                        </p>
                                    </div>
                                    <div className="flex flex-wrap gap-2">
                                        {['critical', 'high', 'medium', 'low', 'info'].map(sev => (
                                            !Object.prototype.hasOwnProperty.call(severityMatrix, sev) && (
                                                <Button
                                                    key={sev} variant="outline" size="sm"
                                                    onClick={(e) => {
                                                        e.preventDefault();
                                                        setSeverityMatrix(prev => ({ ...prev, [sev]: { channels: [], channel_overrides: {} } }));
                                                    }}
                                                    className="h-7 text-xs capitalize"
                                                >
                                                    + {sev}
                                                </Button>
                                            )
                                        ))}
                                    </div>
                                </div>

                                <div className="space-y-3">
                                    {Object.entries(severityMatrix).map(([severity, entry]) => {
                                        const selectedIds = entry.channels || [];
                                        const sevOverrides = entry.channel_overrides || {};
                                        return (
                                            <div key={severity} className="p-3 border border-border rounded-lg bg-muted/20">
                                                <div className="flex items-center justify-between mb-3">
                                                    <span className={`text-xs font-bold uppercase tracking-wider px-2 py-1 rounded ${severity === 'critical' ? 'bg-red-500/20 text-red-500' :
                                                        severity === 'high' ? 'bg-orange-500/20 text-orange-500' :
                                                            severity === 'medium' ? 'bg-yellow-500/20 text-yellow-500' :
                                                                severity === 'low' ? 'bg-green-500/20 text-green-500' :
                                                                    'bg-blue-500/20 text-blue-500'
                                                        }`}>
                                                        {severity}
                                                    </span>
                                                    <Button
                                                        variant="ghost" size="sm"
                                                        onClick={() => removeSeverityOverride(severity)}
                                                        className="h-6 w-6 p-0 hover:bg-destructive/10 hover:text-destructive"
                                                    >
                                                        <X className="h-3 w-3" />
                                                    </Button>
                                                </div>
                                                <div className="space-y-2">
                                                    {channels.map(channel => {
                                                        const isSelected = selectedIds.includes(channel.id);
                                                        const isExpanded = expandedSeverityChannels.has(`${severity}:${channel.id}`);
                                                        const override = sevOverrides[channel.id] || {};
                                                        return (
                                                            <div key={channel.id} className="rounded border transition-colors overflow-hidden">
                                                                <div
                                                                    className={`flex items-center gap-2 p-2 cursor-pointer transition-colors ${isSelected ? 'bg-background border-primary shadow-sm' : 'border-border bg-background/50 hover:bg-background'}`}
                                                                    onClick={() => toggleSeverityChannel(severity, channel.id)}
                                                                >
                                                                    <div className={`w-4 h-4 rounded border flex items-center justify-center flex-shrink-0 ${isSelected ? 'bg-primary border-primary text-primary-foreground' : 'border-muted-foreground'}`}>
                                                                        {isSelected && <span className="text-[10px]">✓</span>}
                                                                    </div>
                                                                    {getChannelIcon(channel.type)}
                                                                    <span className="text-xs truncate font-medium flex-1">{channel.name}</span>
                                                                    {isSelected && (
                                                                        <Button
                                                                            variant="ghost" size="sm"
                                                                            className="h-6 w-6 p-0 flex-shrink-0"
                                                                            onClick={(e) => { e.stopPropagation(); toggleSeverityExpanded(severity, channel.id); }}
                                                                            title="Override settings"
                                                                        >
                                                                            <Settings2 className="h-3 w-3" />
                                                                        </Button>
                                                                    )}
                                                                </div>
                                                                {isSelected && isExpanded && (
                                                                    <div className="px-3 py-2 bg-muted/30 border-t border-border space-y-2" onClick={(e) => e.stopPropagation()}>
                                                                        <p className="text-[10px] text-muted-foreground">Override settings for this severity (leave empty to use channel defaults)</p>
                                                                        {(channel.type === 'telegram') && (
                                                                            <div className="grid grid-cols-2 gap-2">
                                                                                <div>
                                                                                    <label className="text-[10px] text-muted-foreground">Chat ID Override</label>
                                                                                    <Input className="h-7 text-xs" placeholder="-10012345678" value={override.chat_id || ''} onChange={(e) => updateSeverityOverride(severity, channel.id, 'chat_id', e.target.value)} />
                                                                                </div>
                                                                                <div>
                                                                                    <label className="text-[10px] text-muted-foreground">Thread ID Override</label>
                                                                                    <Input className="h-7 text-xs" placeholder="395" value={override.thread_id || ''} onChange={(e) => updateSeverityOverride(severity, channel.id, 'thread_id', e.target.value)} />
                                                                                </div>
                                                                            </div>
                                                                        )}
                                                                        {(channel.type === 'matrix') && (
                                                                            <div>
                                                                                <label className="text-[10px] text-muted-foreground">Room ID Override</label>
                                                                                <Input className="h-7 text-xs" placeholder="!roomid:server.com" value={override.room_id || ''} onChange={(e) => updateSeverityOverride(severity, channel.id, 'room_id', e.target.value)} />
                                                                            </div>
                                                                        )}
                                                                        {(channel.type === 'webhook') && (
                                                                            <div>
                                                                                <label className="text-[10px] text-muted-foreground">URL Override</label>
                                                                                <Input className="h-7 text-xs" placeholder="https://..." value={override.url || ''} onChange={(e) => updateSeverityOverride(severity, channel.id, 'url', e.target.value)} />
                                                                            </div>
                                                                        )}
                                                                        {(channel.type === 'sms') && (
                                                                            <div>
                                                                                <label className="text-[10px] text-muted-foreground">Receptor Override</label>
                                                                                <Input className="h-7 text-xs" placeholder="09123456789" value={override.receptor || ''} onChange={(e) => updateSeverityOverride(severity, channel.id, 'receptor', e.target.value)} />
                                                                            </div>
                                                                        )}
                                                                    </div>
                                                                )}
                                                            </div>
                                                        );
                                                    })}
                                                </div>
                                                {selectedIds.length === 0 && (
                                                    <p className="text-xs text-destructive mt-2">
                                                        ⚠ No channels selected for this severity. It will act as a black hole.
                                                    </p>
                                                )}
                                            </div>
                                        );
                                    })}
                                </div>
                            </div>

                            <div className="flex gap-2">
                                <Button className="flex-1" onClick={saveRule} disabled={adding || !name || !pattern || selectedChannelIds.length === 0}>
                                    {adding ? 'Saving...' : (editingRuleId ? 'Update Rule' : 'Add Rule')}
                                </Button>
                                {editingRuleId && (
                                    <Button variant="outline" onClick={resetForm} disabled={adding}>
                                        <X className="h-4 w-4 mr-2" />
                                        Cancel
                                    </Button>
                                )}
                            </div>
                        </CardContent>
                    </Card>

                    {/* Test Match */}
                    <Card>
                        <CardHeader>
                            <CardTitle className="flex items-center gap-2">
                                <Search className="h-5 w-5" />
                                test Match
                            </CardTitle>
                            <CardDescription>
                                Test which rule matches a given email address
                            </CardDescription>
                        </CardHeader>
                        <CardContent>
                            <div className="flex gap-4">
                                <Input
                                    value={testEmail}
                                    onChange={(e) => setTestEmail(e.target.value)}
                                    placeholder="alert@zabbix.local"
                                    className="flex-1"
                                />
                                <Button onClick={testMatch} disabled={!testEmail}>
                                    Test
                                </Button>
                            </div>
                            {testResult && (
                                <div className="mt-4 p-4 rounded-lg border border-border bg-muted/30">
                                    {testResult.matched ? (
                                        <div>
                                            <p className="font-medium text-green-400">✓ Matched: {testResult.rule_name}</p>
                                            <p className="text-sm text-muted-foreground mt-1">
                                                Channels: {testResult.channels}
                                            </p>
                                        </div>
                                    ) : (
                                        <div>
                                            <p className="font-medium text-yellow-400">No rule matched</p>
                                            <p className="text-sm text-muted-foreground mt-1">
                                                Will use default destinations
                                            </p>
                                        </div>
                                    )}
                                </div>
                            )}
                        </CardContent>
                    </Card>

                    {/* Existing Rules */}
                    <Card>
                        <CardHeader>
                            <CardTitle className="flex items-center gap-2">
                                <Route className="h-5 w-5" />
                                Active Rules ({rules.length})
                            </CardTitle>
                        </CardHeader>
                        <CardContent>
                            {loading ? (
                                <p className="text-muted-foreground">Loading...</p>
                            ) : rules.length === 0 ? (
                                <p className="text-muted-foreground">
                                    No routing rules configured. Alerts will use default destinations.
                                </p>
                            ) : (
                                <div className="space-y-3">
                                    {rules.map((rule) => {
                                        // Find provider name if set
                                        const providerName = rule.ai_provider_id
                                            ? aiProviders.find(p => p.id === rule.ai_provider_id)?.name
                                            : null;

                                        return (
                                            <div
                                                key={rule.id}
                                                className={`flex items-center justify-between p-4 rounded-lg border border-border bg-muted/30 ${editingRuleId === rule.id ? 'border-primary ring-1 ring-primary' : ''}`}
                                            >
                                                <div className="flex items-center gap-4">
                                                    <div className="flex gap-1">
                                                        {rule.notification_channel_ids && rule.notification_channel_ids.length > 0 ? (
                                                            rule.notification_channel_ids.slice(0, 3).map(cid => {
                                                                const ch = channels.find(c => c.id === cid);
                                                                return ch ? (
                                                                    <span key={cid} title={ch.name}>{getChannelIcon(ch.type)}</span>
                                                                ) : null;
                                                            })
                                                        ) : (
                                                            // Fallback for legacy rules
                                                            rule.channels === 'telegram' ? (
                                                                <Send className="h-5 w-5 text-blue-500" />
                                                            ) : rule.channels === 'matrix' ? (
                                                                <MessageSquare className="h-5 w-5 text-green-500" />
                                                            ) : (
                                                                <div className="flex">
                                                                    <Send className="h-5 w-5 text-blue-500" />
                                                                    <MessageSquare className="h-5 w-5 text-green-500 -ml-1" />
                                                                </div>
                                                            )
                                                        )}
                                                        {rule.notification_channel_ids && rule.notification_channel_ids.length > 3 && (
                                                            <span className="text-xs text-muted-foreground">+{rule.notification_channel_ids.length - 3}</span>
                                                        )}
                                                    </div>
                                                    <div>
                                                        <div className="flex items-center gap-2">
                                                            <p className="font-medium">{rule.name}</p>
                                                            {providerName && (
                                                                <span className="text-[10px] bg-indigo-500/20 text-indigo-400 px-1.5 py-0.5 rounded border border-indigo-500/30">
                                                                    AI: {providerName}
                                                                </span>
                                                            )}
                                                        </div>
                                                        <p className="text-sm text-muted-foreground font-mono">
                                                            {rule.match_field.toUpperCase()}: {rule.email_pattern}
                                                        </p>
                                                        <p className="text-xs text-muted-foreground mt-1">
                                                            {rule.notification_channel_ids && rule.notification_channel_ids.length > 0
                                                                ? getChannelNames(rule.notification_channel_ids)
                                                                : `Legacy: ${rule.channels}`
                                                            }
                                                            {rule.channel_overrides && Object.keys(rule.channel_overrides).length > 0 && (
                                                                <span className="ml-2 text-primary">(custom settings)</span>
                                                            )}
                                                        </p>
                                                    </div>
                                                </div>
                                                <div className="flex items-center gap-2">
                                                    <span className="text-sm text-muted-foreground mr-2">
                                                        Priority: {rule.priority}
                                                    </span>
                                                    <Button
                                                        variant="ghost"
                                                        size="sm"
                                                        onClick={() => startEditing(rule)}
                                                    >
                                                        <Edit className="h-4 w-4 text-blue-400" />
                                                    </Button>
                                                    <Button
                                                        variant="ghost"
                                                        size="sm"
                                                        onClick={() => deleteRule(rule.id)}
                                                    >
                                                        <Trash2 className="h-4 w-4 text-red-500" />
                                                    </Button>
                                                </div>
                                            </div>
                                        );
                                    })}
                                </div>
                            )}
                        </CardContent>
                    </Card>
                </div>
            </main>
        </div>
    );
}
