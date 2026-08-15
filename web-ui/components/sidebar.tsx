'use client';

import { useTranslations } from 'next-intl';
import { Link, usePathname } from '@/navigation';
import { cn } from '@/lib/utils';
import {
    LayoutDashboard,
    AlertCircle,
    Route,
    Layers,
    Brain,
    Plug,
    Mail,
    ScrollText,
    Settings,
    LogOut,
    Bot,
    Bell,
    BarChart3,
} from 'lucide-react';
import { LanguageSwitcher } from './LanguageSwitcher';
import { api } from '@/lib/api';
import { CommandPalette } from './command-palette';

const getNavigation = (t: any) => [
    { name: t('dashboard'), href: '/', icon: LayoutDashboard },
    { name: t('alerts'), href: '/alerts', icon: AlertCircle },
    { name: t('analytics'), href: '/analytics', icon: BarChart3 },
    { name: t('routing'), href: '/routing', icon: Route },
    { name: t('queue'), href: '/queue', icon: Layers },
    { name: t('providers'), href: '/ai-providers', icon: Bot },
    { name: t('channels'), href: '/notification-channels', icon: Bell },
    { name: t('smtp'), href: '/smtp', icon: Mail },
    { name: t('logs'), href: '/logs', icon: ScrollText },
    { name: t('settings'), href: '/settings', icon: Settings },
];

export function Sidebar() {
    const pathname = usePathname();
    const t = useTranslations('Navigation');
    const navigation = getNavigation(t);

    const handleLogout = async () => {
        await api.logout().catch(() => undefined);
        localStorage.removeItem('alertflow_token');
        localStorage.removeItem('alertflow_user');
        window.location.href = '/login';
    };

    return (
        <aside className="fixed inset-x-0 bottom-0 z-50 h-16 border-t border-white/10 bg-[#0b1320]/95 backdrop-blur-xl lg:inset-y-0 lg:h-auto lg:w-64 lg:border-t-0 lg:ltr:left-0 lg:rtl:right-0 lg:ltr:border-r lg:rtl:border-l">
            <div className="flex h-full flex-col">
                {/* Logo */}
                <div className="hidden h-20 items-center border-b border-white/10 px-5 lg:flex">
                    <div className="flex items-center gap-2">
                        <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br from-cyan-400 to-blue-600 shadow-lg shadow-cyan-500/20">
                            <span className="text-white font-black text-sm">S</span>
                        </div>
                        <div><span className="block font-semibold text-lg leading-5">AlertFlow</span><span className="text-[10px] uppercase tracking-[.22em] text-cyan-400">Operations Core</span></div>
                    </div>
                </div>

                {/* Navigation */}
                <div className="hidden px-3 pt-4 lg:block"><CommandPalette /></div>
                <nav className="flex h-full items-center justify-around overflow-x-auto px-2 lg:block lg:h-auto lg:flex-1 lg:space-y-1 lg:px-3 lg:py-4">
                    {navigation.map((item, index) => {
                        const isActive = pathname === item.href ||
                            (item.href !== '/' && pathname.startsWith(item.href));

                        return (
                            <Link
                                key={item.name}
                                href={item.href}
                                className={cn(
                                'flex min-w-[4.2rem] flex-col items-center gap-1 rounded-xl px-2 py-2 text-[10px] font-medium transition-all lg:min-w-0 lg:flex-row lg:gap-3 lg:px-3 lg:text-sm',
                                    isActive ? 'bg-cyan-400/10 text-cyan-300' : 'text-slate-500 hover:bg-white/5 hover:text-slate-200',
                                    index > 4 && 'hidden lg:flex'
                                )}
                            >
                                <item.icon className="h-5 w-5" />
                                {item.name}
                            </Link>
                        );
                    })}
                </nav>

                {/* Footer / Actions */}
                <div className="hidden border-t border-white/10 p-3 lg:flex lg:flex-col lg:gap-2">
                    <div className="flex items-center justify-between px-3 py-2 text-sm text-muted-foreground">
                        <span>{t('language')}</span>
                        <LanguageSwitcher />
                    </div>
                    <button
                        onClick={handleLogout}
                        className="flex w-full items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium text-destructive hover:bg-destructive/10 transition-colors"
                    >
                        <LogOut className="h-5 w-5" />
                        {t('logout')}
                    </button>
                </div>
            </div>
        </aside>
    );
}
