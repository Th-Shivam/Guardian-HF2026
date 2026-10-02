import './App.css'

/**
 * Placeholder shell.
 *
 * The dashboard is intentionally unimplemented — this exists so the frontend
 * builds and runs as part of the monorepo foundation.
 */
export default function App() {
  return (
    <main className="shell">
      <h1>Guardian</h1>
      <p className="tagline">A WhatsApp-first AI safety assistant.</p>
      <p className="note">
        Foundation only. Message analysis, WhatsApp delivery and the dashboard
        are not built yet.
      </p>
    </main>
  )
}
