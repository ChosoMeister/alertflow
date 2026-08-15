'use client';

import { useEffect, useMemo, useRef, useState } from 'react';
import { useRouter } from '@/navigation';
import { useAuth } from '@/hooks/use-auth';
import { Sidebar } from '@/components/sidebar';
import { IncidentDrawer } from '@/components/incident-drawer';
import { api } from '@/lib/api';
import { Activity, AlertTriangle, Brain, CheckCircle2, Clock3, Database, HardDrive, Radio, Send, ShieldCheck, Siren, Wifi, WifiOff, ArrowUpRight, Layers3 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { formatDate } from '@/lib/utils';

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

export default function DashboardPage() {
  const router = useRouter();
  const { token, isLoading: authLoading } = useAuth();
  const [status, setStatus] = useState<any>({});
  const [metrics, setMetrics] = useState<any>({});
  const [alerts, setAlerts] = useState<any[]>([]);
  const [observability, setObservability] = useState<any>({});
  const [selected, setSelected] = useState<string | null>(null);
  const [live, setLive] = useState(false);
  const polling = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    if (!token) return;
    let stopped = false; let source: EventSource | null = null;
    const poll = async () => { try { const [s, m, a] = await Promise.all([api.status(token), api.metrics(token), api.alerts(token, { limit: 30, status: 'open' })]); if (!stopped) { setStatus(s); setMetrics(m); setAlerts(a); } } catch {} };
    try {
      source = new EventSource(`${API_URL}/api/sse/dashboard`, { withCredentials: true });
      source.onmessage = event => { const data = JSON.parse(event.data); if (!data.error && !stopped) { setStatus(data.status); setMetrics(data.metrics); setAlerts(data.alerts || []); setLive(true); } };
      source.onerror = () => { source?.close(); setLive(false); poll(); polling.current = setInterval(poll, 10000); };
    } catch { poll(); }
    return () => { stopped = true; source?.close(); if (polling.current) clearInterval(polling.current); };
  }, [token]);
  useEffect(() => { if (!token) return; const load = () => api.observabilityHealth(token).then(setObservability).catch(() => setObservability({ status: 'critical' })); load(); const id = setInterval(load, 30000); return () => clearInterval(id); }, [token]);

  const incidents = useMemo(() => { const seen = new Set(); return alerts.filter(a => { const key = a.incident_key || a.id; if (seen.has(key)) return false; seen.add(key); return true; }); }, [alerts]);
  const critical = incidents.filter(a => a.severity === 'Critical').length;
  const systemHealthy = status.redis === 'online' && status.alert_processor === 'online' && status.ollama === 'online' && observability?.status !== 'critical';
  const healthItems = [
    { label: 'Processor', value: status.alert_processor, icon: Activity },
    { label: 'Redis', value: status.redis, icon: Database },
    { label: 'AI chain', value: status.ollama, icon: Brain },
    { label: 'Log pipeline', value: observability?.canary, icon: ShieldCheck },
  ];
  if (authLoading || !token) return null;

  return <div className="min-h-screen"><Sidebar/><main className="min-h-screen ltr:ml-64 rtl:mr-64 px-6 py-7 xl:px-8">
    <header className="mb-7 flex flex-col gap-5 xl:flex-row xl:items-end xl:justify-between"><div><p className="eyebrow">Operations command center</p><h1 className="mt-2 text-3xl font-semibold tracking-tight md:text-4xl">Good afternoon, operator.</h1><p className="mt-2 max-w-2xl text-sm leading-6 text-slate-400">One focused view for incidents, delivery health and AI decisions.</p></div><div className="flex flex-wrap items-center gap-2"><span className={`flex items-center gap-2 rounded-full border px-3 py-2 text-xs ${live ? 'border-emerald-400/20 bg-emerald-400/10 text-emerald-300' : 'border-amber-400/20 bg-amber-400/10 text-amber-300'}`}>{live ? <Wifi className="h-3.5 w-3.5"/> : <WifiOff className="h-3.5 w-3.5"/>}{live ? 'Live telemetry' : 'Polling fallback'}</span><Button variant="outline" onClick={() => router.push('/smtp')}><Send className="me-2 h-4 w-4"/>Test signal</Button></div></header>

    <section className={`relative mb-6 overflow-hidden rounded-3xl border p-6 ${systemHealthy ? 'border-emerald-400/15 bg-gradient-to-br from-emerald-400/[.08] to-cyan-400/[.03]' : 'border-red-400/20 bg-gradient-to-br from-red-500/10 to-orange-500/[.03]'}`}><div className="absolute -right-16 -top-20 h-56 w-56 rounded-full bg-cyan-400/10 blur-3xl"/><div className="relative flex flex-col gap-6 lg:flex-row lg:items-center lg:justify-between"><div className="flex items-start gap-4"><span className={`rounded-2xl p-3 ${systemHealthy ? 'bg-emerald-400/10 text-emerald-300' : 'bg-red-400/10 text-red-300'}`}>{systemHealthy ? <CheckCircle2 className="h-7 w-7"/> : <Siren className="h-7 w-7"/>}</span><div><p className="text-xs uppercase tracking-[.18em] text-slate-500">AlertFlow posture</p><h2 className="mt-1 text-2xl font-semibold">{systemHealthy ? 'All core systems operational' : 'Attention required'}</h2><p className="mt-1 text-sm text-slate-400">{critical ? `${critical} critical incident${critical > 1 ? 's' : ''} require review.` : 'No critical incident is waiting for response.'}</p></div></div><div className="grid grid-cols-3 gap-6 lg:min-w-[28rem]"><div><p className="metric-value">{incidents.length}</p><p className="text-xs text-slate-500">Active incidents</p></div><div><p className={`metric-value ${critical ? '!text-red-300' : ''}`}>{critical}</p><p className="text-xs text-slate-500">Critical</p></div><div><p className="metric-value">{metrics.queue_depth || 0}</p><p className="text-xs text-slate-500">Queue depth</p></div></div></div></section>

    <div className="grid gap-6 2xl:grid-cols-[1fr_22rem]"><div className="space-y-6"><section className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">{healthItems.map(item => <div key={item.label} className="surface-card p-4"><div className="flex items-center justify-between"><span className="rounded-xl bg-white/5 p-2 text-cyan-300"><item.icon className="h-4 w-4"/></span><span className={`h-2 w-2 rounded-full ${['online','healthy'].includes(item.value) ? 'bg-emerald-400 shadow-[0_0_10px_rgba(52,211,153,.8)]' : 'bg-amber-400'}`}/></div><p className="mt-4 text-xs text-slate-500">{item.label}</p><p className="mt-1 text-sm font-semibold capitalize">{item.value || 'Unknown'}</p></div>)}</section>

      <section className="surface-card"><div className="flex items-center justify-between border-b border-white/[.07] px-5 py-4"><div><p className="eyebrow">Incident feed</p><h2 className="mt-1 text-lg font-semibold">Highest priority now</h2></div><button onClick={() => router.push('/alerts')} className="flex items-center gap-1 text-xs font-medium text-cyan-300 hover:text-cyan-200">View workspace <ArrowUpRight className="h-3.5 w-3.5"/></button></div><div className="divide-y divide-white/[.06]">{incidents.slice(0, 8).map(alert => <button key={alert.id} onClick={() => setSelected(alert.id)} className="grid w-full gap-4 px-5 py-4 text-start transition hover:bg-white/[.025] md:grid-cols-[auto_1fr_auto]"><span className={`mt-1 h-9 w-1 rounded-full ${alert.severity === 'Critical' ? 'bg-red-500' : alert.severity === 'High' ? 'bg-orange-400' : alert.severity === 'Medium' ? 'bg-amber-400' : 'bg-cyan-400'}`}/><div className="min-w-0"><div className="flex flex-wrap items-center gap-2"><span className={`severity-pill severity-${String(alert.severity || 'unknown').toLowerCase()}`}>{alert.severity || 'Unknown'}</span><span className="text-xs text-slate-500">{alert.system_name || alert.category || 'Unclassified'}</span></div><p className="mt-2 line-clamp-2 text-sm font-medium leading-6" dir="auto">{alert.main_message || alert.subject}</p><p className="mt-1 truncate text-xs text-slate-500">{alert.from_email}</p></div><div className="flex items-center gap-4 md:justify-end"><div className="text-end"><span className="status-pill">{alert.status}</span><p className="mt-2 text-[11px] text-slate-600">{formatDate(alert.created_at)}</p></div><ArrowUpRight className="h-4 w-4 text-slate-600"/></div></button>)}{!incidents.length && <div className="p-10 text-center"><CheckCircle2 className="mx-auto h-10 w-10 text-emerald-300"/><p className="mt-3 font-medium">No active incident</p><p className="mt-1 text-sm text-slate-500">AlertFlow is listening. Validate the complete path whenever you add a source.</p><div className="mt-5 flex flex-wrap justify-center gap-2"><button onClick={() => router.push('/ai-providers')} className="rounded-xl border border-white/10 px-3 py-2 text-xs hover:bg-white/5">1 · Check AI</button><button onClick={() => router.push('/notification-channels')} className="rounded-xl border border-white/10 px-3 py-2 text-xs hover:bg-white/5">2 · Check channel</button><button onClick={() => router.push('/smtp')} className="rounded-xl border border-cyan-400/20 bg-cyan-400/5 px-3 py-2 text-xs text-cyan-200">3 · Send test signal</button></div></div>}</div></section>
    </div>

    <aside className="space-y-4"><div className="surface-card p-5"><div className="section-heading"><Layers3 className="h-5 w-5 text-cyan-300"/><div><h3>Flow health</h3><p>Last 24 hours</p></div></div><div className="mt-5 space-y-4"><Flow label="Processed" value={metrics.processed_count_24h || 0} tone="cyan"/><Flow label="Errors" value={metrics.error_count_24h || 0} tone={metrics.error_count_24h ? 'red' : 'green'}/><Flow label="Retry queue" value={metrics.retry_queue_depth || 0} tone={metrics.retry_queue_depth ? 'amber' : 'green'}/><Flow label="Dead letter" value={metrics.dlq_depth || 0} tone={metrics.dlq_depth ? 'red' : 'green'}/></div></div><div className="surface-card p-5"><div className="section-heading"><Siren className="h-5 w-5 text-orange-300"/><div><h3>Storm control</h3><p>{metrics.storm_suppressed ? 'Suppression active in this window' : 'Quiet — no active storm'}</p></div></div><div className="mt-4 flex items-end justify-between"><div><p className="text-3xl font-semibold">{metrics.storm_suppressed || 0}</p><p className="text-xs text-slate-500">Suppressed safely</p></div><button onClick={() => router.push('/settings')} className="rounded-lg border border-white/10 px-2.5 py-1.5 text-[11px] text-slate-300 hover:bg-white/5">Configure</button></div><p className="mt-4 text-xs leading-5 text-slate-500">Critical new incidents and recovery notifications continue through the cap.</p></div><div className="surface-card p-5"><div className="section-heading"><HardDrive className="h-5 w-5 text-violet-300"/><div><h3>Host capacity</h3><p>Live observability</p></div></div><div className="mt-5"><div className="flex items-end justify-between"><span className="text-3xl font-semibold">{Number(observability?.disk_used_percent || 0).toFixed(1)}%</span><span className="text-xs text-emerald-300">Healthy</span></div><div className="mt-3 h-2 overflow-hidden rounded-full bg-white/5"><div className="h-full rounded-full bg-gradient-to-r from-cyan-400 to-violet-500" style={{width: `${Math.min(100, observability?.disk_used_percent || 0)}%`}}/></div></div></div><div className="surface-card p-5"><div className="flex items-center gap-3"><span className="rounded-xl bg-violet-400/10 p-2 text-violet-300"><Brain className="h-5 w-5"/></span><div><p className="text-sm font-semibold">AI chain ready</p><p className="text-xs text-slate-500">Primary with selected fallback</p></div></div><button onClick={() => router.push('/ai-providers')} className="mt-4 w-full rounded-xl border border-white/10 py-2.5 text-xs text-slate-300 transition hover:bg-white/5">Manage providers</button></div></aside></div>
    <IncidentDrawer alertId={selected} token={token} onClose={() => setSelected(null)}/>
  </main></div>;
}

function Flow({ label, value, tone }: { label: string; value: number; tone: string }) { const colors: any = { cyan: 'bg-cyan-400', green: 'bg-emerald-400', red: 'bg-red-400', amber: 'bg-amber-400' }; return <div className="flex items-center justify-between"><div className="flex items-center gap-2"><span className={`h-2 w-2 rounded-full ${colors[tone]}`}/><span className="text-sm text-slate-400">{label}</span></div><strong className="text-sm">{value}</strong></div>; }
