'use client';

import { useState, useCallback } from 'react';

import { toast as sonnerToast } from "sonner";

interface Toast {
    id?: string;
    title?: string;
    description?: string;
    variant?: 'default' | 'destructive';
}

export function useToast() {
    const toast = useCallback(({ title, description, variant }: Toast) => {
        if (variant === 'destructive') {
            sonnerToast.error(title, {
                description: description,
            });
        } else {
            sonnerToast.success(title, {
                description: description,
            });
        }
    }, []);

    return { toast };
}
