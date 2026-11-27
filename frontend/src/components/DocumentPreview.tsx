import { Minus, Plus } from "lucide-react";
import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { apiBlob, saveBlob } from "../api/client";
import "../pages/pages.css";
import "./DocumentPreview.css";
import { Dialog, FormError, Skeleton } from "./ui";

export interface PreviewEmail {
  to: string;
  subject: string;
  text: string;
}

export interface PreviewRequest {
  /** e.g. "Invoice SP-INV-2026-004" or "Receipt preview". */
  title: string;
  /** The name it is saved under. */
  filename: string;
  /** Fetches the exact bytes: what is shown is what is downloaded, issued or sent. */
  load: () => Promise<Blob>;
  /** A line above the document, e.g. what changes once it is issued. */
  note?: string;
  /** For something about to be emailed: the message exactly as it will go out. */
  email?: () => Promise<PreviewEmail>;
  /** The step this preview leads to ("Issue invoice", "Send offer"). Without it, the preview offers Download. */
  confirm?: { label: string; run: () => Promise<unknown> };
}

const PreviewContext = createContext<(request: PreviewRequest) => void>(() => {
  throw new Error("usePreview must be used inside <PreviewProvider>");
});

/** Open a document preview. Every document is seen before it is downloaded, issued or sent. */
export function usePreview() {
  return useContext(PreviewContext);
}

/** Shorthand for a file the API serves: preview it, and download it from the preview. */
export function useViewFile() {
  const preview = usePreview();
  return useCallback((path: string, filename: string, title?: string) => preview({ title: title ?? filename, filename, load: () => apiBlob(path) }), [preview]);
}

export function PreviewProvider({ children }: { children: ReactNode }) {
  const [open, setOpen] = useState<{ id: number; request: PreviewRequest } | null>(null);
  const show = useCallback((request: PreviewRequest) => setOpen((o) => ({ id: (o?.id ?? 0) + 1, request })), []);
  return (
    <PreviewContext.Provider value={show}>
      {children}
      {open && <DocumentPreview key={open.id} request={open.request} onClose={() => setOpen(null)} />}
    </PreviewContext.Provider>
  );
}

type Kind = "pdf" | "image" | "csv" | "other";

function kindOf(blob: Blob, filename: string): Kind {
  const type = blob.type.split(";")[0] ?? "";
  if (type === "application/pdf" || /\.pdf$/i.test(filename)) return "pdf";
  if (type.startsWith("image/")) return "image";
  if (type === "text/csv" || /\.csv$/i.test(filename)) return "csv";
  return "other";
}

const ZOOMS = [1, 1.5, 2];

export function DocumentPreview({ request, onClose }: { request: PreviewRequest; onClose: () => void }) {
  const { title, filename, load, note, email, confirm } = request;
  const [blob, setBlob] = useState<Blob | null>(null);
  const [mail, setMail] = useState<PreviewEmail | null>(null);
  const [loadError, setLoadError] = useState<unknown>(null);
  const [zoom, setZoom] = useState(0);
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState<unknown>(null);
  const [saved, setSaved] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    Promise.all([load(), email?.() ?? Promise.resolve(null)])
      .then(([b, m]) => live && (setBlob(b), setMail(m)))
      .catch((e) => live && setLoadError(e));
    return () => {
      live = false;
    };
    // Loaded once per preview: the provider gives each preview its own instance.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const kind = blob ? kindOf(blob, filename) : null;
  const ready = !!blob && !loadError;

  async function download() {
    if (!blob) return;
    setActionError(null);
    try {
      setSaved(`Saved to ${await saveBlob(blob, filename)}.`);
    } catch (e) {
      setActionError(e);
    }
  }

  async function run() {
    if (!confirm) return;
    setBusy(true);
    setActionError(null);
    try {
      await confirm.run();
      onClose();
    } catch (e) {
      setActionError(e);
      setBusy(false);
    }
  }

  return (
    <Dialog title={title} onClose={busy ? () => undefined : onClose} className="dialog-preview" hideTitle>
      <div className="preview-head">
        <div style={{ minWidth: 0 }}>
          <h3 className="dialog-title">{title}</h3>
          <p className="row-sub preview-file">{filename}</p>
        </div>
        {kind === "pdf" && (
          <div className="preview-zoom" role="group" aria-label="Zoom">
            <button type="button" className="icon-btn" aria-label="Zoom out" disabled={zoom === 0} onClick={() => setZoom((z) => z - 1)}>
              <Minus size={16} aria-hidden="true" />
            </button>
            <span className="preview-zoom-level" aria-live="polite">
              {ZOOMS[zoom]! * 100}%
            </span>
            <button type="button" className="icon-btn" aria-label="Zoom in" disabled={zoom === ZOOMS.length - 1} onClick={() => setZoom((z) => z + 1)}>
              <Plus size={16} aria-hidden="true" />
            </button>
          </div>
        )}
      </div>

      {note && <p className="preview-note">{note}</p>}

      {mail && (
        <section className="preview-email" aria-label="Email that will be sent">
          <dl>
            <dt>To</dt>
            <dd>{mail.to}</dd>
            <dt>Subject</dt>
            <dd>{mail.subject}</dd>
          </dl>
          <pre>{mail.text}</pre>
        </section>
      )}

      <div className="preview-body" tabIndex={0} aria-label={`${title}: document preview`} data-autofocus>
        {!blob && !loadError && <Skeleton h={320} />}
        {loadError ? <FormError error={loadError} /> : null}
        {blob && kind === "pdf" && <PdfView blob={blob} zoom={ZOOMS[zoom]!} />}
        {blob && kind === "image" && <ImageView blob={blob} alt={title} />}
        {blob && kind === "csv" && <CsvView blob={blob} />}
        {blob && kind === "other" && <p className="empty">This kind of file can’t be shown here. Download it to open it.</p>}
      </div>

      <FormError error={actionError} />
      {saved && (
        <p className="form-ok" role="status">
          {saved}
        </p>
      )}
      <div className="form-actions preview-actions">
        <button type="button" className="btn btn-secondary" onClick={onClose} disabled={busy}>
          {confirm ? "Back" : "Close"}
        </button>
        {confirm ? (
          <button type="button" className="btn btn-primary" onClick={run} disabled={!ready || busy}>
            {busy ? "Working…" : confirm.label}
          </button>
        ) : (
          <button type="button" className="btn btn-primary" onClick={download} disabled={!ready}>
            Download
          </button>
        )}
      </div>
    </Dialog>
  );
}

function PdfView({ blob, zoom }: { blob: Blob; zoom: number }) {
  const host = useRef<HTMLDivElement>(null);
  const [pages, setPages] = useState<number | null>(null);
  const [error, setError] = useState<unknown>(null);

  useEffect(() => {
    let cancelled = false;
    let destroy: (() => void) | undefined;
    setError(null);
    Promise.all([blob.arrayBuffer(), import("../lib/pdfRender")])
      .then(([data, { renderPdf }]) => (host.current ? renderPdf(data, host.current, zoom, () => cancelled) : null))
      .then((doc) => {
        if (!doc) return;
        if (cancelled) doc.destroy();
        else (destroy = doc.destroy), setPages(doc.pages);
      })
      .catch((e) => !cancelled && setError(e instanceof Error ? "This document couldn’t be shown here. Download it to open it." : e));
    return () => {
      cancelled = true;
      destroy?.();
    };
  }, [blob, zoom]);

  return (
    <>
      {pages === null && !error && <Skeleton h={320} />}
      <FormError error={error} />
      <div ref={host} className="preview-pages" />
      {pages !== null && <p className="row-sub preview-count">{pages === 1 ? "1 page" : `${pages} pages`}</p>}
    </>
  );
}

function ImageView({ blob, alt }: { blob: Blob; alt: string }) {
  const [url, setUrl] = useState<string | null>(null);
  useEffect(() => {
    const u = URL.createObjectURL(blob);
    setUrl(u);
    return () => URL.revokeObjectURL(u);
  }, [blob]);
  return url ? <img className="preview-image" src={url} alt={alt} /> : null;
}

/** Splits CSV text into rows, keeping quoted commas and quotes ("") inside a cell. */
export function parseCsv(text: string): string[][] {
  const rows: string[][] = [];
  let row: string[] = [];
  let cell = "";
  let quoted = false;
  for (let i = 0; i < text.length; i++) {
    const ch = text[i];
    if (quoted) {
      if (ch === '"' && text[i + 1] === '"') (cell += '"'), i++;
      else if (ch === '"') quoted = false;
      else cell += ch;
    } else if (ch === '"') quoted = true;
    else if (ch === ",") row.push(cell), (cell = "");
    else if (ch === "\n" || ch === "\r") {
      if (ch === "\r" && text[i + 1] === "\n") i++;
      row.push(cell);
      rows.push(row);
      row = [];
      cell = "";
    } else cell += ch;
  }
  if (cell || row.length) row.push(cell), rows.push(row);
  return rows;
}

function CsvView({ blob }: { blob: Blob }) {
  const [rows, setRows] = useState<string[][] | null>(null);
  useEffect(() => {
    let live = true;
    blob.text().then((t) => live && setRows(parseCsv(t.replace(/^﻿/, ""))));
    return () => {
      live = false;
    };
  }, [blob]);
  if (!rows) return <Skeleton h={200} />;
  const [head = [], ...body] = rows;
  if (!body.length) return <p className="empty">This file has no rows.</p>;
  return (
    <div className="table-wrap preview-table">
      <table className="table">
        <thead>
          <tr>
            {head.map((h, i) => (
              <th key={i}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {body.map((r, i) => (
            <tr key={i}>
              {r.map((c, j) => (
                <td key={j}>{c}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      <p className="row-sub preview-count">{body.length === 1 ? "1 row" : `${body.length} rows`}</p>
    </div>
  );
}
