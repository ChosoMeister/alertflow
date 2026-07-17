'use client';
import { useEffect, useState } from 'react';
import { useRouter } from '@/navigation';
import { Sidebar } from '@/components/sidebar';
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from '@/components/ui/card';
import { Brain, ExternalLink } from 'lucide-react';

export default function AIConfigPage() {
    const router = useRouter();
    useEffect(() => {
        if (!localStorage.getItem('alertflow_token')) router.push('/login');
    }, [router]);

    return (
        <div className="flex min-h-screen">
            <Sidebar />
            <main className="flex-1 ml-64 p-6">
                <h1 className="text-3xl font-bold mb-2">AI Configuration</h1>
                <p className="text-muted-foreground mb-6">Ollama model settings and prompt management</p>
                <Card>
                    <CardHeader>
                        <CardTitle className="flex items-center gap-2"><Brain className="h-5 w-5" />Ollama Settings</CardTitle>
                        <CardDescription>Configure via environment variables</CardDescription>
                    </CardHeader>
                    <CardContent className="space-y-3">
                        <div className="p-3 rounded-lg bg-muted/50 border border-border">
                            <p className="font-mono text-sm">OLLAMA_BASE_URL</p>
                            <p className="text-muted-foreground text-sm">http://host.docker.internal:11434/v1/chat/completions</p>
                        </div>
                        <div className="p-3 rounded-lg bg-muted/50 border border-border">
                            <p className="font-mono text-sm">OLLAMA_MODEL</p>
                            <p className="text-muted-foreground text-sm">gpt-oss:120b</p>
                        </div>
                        <p className="text-sm text-muted-foreground">Configure these in your .env file and restart services.</p>
                    </CardContent>
                </Card>
            </main>
        </div>
    );
}
