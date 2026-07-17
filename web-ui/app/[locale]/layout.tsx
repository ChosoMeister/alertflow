import type { Metadata } from "next";
import "../globals.css";
import { NextIntlClientProvider } from 'next-intl';
import { getMessages } from 'next-intl/server';
import { notFound } from 'next/navigation';
import { Toaster } from "@/components/ui/sonner";

export const metadata: Metadata = {
    title: "AlertFlow Dashboard",
    description: "AI-powered alert processing and notification system",
};

export default async function RootLayout({
    children,
    params: { locale }
}: {
    children: React.ReactNode;
    params: { locale: string };
}) {
    // Validate that the incoming `locale` parameter is valid
    if (!['en', 'fa'].includes(locale)) notFound();

    // Receiving messages provided in `i18n.ts`
    const messages = await getMessages();

    return (
        <html lang={locale} dir={locale === 'fa' ? 'rtl' : 'ltr'} className="dark" suppressHydrationWarning>
            <body className="min-h-screen bg-background antialiased">
                <NextIntlClientProvider messages={messages}>
                    {children}
                    <Toaster />
                </NextIntlClientProvider>
            </body>
        </html>
    );
}
