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

    const handleLogout = () => {
        localStorage.removeItem('alertflow_token');
        window.location.href = '/login';
    };

    return (
        <aside className="fixed inset-y-0 ltr:left-0 rtl:right-0 z-50 w-64 bg-card border-r border-border rtl:border-l rtl:border-r-0">
            <div className="flex h-full flex-col">
                {/* Logo */}
                <div className="flex h-16 items-center px-6 border-b border-border">
                    <div className="flex items-center gap-2">
                        <div className="w-8 h-8 rounded-lg bg-primary flex items-center justify-center">
                            <span className="text-white font-bold text-sm">S</span>
                        </div>
                        <span className="font-semibold text-lg">AlertFlow</span>
                    </div>
                </div>

                {/* Navigation */}
                <nav className="flex-1 space-y-1 px-3 py-4">
                    {navigation.map((item) => {
                        const isActive = pathname === item.href ||
                            (item.href !== '/' && pathname.startsWith(item.href));

                        return (
                            <Link
                                key={item.name}
                                href={item.href}
                                className={cn(
                                    'flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors',
                                    isActive
                                        ? 'bg-primary/10 text-primary'
                                        : 'text-muted-foreground hover:bg-muted hover:text-foreground'
                                )}
                            >
                                <item.icon className="h-5 w-5" />
                                {item.name}
                            </Link>
                        );
                    })}
                </nav>

                {/* Footer / Actions */}
                <div className="border-t border-border p-3 flex flex-col gap-2">
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
