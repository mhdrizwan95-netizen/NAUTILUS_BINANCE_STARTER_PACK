import type { AppProps } from 'next/app'
import { IBM_Plex_Mono, Inter } from 'next/font/google'
import '../styles/globals.css'

const inter = Inter({ subsets: ['latin'], variable: '--font-inter' })
const plex = IBM_Plex_Mono({ subsets: ['latin'], weight: ['400', '500', '600'], variable: '--font-plex' })

export default function App({ Component, pageProps }: AppProps) {
  return (
    <div className={`${inter.variable} ${plex.variable}`}>
      <Component {...pageProps} />
    </div>
  )
}
