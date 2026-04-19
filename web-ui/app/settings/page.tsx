'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { Sidebar } from '@/components/sidebar';
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { api } from '@/lib/api';
import { Settings, Lock, User, CheckCircle, AlertCircle, Shield } from 'lucide-react';

export default function SettingsPage() {
    const router = useRouter();
    const [token, setToken] = useState<string | null>(null);
    const [userInfo, setUserInfo] = useState<{ username: string; role: string } | null>(null);

    // Password change form
    const [currentPassword, setCurrentPassword] = useState('');
    const [newPassword, setNewPassword] = useState('');
    const [confirmPassword, setConfirmPassword] = useState('');
    const [changing, setChanging] = useState(false);
    const [message, setMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null);

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
            loadUserInfo();
        }
    }, [token]);

    async function loadUserInfo() {
        try {
            const info = await api.getCurrentUser(token!);
            setUserInfo(info);
        } catch (e) {
            console.error(e);
        }
    }

    async function handleChangePassword() {
        // Validation
        if (!currentPassword || !newPassword || !confirmPassword) {
            setMessage({ type: 'error', text: 'Please fill in all fields' });
            return;
        }
        if (newPassword !== confirmPassword) {
            setMessage({ type: 'error', text: 'New passwords do not match' });
            return;
        }
        if (newPassword.length < 4) {
            setMessage({ type: 'error', text: 'Password must be at least 4 characters' });
            return;
        }

        setChanging(true);
        setMessage(null);

        try {
            await api.changePassword(token!, currentPassword, newPassword);
            setMessage({ type: 'success', text: 'Password changed successfully! Please log in again.' });

            // Clear form
            setCurrentPassword('');
            setNewPassword('');
            setConfirmPassword('');

            // Logout after 2 seconds
            setTimeout(() => {
                localStorage.removeItem('sentinel_token');
                router.push('/login');
            }, 2000);
        } catch (e: any) {
            setMessage({ type: 'error', text: e.message || 'Failed to change password' });
        } finally {
            setChanging(false);
        }
    }

    if (!token) return null;

    return (
        <div className="flex min-h-screen">
            <Sidebar />
            <main className="flex-1 ml-64 p-6">
                <h1 className="text-3xl font-bold mb-2">Settings</h1>
                <p className="text-muted-foreground mb-6">
                    Manage your account and application settings
                </p>

                <div className="grid gap-6 max-w-2xl">
                    {/* User Info Card */}
                    <Card>
                        <CardHeader>
                            <CardTitle className="flex items-center gap-2">
                                <User className="h-5 w-5" />
                                Current User
                            </CardTitle>
                        </CardHeader>
                        <CardContent>
                            {userInfo ? (
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
                                <p className="text-muted-foreground">Loading...</p>
                            )}
                        </CardContent>
                    </Card>

                    {/* Change Password Card */}
                    <Card>
                        <CardHeader>
                            <CardTitle className="flex items-center gap-2">
                                <Lock className="h-5 w-5" />
                                Change Password
                            </CardTitle>
                            <CardDescription>
                                Update your account password. You will be logged out after changing.
                            </CardDescription>
                        </CardHeader>
                        <CardContent className="space-y-4">
                            {message && (
                                <div className={`flex items-center gap-2 p-3 rounded-lg ${message.type === 'success'
                                        ? 'bg-green-500/20 text-green-400'
                                        : 'bg-red-500/20 text-red-400'
                                    }`}>
                                    {message.type === 'success' ? (
                                        <CheckCircle className="h-5 w-5" />
                                    ) : (
                                        <AlertCircle className="h-5 w-5" />
                                    )}
                                    <span>{message.text}</span>
                                </div>
                            )}

                            <div className="space-y-2">
                                <label className="text-sm font-medium">Current Password</label>
                                <Input
                                    type="password"
                                    value={currentPassword}
                                    onChange={(e) => setCurrentPassword(e.target.value)}
                                    placeholder="Enter current password"
                                />
                            </div>

                            <div className="space-y-2">
                                <label className="text-sm font-medium">New Password</label>
                                <Input
                                    type="password"
                                    value={newPassword}
                                    onChange={(e) => setNewPassword(e.target.value)}
                                    placeholder="Enter new password"
                                />
                            </div>

                            <div className="space-y-2">
                                <label className="text-sm font-medium">Confirm New Password</label>
                                <Input
                                    type="password"
                                    value={confirmPassword}
                                    onChange={(e) => setConfirmPassword(e.target.value)}
                                    placeholder="Confirm new password"
                                />
                            </div>

                            <Button
                                onClick={handleChangePassword}
                                disabled={changing || !currentPassword || !newPassword || !confirmPassword}
                                className="w-full"
                            >
                                {changing ? 'Changing...' : 'Change Password'}
                            </Button>
                        </CardContent>
                    </Card>

                    {/* System Info Card */}
                    <Card>
                        <CardHeader>
                            <CardTitle className="flex items-center gap-2">
                                <Settings className="h-5 w-5" />
                                System Information
                            </CardTitle>
                        </CardHeader>
                        <CardContent>
                            <div className="grid grid-cols-2 gap-4 text-sm">
                                <div>
                                    <p className="text-muted-foreground">Version</p>
                                    <p className="font-medium">2.0.0</p>
                                </div>
                                <div>
                                    <p className="text-muted-foreground">Authentication</p>
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
