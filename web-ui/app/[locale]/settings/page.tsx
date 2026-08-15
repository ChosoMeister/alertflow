'use client';

import { useEffect, useState } from 'react';
import { useRouter } from '@/navigation';
import { useTranslations } from 'next-intl';
import { toast } from 'sonner';
import { Sidebar } from '@/components/sidebar';
import { Card, CardHeader, CardTitle, CardDescription, CardContent, CardFooter } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { api } from '@/lib/api';
import { Settings, Lock, User, Shield } from 'lucide-react';
import useSWR from 'swr';
import { Skeleton } from '@/components/ui/skeleton';

export default function SettingsPage() {
    const router = useRouter();
    const t = useTranslations('Settings');
    const [token, setToken] = useState<string | null>(null);

    useEffect(() => {
        const storedToken = localStorage.getItem('alertflow_token');
        if (!storedToken) {
            router.push('/login');
            return;
        }
        setToken(storedToken);
    }, [router]);

    const fetcher = async ([url, authToken]: [string, string]) => {
        if (url === '/api/users/me') return api.getCurrentUser(authToken);
        if (url === '/api/settings/general') return api.getGeneralSettings(authToken);
    };

    const { data: userInfo, isLoading: userInfoLoading } = useSWR(
        token ? ['/api/users/me', token] : null, fetcher
    );
    const { data: generalSettings, isLoading: settingsLoading } = useSWR(
        token ? ['/api/settings/general', token] : null, fetcher
    );

    // Password change form
    const [currentPassword, setCurrentPassword] = useState('');
    const [newPassword, setNewPassword] = useState('');
    const [confirmPassword, setConfirmPassword] = useState('');
    const [changing, setChanging] = useState(false);

    // General Settings
    const [settings, setSettings] = useState({
        alert_retention_days: 14,
        summary_telegram_chat_id: '',
        summary_telegram_thread_id: '0',
        summary_telegram_bot_token: '',
        global_storm_max_notifications: 20,
        global_storm_window_seconds: 300,
        storm_summary_interval_seconds: 300,
        incident_sla_minutes: 60,
    });
    const [savingSettings, setSavingSettings] = useState(false);

    // Sync retention days when loaded
    useEffect(() => {
        if (generalSettings) {
            setSettings({
                alert_retention_days: generalSettings.alert_retention_days || 14,
                summary_telegram_chat_id: generalSettings.summary_telegram_chat_id || '',
                summary_telegram_thread_id: generalSettings.summary_telegram_thread_id || '0',
                summary_telegram_bot_token: generalSettings.summary_telegram_bot_token || '',
                global_storm_max_notifications: generalSettings.global_storm_max_notifications || 20,
                global_storm_window_seconds: generalSettings.global_storm_window_seconds || 300,
                storm_summary_interval_seconds: generalSettings.storm_summary_interval_seconds || 300,
                incident_sla_minutes: generalSettings.incident_sla_minutes || 60,
            });
        }
    }, [generalSettings]);

    async function handleSaveSettings() {
        setSavingSettings(true);
        try {
            await api.updateGeneralSettings(token!, {
                alert_retention_days: settings.alert_retention_days,
                summary_telegram_chat_id: settings.summary_telegram_chat_id,
                summary_telegram_thread_id: settings.summary_telegram_thread_id,
                summary_telegram_bot_token: settings.summary_telegram_bot_token,
                global_storm_max_notifications: settings.global_storm_max_notifications,
                global_storm_window_seconds: settings.global_storm_window_seconds,
                storm_summary_interval_seconds: settings.storm_summary_interval_seconds,
                incident_sla_minutes: settings.incident_sla_minutes,
            });
            toast.success(t('success_settings_saved'));
        } catch (e: any) {
            toast.error(e.message || t('error_settings_save'));
        } finally {
            setSavingSettings(false);
        }
    }

    async function handleChangePassword() {
        // Validation
        if (!currentPassword || !newPassword || !confirmPassword) {
            toast.error(t('error_fill_fields'));
            return;
        }
        if (newPassword !== confirmPassword) {
            toast.error(t('error_pass_mismatch'));
            return;
        }
        if (newPassword.length < 4) {
            toast.error(t('error_pass_length'));
            return;
        }

        setChanging(true);

        try {
            await api.changePassword(token!, currentPassword, newPassword);
            toast.success(t('success_pass_changed'));

            // Clear form
            setCurrentPassword('');
            setNewPassword('');
            setConfirmPassword('');

            // Logout after 2 seconds
            setTimeout(() => {
                localStorage.removeItem('alertflow_token');
                router.push('/login');
            }, 2000);
        } catch (e: any) {
            toast.error(e.message || t('error_pass_change'));
        } finally {
            setChanging(false);
        }
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

                <div className="grid gap-6 max-w-2xl">
                    {/* System Configuration Card */}
                    <Card>
                        <CardHeader>
                            <CardTitle className="flex items-center gap-2">
                                <Settings className="h-5 w-5" />
                                {t('system_config')}
                            </CardTitle>
                            <CardDescription>
                                {t('system_config_desc')}
                            </CardDescription>
                        </CardHeader>
                        <CardContent className="space-y-4">
                            <div className="space-y-2">
                                <label className="text-sm font-medium">{t('alert_retention')}</label>
                                {settingsLoading ? (
                                    <Skeleton className="h-10 w-full" />
                                ) : (
                                    <Input
                                        type="number"
                                        min="1"
                                        max="365"
                                        value={settings.alert_retention_days}
                                        onChange={(e) => setSettings({ ...settings, alert_retention_days: parseInt(e.target.value) || 14 })}
                                        placeholder="e.g. 14"
                                    />
                                )}
                                <p className="text-xs text-muted-foreground">
                                    {t('alert_retention_desc')}
                                </p>
                            </div>
                            <div className="grid grid-cols-1 md:grid-cols-2 gap-4 border-t pt-4">
                                <div className="space-y-2">
                                    <label className="text-sm font-medium">{t('storm_limit')}</label>
                                    <Input type="number" min="5" max="500" value={settings.global_storm_max_notifications} onChange={(e) => setSettings({ ...settings, global_storm_max_notifications: parseInt(e.target.value) || 20 })} />
                                </div>
                                <div className="space-y-2">
                                    <label className="text-sm font-medium">{t('storm_window')}</label>
                                    <Input type="number" min="60" max="3600" value={settings.global_storm_window_seconds} onChange={(e) => setSettings({ ...settings, global_storm_window_seconds: parseInt(e.target.value) || 300 })} />
                                </div>
                                <div className="space-y-2">
                                    <label className="text-sm font-medium">{t('storm_summary_interval')}</label>
                                    <Input type="number" min="30" max="3600" value={settings.storm_summary_interval_seconds} onChange={(e) => setSettings({ ...settings, storm_summary_interval_seconds: parseInt(e.target.value) || 300 })} />
                                </div>
                                <div className="space-y-2">
                                    <label className="text-sm font-medium">{t('incident_sla')}</label>
                                    <Input type="number" min="5" max="10080" value={settings.incident_sla_minutes} onChange={(e) => setSettings({ ...settings, incident_sla_minutes: parseInt(e.target.value) || 60 })} />
                                </div>
                            </div>
                        </CardContent>

                        <CardFooter>
                            <Button
                                onClick={handleSaveSettings}
                                disabled={savingSettings || settings.alert_retention_days < 1}
                                className="w-full"
                            >
                                {savingSettings ? t('saving') : t('save_config')}
                            </Button>
                        </CardFooter>
                    </Card>

                    {/* User Info Card */}
                    <Card>
                        <CardHeader>
                            <CardTitle className="flex items-center gap-2">
                                <User className="h-5 w-5" />
                                {t('current_user')}
                            </CardTitle>
                        </CardHeader>
                        <CardContent>
                            {userInfoLoading ? (
                                <div className="flex items-center gap-4">
                                    <Skeleton className="w-12 h-12 rounded-full" />
                                    <div className="space-y-2">
                                        <Skeleton className="h-5 w-32" />
                                        <Skeleton className="h-4 w-20" />
                                    </div>
                                </div>
                            ) : userInfo ? (
                                <div className="flex items-center gap-4">
                                    <div className="w-12 h-12 bg-primary/20 rounded-full flex items-center justify-center">
                                        <User className="h-6 w-6 text-primary" />
                                    </div>
                                    <div>
                                        <p className="font-medium text-lg">{userInfo.username}</p>
                                        <div className="flex items-center gap-2 text-sm text-muted-foreground">
                                            <Shield className="h-4 w-4" />
                                            <span className="capitalize">{userInfo.role}</span>
                                        </div>
                                    </div>
                                </div>
                            ) : (
                                <p className="text-muted-foreground">Failed to load user info</p>
                            )}
                        </CardContent>
                    </Card>

                    {/* Change Password Card */}
                    <Card>
                        <CardHeader>
                            <CardTitle className="flex items-center gap-2">
                                <Lock className="h-5 w-5" />
                                {t('change_password')}
                            </CardTitle>
                            <CardDescription>
                                {t('change_password_desc')}
                            </CardDescription>
                        </CardHeader>
                        <CardContent className="space-y-4">
                            <div className="space-y-2">
                                <label className="text-sm font-medium">{t('current_password')}</label>
                                <Input
                                    type="password"
                                    value={currentPassword}
                                    onChange={(e) => setCurrentPassword(e.target.value)}
                                    placeholder={t('current_password_placeholder')}
                                />
                            </div>

                            <div className="space-y-2">
                                <label className="text-sm font-medium">{t('new_password')}</label>
                                <Input
                                    type="password"
                                    value={newPassword}
                                    onChange={(e) => setNewPassword(e.target.value)}
                                    placeholder={t('new_password_placeholder')}
                                />
                            </div>

                            <div className="space-y-2">
                                <label className="text-sm font-medium">{t('confirm_password')}</label>
                                <Input
                                    type="password"
                                    value={confirmPassword}
                                    onChange={(e) => setConfirmPassword(e.target.value)}
                                    placeholder={t('confirm_password_placeholder')}
                                />
                            </div>

                            <Button
                                onClick={handleChangePassword}
                                disabled={changing || !currentPassword || !newPassword || !confirmPassword}
                                className="w-full"
                            >
                                {changing ? t('changing') : t('change_password')}
                            </Button>
                        </CardContent>
                    </Card>

                    {/* System Info Card */}
                    <Card>
                        <CardHeader>
                            <CardTitle className="flex items-center gap-2">
                                <Settings className="h-5 w-5" />
                                {t('system_info')}
                            </CardTitle>
                        </CardHeader>
                        <CardContent>
                            <div className="grid grid-cols-2 gap-4 text-sm">
                                <div>
                                    <p className="text-muted-foreground">{t('version')}</p>
                                    <p className="font-medium">2.0.0</p>
                                </div>
                                <div>
                                    <p className="text-muted-foreground">{t('auth_method')}</p>
                                    <p className="font-medium">Redis-backed JWT</p>
                                </div>
                            </div>
                        </CardContent>
                    </Card>
                </div>
            </main>
        </div>
    );
}
