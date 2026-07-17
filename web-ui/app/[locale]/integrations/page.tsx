'use client';
import { useEffect } from 'react';
import { useRouter } from '@/navigation';
import { Sidebar } from '@/components/sidebar';
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from '@/components/ui/card';
import { Plug, Send, MessageSquare, Bell } from 'lucide-react';

export default function IntegrationsPage() {
    const router = useRouter();
    useEffect(() => {
        if (!localStorage.getItem('alertflow_token')) router.push('/login');
    }, [router]);

    return (
        <div className="flex min-h-screen">
            <Sidebar />
            <main className="flex-1 ml-64 p-6">
                <h1 className="text-3xl font-bold mb-2">Integrations</h1>
                <p className="text-muted-foreground mb-6">Telegram and Matrix notification settings</p>
                <div className="grid gap-6 md:grid-cols-2">
                    <Card>
                        <CardHeader>
                            <CardTitle className="flex items-center gap-2"><Send className="h-5 w-5 text-blue-500" />Telegram</CardTitle>
                            <CardDescription>Bot token and default destinations</CardDescription>
                        </CardHeader>
                        <CardContent className="text-sm text-muted-foreground">
                            Configure TELEGRAM_BOT_TOKEN, TELEGRAM_DEFAULT_CHAT_ID in .env
                        </CardContent>
                    </Card>
                    <Card>
                        <CardHeader>
                            <CardTitle className="flex items-center gap-2"><MessageSquare className="h-5 w-5 text-green-500" />Matrix</CardTitle>
                            <CardDescription>Homeserver and access token</CardDescription>
                        </CardHeader>
                        <CardContent className="text-sm text-muted-foreground">
                            Configure MATRIX_HOMESERVER_URL, MATRIX_ACCESS_TOKEN in .env
                        </CardContent>
                    </Card>
                </div>
            </main>
        </div>
    );
}
