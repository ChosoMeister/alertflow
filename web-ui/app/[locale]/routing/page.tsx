
'use client';

import { useEffect, useState } from 'react';
import { useRouter } from '@/navigation';
import { useTranslations } from 'next-intl';
import { Sidebar } from '@/components/sidebar';
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { api } from '@/lib/api';
import { Plus, Trash2, Route, Send, MessageSquare, Search, Bell, Phone, Globe, ChevronDown, ChevronUp, Settings2, Edit, Save, X } from 'lucide-react';
import { useToast } from '@/hooks/use-toast';
import useSWR from 'swr';
import { Skeleton } from '@/components/ui/skeleton';

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
    severity_destination_ids?: Record<string, string[]>;
    ai_provider_id?: string;
    resolution_profile_id?: string;
    resolution_behavior?: 'legacy' | 'archive' | 'archive_and_remove';
    delete_active_after_resolve?: boolean;
    notes: string;
    created_at: string;
    alert_destination_ids?: string[];
    resolved_destination_ids?: string[];
    resolution_mode?: 'legacy' | 'copy' | 'move';
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

interface ResolutionProfile {
    id: string;
    name: string;
    enabled: boolean;
    notification_channel_ids: string[];
    channel_overrides: Record<string, ChannelOverride>;
    notes: string;
    rule_count: number;
}

interface NotificationDestination { id: string; name: string; channel_id: string; type: string; target: Record<string,string>; enabled: boolean; }

export default function RoutingPage() {
    const router = useRouter();
    const t = useTranslations('Routing');
    const c = useTranslations('Common');
    const { toast } = useToast();
    const [token, setToken] = useState<string | null>(null);

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
    const [resolutionProfileId, setResolutionProfileId] = useState('');
    const [removeActiveOnResolve, setRemoveActiveOnResolve] = useState(false);
    const [profileName, setProfileName] = useState('');
    const [profileChannelIds, setProfileChannelIds] = useState<string[]>([]);
    const [profileOverridesJson, setProfileOverridesJson] = useState('{}');
    const [savingProfile, setSavingProfile] = useState(false);
    const [alertDestinationIds, setAlertDestinationIds] = useState<string[]>([]);
    const [resolvedDestinationIds, setResolvedDestinationIds] = useState<string[]>([]);
    const [resolutionMode, setResolutionMode] = useState<'legacy'|'copy'|'move'>('legacy');
    const [severityDestinationIds, setSeverityDestinationIds] = useState<Record<string, string[]>>({});

    // Test match state
    const [testEmail, setTestEmail] = useState('');
    const [testResult, setTestResult] = useState<any>(null);

    useEffect(() => {
        const storedToken = localStorage.getItem('alertflow_token');
        if (!storedToken) {
            router.push('/login');
            return;
        }
        setToken(storedToken);
    }, [router]);

    const fetcher = async ([url, authToken]: [string, string]) => {
        if (url === '/api/routing-rules') return api.routingRules(authToken);
        if (url === '/api/notification-channels') return api.notificationChannels(authToken);
        if (url === '/api/ai-providers') return api.aiProviders(authToken);
        if (url === '/api/resolution-profiles') return api.resolutionProfiles(authToken);
        if (url === '/api/notification-destinations') return api.notificationDestinations(authToken);
    };

    const { data: fetchedRules, isLoading: rulesLoading, mutate: mutateRules } = useSWR<RoutingRule[]>(
        token ? ['/api/routing-rules', token] : null, fetcher
    );
    const { data: fetchedChannels, isLoading: channelsLoading } = useSWR<NotificationChannel[]>(
        token ? ['/api/notification-channels', token] : null, fetcher
    );
    const { data: fetchedAiProviders, isLoading: aiProvidersLoading } = useSWR<AIProvider[]>(
        token ? ['/api/ai-providers', token] : null, fetcher
    );
    const { data: fetchedProfiles, mutate: mutateProfiles } = useSWR<ResolutionProfile[]>(
        token ? ['/api/resolution-profiles', token] : null, fetcher
    );
    const { data: fetchedDestinations } = useSWR<NotificationDestination[]>(
        token ? ['/api/notification-destinations', token] : null, fetcher
    );

    const rules: RoutingRule[] = fetchedRules || [];
    const channels: NotificationChannel[] = fetchedChannels || [];
    const aiProviders: AIProvider[] = fetchedAiProviders || [];
    const resolutionProfiles: ResolutionProfile[] = fetchedProfiles || [];
    const destinations: NotificationDestination[] = fetchedDestinations || [];

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
        setResolutionProfileId('');
        setRemoveActiveOnResolve(false);
        setAlertDestinationIds([]); setResolvedDestinationIds([]); setResolutionMode('legacy');
        setSeverityDestinationIds({});
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
        setResolutionProfileId(rule.resolution_profile_id || '');
        setRemoveActiveOnResolve(rule.resolution_behavior === 'archive_and_remove' || !!rule.delete_active_after_resolve);
        setAlertDestinationIds(rule.alert_destination_ids || []);
        setResolvedDestinationIds(rule.resolved_destination_ids || []);
        setResolutionMode(rule.resolution_mode || 'legacy');
        setSeverityDestinationIds(rule.severity_destination_ids || {});

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
        if (!name || !pattern || alertDestinationIds.length === 0) return;
        setAdding(true);

        const ruleData = {
            name,
            email_pattern: pattern,
            match_field: matchField,
            ai_provider_id: selectedAiProviderId || null,
            priority: parseInt(priority) || 0,
            enabled: true
            ,alert_destination_ids: alertDestinationIds
            ,resolved_destination_ids: resolvedDestinationIds
            ,severity_destination_ids: severityDestinationIds
            ,resolution_mode: resolvedDestinationIds.length ? resolutionMode : 'legacy'
        };

        try {
            if (editingRuleId) {
                await api.updateRoutingRule(token!, editingRuleId, ruleData);
                toast({ title: c('success'), description: t('success_updated') });
            } else {
                await api.createRoutingRule(token!, ruleData);
                toast({ title: c('success'), description: t('success_created') });
            }
            resetForm();
            mutateRules();
        } catch (e: any) {
            toast({ title: c('error'), description: e.message, variant: 'destructive' });
        } finally {
            setAdding(false);
        }
    }

    async function deleteRule(ruleId: string) {
        if (!confirm('Delete this rule?')) return;
        try {
            await api.deleteRoutingRule(token!, ruleId);
            toast({ title: c('success'), description: t('success_deleted') });
            mutateRules();
        } catch (e: any) {
            toast({ title: c('error'), description: e.message || 'Failed to delete rule', variant: 'destructive' });
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

    async function createProfile() {
        if (!profileName || profileChannelIds.length === 0) return;
        setSavingProfile(true);
        try {
            const overrides = JSON.parse(profileOverridesJson || '{}');
            await api.createResolutionProfile(token!, {
                name: profileName, enabled: true, notification_channel_ids: profileChannelIds,
                channel_overrides: overrides, notes: ''
            });
            setProfileName(''); setProfileChannelIds([]); setProfileOverridesJson('{}');
            mutateProfiles();
            toast({ title: c('success'), description: 'Resolution profile created' });
        } catch (e: any) {
            toast({ title: c('error'), description: e.message || 'Invalid overrides JSON', variant: 'destructive' });
        } finally { setSavingProfile(false); }
    }

    async function deleteProfile(id: string) {
        if (!confirm('Delete this resolution profile?')) return;
        try { await api.deleteResolutionProfile(token!, id); mutateProfiles(); }
        catch (e: any) { toast({ title: c('error'), description: e.message, variant: 'destructive' }); }
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
            <main className="flex-1 ltr:ml-64 rtl:mr-64 p-6">
                <h1 className="text-3xl font-bold mb-2">{t('title')}</h1>
                <p className="text-muted-foreground mb-6">
                    {t('subtitle')}
                </p>

                <div className="grid gap-6">
                    {/* Add/Edit Rule */}
                    <Card className={editingRuleId ? "border-primary" : ""}>
                        <CardHeader>
                            <CardTitle className="flex items-center gap-2">
                                {editingRuleId ? <Edit className="h-5 w-5 text-primary" /> : <Plus className="h-5 w-5" />}
                                {editingRuleId ? t('edit_rule') : t('add_rule')}
                            </CardTitle>
                            <CardDescription>
                                {t('rule_desc')}
                            </CardDescription>
                        </CardHeader>
                        <CardContent className="space-y-4">
                            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                                <div className="space-y-2">
                                    <label className="text-sm font-medium">{t('rule_name')}</label>
                                    <Input
                                        value={name}
                                        onChange={(e) => setName(e.target.value)}
                                        placeholder={t('rule_name_placeholder')}
                                    />
                                </div>
                                <div className="space-y-2">
                                    <label className="text-sm font-medium">{t('email_pattern')}</label>
                                    <Input
                                        value={pattern}
                                        onChange={(e) => setPattern(e.target.value)}
                                        placeholder={t('email_pattern_placeholder')}
                                    />
                                </div>
                                <div className="space-y-2">
                                    <label className="text-sm font-medium">{t('match_field')}</label>
                                    <select
                                        value={matchField}
                                        onChange={(e) => setMatchField(e.target.value)}
                                        className="w-full h-10 px-3 rounded-md border border-input bg-background text-sm"
                                    >
                                        <option value="from">{t('match_from')}</option>
                                        <option value="to">{t('match_to')}</option>
                                    </select>
                                </div>
                            </div>

                            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                                <div className="space-y-2">
                                    <label className="text-sm font-medium">{t('priority')}</label>
                                    <Input
                                        type="number"
                                        value={priority}
                                        onChange={(e) => setPriority(e.target.value)}
                                        placeholder="0"
                                    />
                                </div>
                                <div className="space-y-2">
                                    <label className="text-sm font-medium">{t('ai_provider')}</label>
                                    <select
                                        value={selectedAiProviderId}
                                        onChange={(e) => setSelectedAiProviderId(e.target.value)}
                                        className="w-full h-10 px-3 rounded-md border border-input bg-background text-sm"
                                    >
                                        <option value="">{t('global_setting')}</option>
                                        {aiProviders.map(p => (
                                            <option key={p.id} value={p.id}>
                                                {p.name} ({p.type})
                                            </option>
                                        ))}
                                    </select>
                                </div>
                            </div>

                            <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
                                <div className="rounded-xl border border-amber-500/30 bg-amber-500/5 p-4 space-y-3">
                                    <div><p className="font-semibold">Alert destinations</p><p className="text-xs text-muted-foreground">Active incidents are sent or updated in every selected endpoint.</p></div>
                                    <div className="space-y-2 max-h-60 overflow-y-auto">
                                        {destinations.map(item => <label key={item.id} className={`flex items-start gap-3 rounded-lg border p-3 cursor-pointer ${alertDestinationIds.includes(item.id) ? 'border-amber-400 bg-amber-500/10' : 'border-border'}`}>
                                            <input type="checkbox" className="mt-1" checked={alertDestinationIds.includes(item.id)} onChange={() => setAlertDestinationIds(prev => prev.includes(item.id) ? prev.filter(x => x !== item.id) : [...prev,item.id])} />
                                            <span>{getChannelIcon(item.type)}</span><span><span className="block text-sm font-medium">{item.name}</span><span className="block text-xs text-muted-foreground">{item.type === 'telegram' ? `${item.target.chat_id}${item.target.thread_id && item.target.thread_id !== '0' ? ` / thread ${item.target.thread_id}` : ''}` : item.target.room_id || item.target.url || item.target.receptor}</span></span>
                                        </label>)}
                                    </div>
                                </div>
                                <div className="rounded-xl border border-emerald-500/30 bg-emerald-500/5 p-4 space-y-3">
                                    <div><p className="font-semibold">Resolved destinations</p><p className="text-xs text-muted-foreground">Select Telegram, Matrix or multiple endpoints for the completed incident card.</p></div>
                                    <select value={resolutionMode} onChange={e => setResolutionMode(e.target.value as 'legacy'|'copy'|'move')} className="w-full h-10 px-3 rounded-md border bg-background text-sm">
                                        <option value="legacy">Keep in place (legacy)</option><option value="copy">Copy to resolved destinations</option><option value="move">Move after all resolved deliveries succeed</option>
                                    </select>
                                    {resolutionMode !== 'legacy' && <div className="space-y-2 max-h-60 overflow-y-auto">{destinations.map(item => <label key={item.id} className={`flex items-start gap-3 rounded-lg border p-3 cursor-pointer ${resolvedDestinationIds.includes(item.id) ? 'border-emerald-400 bg-emerald-500/10' : 'border-border'}`}>
                                        <input type="checkbox" className="mt-1" checked={resolvedDestinationIds.includes(item.id)} onChange={() => setResolvedDestinationIds(prev => prev.includes(item.id) ? prev.filter(x => x !== item.id) : [...prev,item.id])} />
                                        <span>{getChannelIcon(item.type)}</span><span><span className="block text-sm font-medium">{item.name}</span><span className="block text-xs text-muted-foreground">{item.type === 'telegram' ? `${item.target.chat_id}${item.target.thread_id && item.target.thread_id !== '0' ? ` / thread ${item.target.thread_id}` : ''}` : item.target.room_id || item.target.url || item.target.receptor}</span></span>
                                    </label>)}</div>}
                                </div>
                            </div>

                            {/* Dynamic Notification Channels Selection with Override Settings */}
                            <div className="hidden" aria-hidden="true">
                                <label className="text-sm font-medium">
                                    Legacy connector compatibility and severity overrides ({selectedChannelIds.length} selected)
                                </label>
                                {channelsLoading ? (
                                    <div className="space-y-2">
                                        {[...Array(2)].map((_, i) => (
                                            <Skeleton key={i} className="h-12 w-full rounded-lg" />
                                        ))}
                                    </div>
                                ) : channels.length === 0 ? (
                                    <p className="text-sm text-muted-foreground p-4 border rounded-lg bg-muted/30">
                                        {t('no_channels')}
                                        <a href="/notification-channels" className="text-primary ltr:ml-1 rtl:mr-1 hover:underline">
                                            {t('add_channels_first')}
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

                            <div className="space-y-4 pt-4 border-t border-border">
                                <div>
                                    <label className="text-sm font-medium">Severity destinations (Optional)</label>
                                    <p className="text-xs text-muted-foreground">A configured severity replaces the default Alert destinations. Empty severities inherit the default destinations.</p>
                                </div>
                                <div className="grid grid-cols-1 xl:grid-cols-2 gap-3">
                                    {['critical', 'high', 'medium', 'low', 'info'].map(severity => {
                                        const enabled = Object.prototype.hasOwnProperty.call(severityDestinationIds, severity);
                                        const selected = severityDestinationIds[severity] || [];
                                        return <div key={severity} className={`rounded-lg border p-3 space-y-2 ${enabled ? 'border-primary/50 bg-primary/5' : 'border-border bg-muted/20'}`}>
                                            <label className="flex items-center justify-between gap-3 cursor-pointer">
                                                <span className="flex items-center gap-2">
                                                    <input
                                                        type="checkbox"
                                                        checked={enabled}
                                                        onChange={() => setSeverityDestinationIds(prev => {
                                                            const next = { ...prev };
                                                            if (enabled) delete next[severity];
                                                            else next[severity] = [];
                                                            return next;
                                                        })}
                                                    />
                                                    <span className="text-xs font-bold uppercase tracking-wider">{severity}</span>
                                                </span>
                                                <span className="text-xs text-muted-foreground">{enabled ? `${selected.length} selected` : 'Inherit default'}</span>
                                            </label>
                                            {enabled && <div className="max-h-48 overflow-y-auto space-y-1 pt-2 border-t border-border">
                                                {destinations.map(item => <label key={item.id} className={`flex items-center gap-2 rounded border p-2 cursor-pointer ${selected.includes(item.id) ? 'border-primary bg-primary/10' : 'border-border'}`}>
                                                    <input type="checkbox" checked={selected.includes(item.id)} onChange={() => setSeverityDestinationIds(prev => ({...prev, [severity]: selected.includes(item.id) ? selected.filter(id => id !== item.id) : [...selected, item.id]}))} />
                                                    {getChannelIcon(item.type)}<span className="text-xs truncate">{item.name}</span>
                                                </label>)}
                                                {selected.length === 0 && <p className="text-xs text-amber-500 py-1">Select at least one destination, or turn this severity off to inherit defaults.</p>}
                                            </div>}
                                        </div>;
                                    })}
                                </div>
                            </div>

                            {/* Removed connector-based severity editor; retained in source for one release only, never rendered. */}
                            <div className="hidden" aria-hidden="true">
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
                                <Button className="flex-1" onClick={saveRule} disabled={adding || !name || !pattern || alertDestinationIds.length === 0 || (resolutionMode !== 'legacy' && resolvedDestinationIds.length === 0)}>
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
                            {rulesLoading ? (
                                <div className="space-y-3">
                                    {[...Array(3)].map((_, i) => (
                                        <div key={i} className="flex items-center justify-between p-4 rounded-lg border border-border bg-muted/30">
                                            <div className="flex items-center gap-4 w-full">
                                                <div className="flex gap-1">
                                                    <Skeleton className="h-5 w-5 rounded-full" />
                                                    <Skeleton className="h-5 w-5 rounded-full" />
                                                </div>
                                                <div className="flex-1 space-y-2">
                                                    <Skeleton className="h-4 w-1/4" />
                                                    <Skeleton className="h-3 w-1/3" />
                                                </div>
                                                <div className="flex gap-2">
                                                    <Skeleton className="h-8 w-8 rounded-md" />
                                                    <Skeleton className="h-8 w-8 rounded-md" />
                                                </div>
                                            </div>
                                        </div>
                                    ))}
                                </div>
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
                                                            <span className={`text-[10px] px-1.5 py-0.5 rounded border ${rule.resolution_mode && rule.resolution_mode !== 'legacy' ? 'bg-emerald-500/15 text-emerald-400 border-emerald-500/30' : 'bg-muted text-muted-foreground border-border'}`}>
                                                                {rule.resolution_mode && rule.resolution_mode !== 'legacy'
                                                                    ? `Resolve: ${rule.resolution_mode} → ${(rule.resolved_destination_ids || []).length} endpoint(s)`
                                                                    : 'Resolve: legacy'}
                                                            </span>
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
