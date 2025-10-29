import Link from 'next/link'

export default function Home() {
  return (
    <main className="min-h-screen grid place-items-center">
      <div className="text-center space-y-4">
        <h1 className="text-3xl font-semibold">Nautilus Command Center</h1>
        <p className="text-text-secondary">Open the live cockpit prototype</p>
        <Link className="px-4 py-2 rounded-md bg-white/10 hover:bg-white/20 transition" href="/dashboard">
          Go to Dashboard
        </Link>
      </div>
    </main>
  )
}
