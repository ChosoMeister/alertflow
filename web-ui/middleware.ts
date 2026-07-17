import createMiddleware from 'next-intl/middleware';
import { routing } from './navigation';
import { NextRequest } from 'next/server';

const intlMiddleware = createMiddleware(routing);

export default function middleware(request: NextRequest) {
  // Run the next-intl middleware
  const response = intlMiddleware(request);

  // Intercept the response and remove port 3000 from redirect URLs
  if (response.status >= 300 && response.status < 400) {
    const location = response.headers.get('location');
    if (location && location.includes(':3000')) {
      response.headers.set('location', location.replace(':3000', ''));
    }
  }

  return response;
}

export const config = {
  matcher: ['/((?!api|_next|.*\\..*).*)']
};
