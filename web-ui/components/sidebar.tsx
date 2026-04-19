'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
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
} from 'lucide-react';

const navigation = [
    { name: 'Overview', href: '/', icon: LayoutDashboard },
    { name: 'Alerts', href: '/alerts', icon: AlertCircle },
    { name: 'Routing Rules', href: '/routing', icon: Route },
    { name: 'Queue', href: '/queue', icon: Layers },
    { name: 'AI Providers', href: '/ai-providers', icon: Bot },
    { name: 'Channels', href: '/notification-channels', icon: Bell },
    { name: 'SMTP Debugger', href: '/smtp', icon: Mail },
    { name: 'Logs', href: '/logs', icon: ScrollText },
    { name: 'Settings', href: '/settings', icon: Settings },
];

export function Sidebar() {
    const pathname = usePathname();

    const handleLogout = () => {
        localStorage.removeItem('sentinel_token');
        window.location.href = '/login';
    };

    return (
        <aside className="fixed inset-y-0 left-0 z-50 w-64 bg-card border-r border-border">
            <div className="flex h-full flex-col">
                {/* Logo */}
                <div className="flex h-16 items-center px-6 border-b border-border">
                    <div className="flex items-center gap-2">
                        <div className="w-8 h-8 rounded-lg bg-primary flex items-center justify-center">
                            <span className="text-white font-bold text-sm">S</span>
                        </div>
                        <span className="font-semibold text-lg">Sentinel AI</span>
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

                {/* Logout */}
                <div className="border-t border-border p-3">
                    <button
                        onClick={handleLogout}
                        className="flex w-full items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium text-muted-foreground hover:bg-muted hover:text-foreground transition-colors"
                    >
                        <LogOut className="h-5 w-5" />
                        Logout
                    </button>
                </div>
            </div>
        </aside>
    );
}
