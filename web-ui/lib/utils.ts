import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
    return twMerge(clsx(inputs));
}

export function formatDate(dateString: string): string {
    if (!dateString) return '';
    const numeric = Number(dateString);
    if (Number.isFinite(numeric) && numeric > 0) {
        const milliseconds = numeric < 10_000_000_000 ? numeric * 1000 : numeric;
        return new Date(milliseconds).toLocaleString();
    }
    // Backend stores UTC timestamps without timezone marker.
    // Append 'Z' so the browser correctly interprets them as UTC
    // and toLocaleString() converts to the user's local timezone.
    const utcString = dateString.endsWith('Z') || dateString.includes('+') || dateString.includes('-', 10)
        ? dateString
        : dateString + 'Z';
    const date = new Date(utcString);
    return Number.isNaN(date.getTime()) ? '—' : date.toLocaleString();
}


export function truncate(str: string, length: number): string {
    if (!str) return '';
    return str.length > length ? str.slice(0, length) + '...' : str;
}

export function severityColor(severity: string): string {
    switch (severity?.toLowerCase()) {
        case 'critical': return 'text-red-500';
        case 'high': return 'text-orange-500';
        case 'medium': return 'text-yellow-500';
        case 'low': return 'text-green-500';
        case 'info': return 'text-blue-400';
        default: return 'text-gray-400';
    }
}

export function statusColor(status: string): string {
    switch (status?.toLowerCase()) {
        case 'new': return 'bg-blue-500/20 text-blue-400 border-blue-500/30';
        case 'acknowledged': return 'bg-yellow-500/20 text-yellow-400 border-yellow-500/30';
        case 'resolved': return 'bg-green-500/20 text-green-400 border-green-500/30';
        case 'duplicate': return 'bg-purple-500/20 text-purple-400 border-purple-500/30';
        case 'redundant': return 'bg-gray-700/20 text-gray-500 border-gray-700/30';
        default: return 'bg-gray-500/20 text-gray-400 border-gray-500/30';
    }
}
