import { AlertCircle, CheckCircle2 } from "lucide-react";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { useSearchParams } from "react-router";

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
const FOCUSABLE =
  'a[href], button:not([disabled]), input:not([disabled]):not([type="hidden"]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

/**
 * A modal dialog: moves focus inside on open (to an autoFocus field, else the first control), keeps Tab
 * inside, closes on Escape or a backdrop click, stops the page behind from scrolling, and gives focus
 * back to whatever opened it.
 */
/** Open dialogs, newest last: only the top one answers Escape and keeps Tab inside it. */
const openDialogs: object[] = [];
let pageOverflow = "";

export function Dialog({ title, onClose, children, className, hideTitle }: { title: string; onClose: () => void; children: ReactNode; className?: string; hideTitle?: boolean }) {
  const ref = useRef<HTMLDivElement>(null);
  const closeRef = useRef(onClose);
  closeRef.current = onClose;

  useEffect(() => {
    const me = {};
    // The page behind stays still while any dialog is open, whichever order they close in.
    if (openDialogs.push(me) === 1) {
      pageOverflow = document.body.style.overflow;
      document.body.style.overflow = "hidden";
    }
    const opener = document.activeElement as HTMLElement | null;
    const box = ref.current;
    if (box && !box.contains(document.activeElement)) {
      const first = box.querySelector<HTMLElement>("[autofocus], [data-autofocus]") ?? box.querySelector<HTMLElement>(FOCUSABLE);
      (first ?? box).focus();
    }
    const onKey = (e: KeyboardEvent) => {
      if (openDialogs[openDialogs.length - 1] !== me) return;
      if (e.key === "Escape") {
        e.stopPropagation();
        closeRef.current();
      } else if (e.key === "Tab" && box) {
        const items = [...box.querySelectorAll<HTMLElement>(FOCUSABLE)].filter((el) => el.offsetParent !== null);
        const first = items[0];
        const last = items[items.length - 1];
        if (!first || !last) return;
        if (e.shiftKey && document.activeElement === first) {
          e.preventDefault();
          last.focus();
        } else if (!e.shiftKey && document.activeElement === last) {
          e.preventDefault();
          first.focus();
        }
      }
    };
    document.addEventListener("keydown", onKey);
    return () => {
      openDialogs.splice(openDialogs.indexOf(me), 1);
      if (openDialogs.length === 0) document.body.style.overflow = pageOverflow;
      document.removeEventListener("keydown", onKey);
      if (opener && document.contains(opener)) opener.focus();
    };
  }, []);

  return (
    <div className="dialog-backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className={`dialog ${className ?? ""}`} role="dialog" aria-modal="true" aria-label={title} ref={ref} tabIndex={-1}>
        {!hideTitle && <h3 className="dialog-title">{title}</h3>}
        {children}
      </div>
    </div>
  );
}

/** A table row that selects an item on click, Enter or Space. */
export function RowButton({ selected, onSelect, children }: { selected: boolean; onSelect: () => void; children: ReactNode }) {
  return (
    <tr
      className="selectable"
      aria-selected={selected}
      tabIndex={0}
      onClick={onSelect}
      onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && (e.preventDefault(), onSelect())}
    >
      {children}
    </tr>
  );
}

/** Green confirmation line after an action succeeds. */
export function Done({ text }: { text: string | null }) {
  if (!text) return null;
  return (
    <p className="form-ok" role="status">
      <CheckCircle2 size={16} aria-hidden="true" /> {text}
    </p>
  );
}

/** Label + control + optional hint, stacked. */
export function Field({ id, label, hint, children }: { id: string; label: string; hint?: string; children: ReactNode }) {
  return (
    <div className="field">
      <label htmlFor={id}>{label}</label>
      {children}
      {hint && <span className="field-hint">{hint}</span>}
    </div>
  );
}

/** Empty table body row. */
export function EmptyRow({ cols, text }: { cols: number; text: string }) {
  return (
    <tr>
      <td colSpan={cols} className="empty">
        {text}
      </td>
    </tr>
  );
}

/** Loading table body row. */
export function LoadingRow({ cols }: { cols: number }) {
  return (
    <tr>
      <td colSpan={cols}>
        <Skeleton h={48} />
      </td>
    </tr>
  );
}

/** Message from a failed mutation or validation, shown as an alert. */
export function FormError({ error }: { error: unknown }) {
  if (!error) return null;
  return (
    <p className="form-error" role="alert">
      {typeof error === "string" ? error : error instanceof Error ? error.message : "Something went wrong."}
    </p>
  );
}

/** "Showing 6 of 12 · Previous 1 2 Next" under a table. */
export function Pager({
  page,
  pages,
  total,
  shown,
  noun,
  onPage,
}: {
  page: number;
  pages: number;
  total: number;
  shown: number;
  noun: string;
  onPage: (p: number) => void;
}) {
  return (
    <div className="pager">
      <span>{shown === total ? `${total} ${noun}` : `Showing ${shown} of ${total} ${noun}`}</span>
      {pages > 1 && (
        <nav aria-label="Pages" className="pager-nav">
          <button className="link-btn" disabled={page === 0} onClick={() => onPage(page - 1)}>
            Previous
          </button>
          {Array.from({ length: pages }, (_, i) => (
            <button key={i} className="link-btn" aria-current={i === page ? "page" : undefined} onClick={() => onPage(i)}>
              {i + 1}
            </button>
          ))}
          <button className="link-btn" disabled={page >= pages - 1} onClick={() => onPage(page + 1)}>
            Next
          </button>
        </nav>
      )}
    </div>
  );
}

export const PAGE_SIZE = 8;

/** Slice a list for the current page; resets to the last page if the list shrinks. */
export function paginate<T>(items: T[], page: number, size = PAGE_SIZE): { rows: T[]; pages: number; page: number } {
  const pages = Math.max(1, Math.ceil(items.length / size));
  const p = Math.min(page, pages - 1);
  return { rows: items.slice(p * size, p * size + size), pages, page: p };
}

/** The selected row of a list page, opened from a link such as /task-orders?open=24 (search, activity). */
export function useSelectedFromUrl(): [number | null, (id: number | null) => void] {
  const [params] = useSearchParams();
  const open = Number(params.get("open")) || null;
  const [id, setId] = useState<number | null>(open);
  useEffect(() => {
    if (open) setId(open);
  }, [open]);
  return [id, setId];
}
