"use client";

import { useLocale } from 'next-intl';
import { useRouter, usePathname } from 'next/navigation';
import { Button } from "@/components/ui/button";

export function LanguageSwitcher() {
    const locale = useLocale();
    const router = useRouter();
    const pathname = usePathname();

    const toggleLanguage = () => {
        const nextLocale = locale === 'en' ? 'fa' : 'en';

        // Remove current locale from pathname
        const pathWithoutLocale = pathname.replace(`/${locale}`, '') || '/';

        // Redirect to new locale
        router.replace(`/${nextLocale}${pathWithoutLocale}`);
    };

    return (
        <Button
            variant="ghost"
            size="sm"
            onClick={toggleLanguage}
            className="w-12 px-0 font-medium"
        >
            {locale === 'en' ? 'FA' : 'EN'}
        </Button>
    );
}
