'use client';

import { useEffect, useState } from 'react';
import { X, Brain, GitMerge, Clock3, CheckCircle2, Send, ShieldCheck, Radio, Target, Eye, BellOff, RotateCw, AlertTriangle } from 'lucide-react';
import { api } from '@/lib/api';
import { Button } from '@/components/ui/button';
import { formatDate } from '@/lib/utils';
import { toast } from 'sonner';

export function IncidentDrawer({ alertId, token, onClose, onChanged }: { alertId: string | null; token: string; onClose: () => void; onChanged?: () => void }) {
  const [alert, setAlert] = useState<any>(null);
  const [events, setEvents] = useState<any[]>([]);
  const [operations, setOperations] = useState<any>(null);
  const [preview, setPreview] = useState<'telegram' | 'matrix'>('telegram');
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!alertId) return;
    setAlert(null); setOperations(null);
    Promise.all([api.alert(token, alertId), api.alertTimeline(token, alertId), api.alertOperations(token, alertId)])
      .then(([a, timeline, ops]) => { setAlert(a); setEvents(timeline.events || []); setOperations(ops); })
      .catch(() => toast.error('Could not load incident details'));
  }, [alertId, token]);
  if (!alertId) return null;

  const act = async (status: string) => {
    setBusy(true);
    try { await api.updateAlertStatus(token, alertId, status); setAlert((old: any) => ({ ...old, status })); toast.success(`Incident marked ${status}`); onChanged?.(); }
    catch (error: any) { toast.error(error.message); } finally { setBusy(false); }
  };
  const iconFor = (type: string) => type === 'DELIVERY' ? Send : type === 'OPERATOR' ? CheckCircle2 : type === 'SUPPRESSED' ? ShieldCheck : type === 'CREATED' ? Radio : Clock3;
  const resources = operations?.impact?.resources || [];
  const selectedPreview = operations?.previews?.[preview] || '';

  return <div className="fixed inset-0 z-[90] bg-slate-950/55 backdrop-blur-sm" onMouseDown={onClose}>
    <aside className="absolute inset-y-0 ltr:right-0 rtl:left-0 w-full max-w-2xl overflow-y-auto border-l border-white/10 bg-[#0c1422] shadow-2xl" onMouseDown={e => e.stopPropagation()}>
      <div className="sticky top-0 z-10 flex items-center justify-between border-b border-white/10 bg-[#0c1422]/95 px-5 py-4 backdrop-blur"><div><p className="eyebrow">Incident workspace</p><h2 className="mt-1 text-lg font-semibold">{alert?.system_name || 'Loading incident…'}</h2></div><button onClick={onClose} className="icon-button"><X className="h-5 w-5"/></button></div>
      {!alert ? <div className="space-y-4 p-6"><div className="skeleton-block h-28"/><div className="skeleton-block h-52"/></div> : <div className="space-y-5 p-5">
        <section className="surface-card overflow-hidden"><div className={`h-1 ${alert.severity === 'Critical' ? 'bg-red-500' : alert.severity === 'High' ? 'bg-orange-500' : 'bg-cyan-500'}`}/><div className="p-5"><div className="flex flex-wrap items-center gap-2"><span className={`severity-pill severity-${String(alert.severity || 'unknown').toLowerCase()}`}>{alert.severity || 'Unknown'}</span><span className="status-pill">{alert.status}</span><span className="text-xs text-slate-500">{formatDate(alert.created_at)}</span></div><h3 className="mt-4 text-xl font-semibold leading-8" dir="auto">{alert.main_message || alert.subject}</h3><div className="mt-4 flex flex-wrap gap-2">{resources.map((r: string) => <span key={r} className="resource-chip">{r}</span>)}</div></div></section>

        <section className="surface-card p-5"><div className="section-heading"><Target className="h-5 w-5 text-orange-300"/><div><h3>Incident impact</h3><p>Observed blast radius from correlated evidence</p></div><span className={`ms-auto status-pill ${operations?.impact?.blast_radius === 'wide' ? 'text-red-300' : 'text-emerald-300'}`}>{operations?.impact?.blast_radius || '—'}</span></div><div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-4"><div className="data-tile"><span>Resources</span><strong>{operations?.impact?.resource_count ?? '—'}</strong></div><div className="data-tile"><span>Occurrences</span><strong>{operations?.impact?.occurrences ?? '—'}</strong></div><div className="data-tile"><span>System</span><strong className="break-words">{operations?.impact?.system || '—'}</strong></div><div className="data-tile"><span>Category</span><strong>{operations?.impact?.category || '—'}</strong></div></div></section>

        <section className="surface-card p-5"><div className="section-heading">{operations?.decision?.outcome === 'suppressed' ? <BellOff className="h-5 w-5 text-amber-300"/> : <GitMerge className="h-5 w-5 text-cyan-300"/>}<div><h3>Notification decision</h3><p>Why the system sent, updated, or stayed silent</p></div><span className="ms-auto status-pill">{operations?.decision?.outcome || '—'}</span></div><div className="mt-4 grid gap-3 sm:grid-cols-2"><div className="data-tile"><span>Decision code</span><strong>{operations?.decision?.code || '—'}</strong></div><div className="data-tile"><span>Incident key</span><strong className="truncate font-mono text-xs">{alert.incident_key || '—'}</strong></div><div className="data-tile sm:col-span-2"><span>Reason</span><strong>{operations?.decision?.reason || 'Decision metadata is unavailable for this historical alert'}</strong></div></div></section>

        <section className="surface-card p-5"><div className="section-heading"><Brain className="h-5 w-5 text-violet-300"/><div><h3>AI analysis</h3><p>Decision support with visible evidence</p></div><span className={`ms-auto status-pill ${operations?.analysis_quality?.evidence_status === 'verified' ? 'text-emerald-300' : 'text-amber-300'}`}>{operations?.analysis_quality?.evidence_status || 'unknown'}</span></div><div className="mt-4 grid grid-cols-2 gap-3"><div className="data-tile"><span>Model confidence</span><strong>{operations?.analysis_quality ? `${Math.round(operations.analysis_quality.model_confidence * 100)}%` : '—'}</strong></div><div className="data-tile"><span>Evidence confidence</span><strong>{operations?.analysis_quality ? `${Math.round(operations.analysis_quality.evidence_confidence * 100)}%` : '—'}</strong></div></div>{operations?.analysis_quality?.validation_warnings?.length > 0 && <div className="mt-3 rounded-xl border border-amber-400/20 bg-amber-400/5 p-3 text-xs leading-5 text-amber-200">Evidence guardrail adjusted this analysis: {operations.analysis_quality.validation_warnings.join(', ')}</div>}<p className="mt-4 whitespace-pre-wrap text-sm leading-7 text-slate-300" dir="auto">{alert.details || 'No structured detail was returned.'}</p></section>

        {operations?.delivery_risk?.degraded && <section className="rounded-2xl border border-red-500/30 bg-red-500/10 p-4"><div className="flex gap-3"><AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-red-300"/><div><h3 className="font-semibold text-red-200">Delivery attention required</h3><p className="mt-1 text-sm leading-6 text-red-100/70">{operations.delivery_risk.reason}. Exhausted: {operations.delivery_risk.exhausted_total} · Consecutive failures: {operations.delivery_risk.consecutive_failures}</p></div></div></section>}

        <section className="surface-card p-5"><div className="section-heading"><Eye className="h-5 w-5 text-emerald-300"/><div><h3>Notification preview</h3><p>Exact rendered message without channel secrets</p></div></div><div className="mt-4 flex gap-2"><button className={`status-pill ${preview === 'telegram' ? 'border-cyan-400/50 text-cyan-300' : ''}`} onClick={() => setPreview('telegram')}>Telegram</button><button className={`status-pill ${preview === 'matrix' ? 'border-cyan-400/50 text-cyan-300' : ''}`} onClick={() => setPreview('matrix')}>Matrix</button></div><pre className="mt-3 max-h-72 overflow-auto whitespace-pre-wrap break-words rounded-xl border border-white/10 bg-slate-950/55 p-4 text-xs leading-6 text-slate-300" dir="auto">{selectedPreview || 'Preview is unavailable for alerts processed before this feature was enabled.'}</pre><div className="mt-4 space-y-2">{operations?.delivery?.length ? operations.delivery.map((item: any) => <div key={item.channel_id} className="flex flex-wrap items-center gap-2 rounded-xl border border-white/10 px-3 py-2 text-xs"><span className={`h-2 w-2 rounded-full ${item.status === 'delivered' ? 'bg-emerald-400' : item.status === 'retrying' ? 'bg-amber-400' : 'bg-red-400'}`}/><strong>{item.channel_name}</strong><span className="text-slate-500">{item.channel_type}</span><span className="ms-auto">{item.status} · attempt {item.attempt}</span>{item.updated_at && <span className="w-full text-slate-500">{formatDate(item.updated_at)}</span>}</div>) : <p className="text-xs text-slate-500">No per-channel delivery record is available.</p>}</div></section>

        <section className="surface-card p-5"><div className="section-heading"><Clock3 className="h-5 w-5 text-cyan-300"/><div><h3>Incident timeline</h3><p>{events.length} recorded events</p></div></div><div className="mt-5 space-y-0">{events.map((event, index) => { const Icon = iconFor(event.type || event.action); return <div key={`${event.id || event.occurred_at}-${index}`} className="timeline-row"><div className="timeline-rail"><span><Icon className="h-4 w-4"/></span>{index < events.length - 1 && <i/>}</div><div className="pb-5"><div className="flex flex-wrap items-center gap-2"><strong className="text-sm">{event.type || event.action}</strong><span className="text-xs text-slate-500">{event.occurred_at ? formatDate(event.occurred_at) : '—'}</span></div><p className="mt-1 text-sm leading-6 text-slate-400">{event.detail || event.status || 'Event recorded'}{event.actor ? ` · ${event.actor}` : ''}</p></div></div>})}</div></section>
        <div className="sticky bottom-3 flex flex-wrap gap-2 rounded-2xl border border-white/10 bg-[#111c2d]/95 p-3 shadow-xl backdrop-blur"><Button disabled={busy} variant="outline" onClick={() => act('acknowledged')}><ShieldCheck className="me-2 h-4 w-4"/>Acknowledge</Button><Button disabled={busy} onClick={() => act('resolved')}><CheckCircle2 className="me-2 h-4 w-4"/>Resolve</Button><Button disabled={busy} variant="secondary" onClick={() => api.resendAlert(token, alertId).then(() => toast.success('Notification queued'))}><RotateCw className="me-2 h-4 w-4"/>Resend</Button></div>
      </div>}
    </aside>
  </div>;
}
