import type { Metadata } from 'next'
import { Inter, Playfair_Display } from 'next/font/google'
import './globals.css'

const playfair = Playfair_Display({
  subsets: ['latin'],
  weight: ['400', '500'],
  variable: '--font-playfair',
})

const inter = Inter({
  subsets: ['latin'],
  weight: ['400', '500', '600'],
  variable: '--font-inter',
})

export const metadata: Metadata = {
  title: 'DistroAgent — Find Boutiques That Will Love Your Brand',
  description:
    'Drop your Shopify URL. See which boutiques match your aesthetic in 60 seconds.',
  openGraph: {
    title: 'Find Your Perfect Boutique Partners',
    description: 'AI-powered wholesale distribution for D2C beauty brands.',
  },
}

export default function RootLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <html lang="en">
      <body className={`${playfair.variable} ${inter.variable} bg-bg font-sans`}>
        {children}
      </body>
    </html>
  )
}
