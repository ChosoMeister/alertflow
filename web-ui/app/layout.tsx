import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
    title: "Sentinel-AI-Core Dashboard",
    description: "AI-powered alert processing and notification system",
};

export default function RootLayout({
    children,
}: {
    children: React.ReactNode;
}) {
    return (
        <html lang="en" className="dark">
            <body className="min-h-screen bg-background antialiased">
                {children}
            </body>
        </html>
    );
}
