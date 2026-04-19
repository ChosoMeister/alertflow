'use client';

import { useState, useCallback } from 'react';

interface Toast {
    id: string;
    title?: string;
    description?: string;
    variant?: 'default' | 'destructive';
}

// Simple toast implementation using browser alert for now
// Can be replaced with a proper toast library later
export function useToast() {
    const toast = useCallback(({ title, description, variant }: Omit<Toast, 'id'>) => {
        // For now, just use console.log - proper toast can be added later
        if (variant === 'destructive') {
            console.error(`[Toast Error] ${title}: ${description}`);
        } else {
            console.log(`[Toast] ${title}: ${description}`);
        }

        // Optional: show browser notification or simple alert
        // For a non-intrusive UX, we'll just log to console
        // You can enable alert by uncommenting:
        // alert(`${title}\n${description}`);
    }, []);

    return { toast };
}
