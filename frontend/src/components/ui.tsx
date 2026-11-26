import { AlertCircle } from "lucide-react";
import type { ReactNode } from "react";

export function Skeleton({ w = "100%", h = 16 }: { w?: number | string; h?: number }) {
  return <span className="skeleton" style={{ display: "block", width: w, height: h }} aria-hidden="true" />;
}

export function ErrorNote({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  return (
    <div className="form-error" role="alert">
      <AlertCircle size={16} aria-hidden="true" />
      <span style={{ flex: 1 }}>{error instanceof Error ? error.message : "Something went wrong."}</span>
      {onRetry && (
        <button className="link-btn" onClick={onRetry}>
          Try again
        </button>
      )}
    </div>
  );
}

export function StatCard({ label, value, note, noteTone }: { label: string; value: ReactNode; note: ReactNode; noteTone?: "warning" }) {
  return (
    <section className="card stat-card">
      <p className="stat-label">{label}</p>
      <p className="stat-value num">{value}</p>
      <p className={`stat-note${noteTone === "warning" ? " warning" : ""}`}>{note}</p>
    </section>
  );
}

export function ComingSoon({ title }: { title: string }) {
  return (
    <section className="card empty" style={{ padding: 48 }}>
      <strong>{title}</strong>
      This screen is being built and will arrive in the next update.
    </section>
  );
}
