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

export function StatCard({ label, value, note, noteTone }: { label: string; value: ReactNode; note?: ReactNode; noteTone?: "warning" }) {
  return (
    <section className="card stat-card">
      <p className="stat-label">{label}</p>
      <p className="stat-value num">{value}</p>
      {note !== undefined && <p className={`stat-note${noteTone === "warning" ? " warning" : ""}`}>{note}</p>}
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

/** Page heading used on every screen: big title + one-line description, optional actions on the right. */
export function PageHead({ title, sub, children }: { title: string; sub?: string; children?: ReactNode }) {
  return (
    <div className="page-head">
      <div>
        <h2 className="page-title">{title}</h2>
        {sub && <p className="page-sub">{sub}</p>}
      </div>
      {children && <div className="toolbar">{children}</div>}
    </div>
  );
}

export interface TabDef<K extends string> {
  key: K;
  label: string;
  count?: number;
}

/** Filter tabs ("All 2 · To confirm 1 · …"), keyboard reachable, announced as a tab list. */
export function Tabs<K extends string>({ tabs, value, onChange, label }: { tabs: TabDef<K>[]; value: K; onChange: (k: K) => void; label: string }) {
  return (
    <div className="tabs" role="tablist" aria-label={label}>
      {tabs.map((t) => (
        <button key={t.key} role="tab" type="button" className="tab" aria-selected={t.key === value} onClick={() => onChange(t.key)}>
          {t.label}
          {t.count !== undefined && t.count > 0 && <span className="tab-count">{t.count}</span>}
        </button>
      ))}
    </div>
  );
}

/** Small confirm / form dialog. Closes on Escape and on a click outside the box. */
export function Dialog({ title, onClose, children }: { title: string; onClose: () => void; children: ReactNode }) {
  return (
    <div
      className="dialog-backdrop"
      onMouseDown={(e) => e.target === e.currentTarget && onClose()}
      onKeyDown={(e) => e.key === "Escape" && onClose()}
    >
      <div className="dialog" role="dialog" aria-modal="true" aria-label={title}>
        <h3 className="dialog-title">{title}</h3>
        {children}
      </div>
    </div>
  );
}
