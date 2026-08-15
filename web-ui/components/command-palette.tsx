'use client';

import { useEffect, useMemo, useState } from 'react';
import { useRouter } from '@/navigation';
import { Search, LayoutDashboard, AlertTriangle, BarChart3, Bot, Bell, Settings, ScrollText } from 'lucide-react';

const commands = [
  { label: 'Dashboard', hint: 'Overview & health', href: '/', icon: LayoutDashboard },
  { label: 'Incidents', hint: 'Search and respond', href: '/alerts', icon: AlertTriangle },
  { label: 'Analytics', hint: 'Trends & SLO', href: '/analytics', icon: BarChart3 },
  { label: 'AI providers', hint: 'Primary & fallback', href: '/ai-providers', icon: Bot },
  { label: 'Notification channels', hint: 'Delivery targets', href: '/notification-channels', icon: Bell },
  { label: 'Logs', hint: 'Live service logs', href: '/logs', icon: ScrollText },
  { label: 'Settings', hint: 'Storm, summary & retention', href: '/settings', icon: Settings },
];

export function CommandPalette() {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  const filtered = useMemo(() => commands.filter(item => `${item.label} ${item.hint}`.toLowerCase().includes(query.toLowerCase())), [query]);

  useEffect(() => {
    const handler = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault(); setOpen(value => !value);
      }
      if (event.key === 'Escape') setOpen(false);
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, []);

  if (!open) return <button onClick={() => setOpen(true)} className="command-trigger"><Search className="h-4 w-4" /><span>Quick search</span><kbd>⌘K</kbd></button>;

  return (
    <div className="fixed inset-0 z-[100] flex items-start justify-center bg-slate-950/70 px-4 pt-[12vh] backdrop-blur-sm" onMouseDown={() => setOpen(false)}>
      <div className="w-full max-w-xl overflow-hidden rounded-2xl border border-white/10 bg-[#101827] shadow-2xl shadow-black/50" onMouseDown={event => event.stopPropagation()}>
        <div className="flex items-center gap-3 border-b border-white/10 px-4"><Search className="h-5 w-5 text-cyan-400"/><input autoFocus value={query} onChange={e => setQuery(e.target.value)} placeholder="Search pages and actions…" className="h-14 flex-1 bg-transparent text-sm outline-none placeholder:text-slate-500"/><kbd className="rounded border border-white/10 px-2 py-1 text-xs text-slate-500">ESC</kbd></div>
        <div className="max-h-80 overflow-y-auto p-2">
          {filtered.map(item => <button key={item.href} onClick={() => { setOpen(false); router.push(item.href); }} className="flex w-full items-center gap-3 rounded-xl px-3 py-3 text-start hover:bg-white/5"><span className="rounded-lg bg-cyan-400/10 p-2 text-cyan-300"><item.icon className="h-4 w-4"/></span><span className="flex-1"><span className="block text-sm font-medium">{item.label}</span><span className="block text-xs text-slate-500">{item.hint}</span></span><span className="text-slate-600">↵</span></button>)}
          {!filtered.length && <p className="p-8 text-center text-sm text-slate-500">No command found</p>}
        </div>
      </div>
    </div>
  );
}
