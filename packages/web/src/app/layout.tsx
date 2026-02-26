import './globals.css';
import type { Metadata } from 'next';

export const metadata: Metadata = {
  title: 'Polypaper - Paper Trading Dashboard',
  description: 'Paper trading system for Polymarket + Crypto',
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
