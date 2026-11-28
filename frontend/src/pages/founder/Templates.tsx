import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FileText, Upload } from "lucide-react";
import { useRef, useState, type FormEvent } from "react";
import { api, post } from "../../api/client";
import type { CompanyTemplate, TemplateCategory } from "../../api/types";
import { useViewFile } from "../../components/DocumentPreview";
import { Dialog, Done, ErrorNote, Field, FormError, PageHead, Skeleton, Tabs } from "../../components/ui";
import { fileSize, fullDay, shortDay } from "../../lib/format";
import "../overview.css";
import "../pages.css";

const TEMPLATE_CATEGORIES: { key: TemplateCategory; label: string }[] = [
  { key: "letterhead", label: "Letterhead" },
  { key: "offer", label: "Offer letters" },
  { key: "contract", label: "Contracts" },
  { key: "policy", label: "Policies" },
  { key: "finance", label: "Finance" },
  { key: "other", label: "Other" },
];

const categoryLabel = (c: TemplateCategory) => TEMPLATE_CATEGORIES.find((x) => x.key === c)?.label ?? c;
const MAX_BYTES = 10 * 1024 * 1024;

type Filter = "all" | TemplateCategory;

const templatePath = (t: Pick<CompanyTemplate, "id">, version?: number) => `/api/templates/${t.id}/pdf${version ? `?version=${version}` : ""}`;

function checkPdf(file: File | null): string | null {
  if (!file) return "Choose the PDF file.";
  if (file.type !== "application/pdf" || file.size > MAX_BYTES) return "The template must be a PDF under 10 MB.";
  return null;
}

function PdfPicker({ id, file, onChange, inputRef }: { id: string; file: File | null; onChange: (f: File | null) => void; inputRef: React.RefObject<HTMLInputElement | null> }) {
  return (
    <label className="file-tile" style={{ cursor: "pointer" }}>
      <FileText size={18} className="doc-icon" aria-hidden="true" />
      <span>
        <span className="row-title" style={{ display: "block" }}>
          {file ? file.name : "Choose a PDF"}
        </span>
        <span className="row-sub">{file ? `PDF · ${fileSize(file.size)}` : "PDF, up to 10 MB"}</span>
      </span>
      <input id={id} ref={inputRef} type="file" accept="application/pdf" className="sr-only" onChange={(e) => onChange(e.target.files?.[0] ?? null)} />
    </label>
  );
}

export function Templates() {
  const qc = useQueryClient();
  const [showArchived, setShowArchived] = useState(false);
  const list = useQuery({
    queryKey: ["templates", showArchived],
    queryFn: () => api<CompanyTemplate[]>(`/api/templates${showArchived ? "?include_archived=true" : ""}`),
  });
  const [filter, setFilter] = useState<Filter>("all");
  const [search, setSearch] = useState("");
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [dialog, setDialog] = useState<"add" | "version" | "edit" | null>(null);
  const [done, setDone] = useState<string | null>(null);
  const view = useViewFile();
  const refresh = () => qc.invalidateQueries({ queryKey: ["templates"] });

  const archive = useMutation({
    mutationFn: (t: CompanyTemplate) => post<CompanyTemplate>(`/api/templates/${t.id}/${t.archived ? "restore" : "archive"}`),
    onSuccess: (t) => (refresh(), setDone(t.archived ? `${t.name} archived. It stays available under “Show archived”.` : `${t.name} restored.`)),
  });

  if (list.isError) return <ErrorNote error={list.error} onRetry={() => list.refetch()} />;
  const rows = list.data ?? [];
  const q = search.trim().toLowerCase();
  const shown = rows.filter((t) => (filter === "all" || t.category === filter) && (!q || `${t.name} ${t.description ?? ""}`.toLowerCase().includes(q)));
  const selected = rows.find((t) => t.id === selectedId) ?? shown[0];

  return (
    <div className="page">
      <PageHead title="Company templates" sub="Official letterheads, offer letters, contracts and policies. Every upload is kept as a version.">
        <button className="btn btn-primary" onClick={() => (setDone(null), setDialog("add"))}>
          <Upload size={16} aria-hidden="true" /> Add template
        </button>
      </PageHead>
      <Done text={done} />
      <div className="toolbar">
        <input className="input" type="search" placeholder="Search templates" aria-label="Search templates" value={search} onChange={(e) => setSearch(e.target.value)} />
        <Tabs<Filter>
          label="Filter templates"
          value={filter}
          onChange={(f) => (setFilter(f), setSelectedId(null))}
          tabs={[
            { key: "all", label: "All", count: rows.length },
            ...TEMPLATE_CATEGORIES.filter((c) => rows.some((t) => t.category === c.key)).map((c) => ({
              key: c.key as Filter,
              label: c.label,
              count: rows.filter((t) => t.category === c.key).length,
            })),
          ]}
        />
        <label className="row-sub" style={{ display: "flex", gap: 6, alignItems: "center" }}>
          <input type="checkbox" checked={showArchived} onChange={(e) => setShowArchived(e.target.checked)} /> Show archived
        </label>
      </div>

      <div className="split">
        <section className="card">
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>Template</th>
                  <th className="hide-sm">Updated</th>
                  <th>Category</th>
                </tr>
              </thead>
              <tbody>
                {list.isPending && (
                  <tr>
                    <td colSpan={3}>
                      <Skeleton h={48} />
                    </td>
                  </tr>
                )}
                {!list.isPending && shown.length === 0 && (
                  <tr>
                    <td colSpan={3} className="empty">
                      {q ? "No templates match your search." : "No templates yet. Add your letterhead, offer letter and contracts."}
                    </td>
                  </tr>
                )}
                {shown.map((t) => (
                  <tr
                    key={t.id}
                    className="selectable"
                    aria-selected={t.id === selected?.id}
                    tabIndex={0}
                    onClick={() => setSelectedId(t.id)}
                    onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && (e.preventDefault(), setSelectedId(t.id))}
                  >
                    <td>
                      <div className="doc-cell">
                        <FileText size={18} className="doc-icon" aria-hidden="true" />
                        <div>
                          <p className="row-title">{t.name}</p>
                          <p className="row-sub num">Version {t.current.version}</p>
                        </div>
                      </div>
                    </td>
                    <td className="hide-sm">{shortDay(t.updated_at)}</td>
                    <td>
                      <span className={`chip ${t.archived ? "chip-neutral" : "chip-brand"}`}>{t.archived ? "Archived" : categoryLabel(t.category)}</span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>

        {selected && (
          <section className="card detail" aria-label="Template details">
            <span className="detail-icon" aria-hidden="true">
              <FileText size={20} />
            </span>
            <h3 className="detail-title" style={{ marginTop: 18 }}>
              {selected.name}
            </h3>
            <p className="detail-ref num">
              {categoryLabel(selected.category)} · Version {selected.current.version}
            </p>
            {selected.description && <p className="row-sub" style={{ marginTop: 8 }}>{selected.description}</p>}
            <hr className="divider" />
            <dl className="kv">
              <div>
                <dt>Last updated</dt>
                <dd>{fullDay(selected.updated_at)}</dd>
              </div>
              <div>
                <dt>Current file</dt>
                <dd>
                  {selected.current.filename} · {fileSize(selected.current.size)}
                </dd>
              </div>
            </dl>
            <div className="form-row" style={{ gap: 10, marginTop: 14, flexWrap: "wrap" }}>
              <button className="btn btn-primary" onClick={() => view(templatePath(selected), `${selected.name}.pdf`, selected.name)}>
                View
              </button>
              {!selected.archived && (
                <button className="btn btn-secondary" onClick={() => (setDone(null), setDialog("version"))}>
                  Upload new version
                </button>
              )}
              <button className="btn btn-secondary" onClick={() => (setDone(null), setDialog("edit"))}>
                Edit details
              </button>
              <button className="btn btn-secondary" disabled={archive.isPending} onClick={() => archive.mutate(selected)}>
                {selected.archived ? "Restore" : "Archive"}
              </button>
            </div>
            <FormError error={archive.error} />
            {selected.versions.length > 1 && (
              <>
                <hr className="divider" />
                <h4 className="row-title">Earlier versions</h4>
                <ul className="list" style={{ listStyle: "none", padding: 0, display: "grid", gap: 8, marginTop: 8 }}>
                  {selected.versions.slice(1).map((v) => (
                    <li key={v.version} style={{ display: "flex", justifyContent: "space-between", gap: 10, alignItems: "center" }}>
                      <span>
                        <span className="row-title" style={{ display: "block" }}>
                          Version {v.version} · {shortDay(v.created_at)}
                        </span>
                        <span className="row-sub">{v.note ?? v.filename}</span>
                      </span>
                      <button className="link-btn" onClick={() => view(templatePath(selected, v.version), `${selected.name} v${v.version}.pdf`, `${selected.name}, version ${v.version}`)}>
                        View
                      </button>
                    </li>
                  ))}
                </ul>
              </>
            )}
          </section>
        )}
      </div>

      {dialog === "add" && <AddTemplate onClose={() => setDialog(null)} onSaved={(t) => (refresh(), setSelectedId(t.id), setDialog(null), setDone(`${t.name} added.`))} />}
      {dialog === "version" && selected && (
        <NewVersion template={selected} onClose={() => setDialog(null)} onSaved={(t) => (refresh(), setDialog(null), setDone(`${t.name} is now on version ${t.current.version}.`))} />
      )}
      {dialog === "edit" && selected && <EditTemplate template={selected} onClose={() => setDialog(null)} onSaved={(t) => (refresh(), setDialog(null), setDone(`${t.name} saved.`))} />}
    </div>
  );
}

function AddTemplate({ onClose, onSaved }: { onClose: () => void; onSaved: (t: CompanyTemplate) => void }) {
  const [f, setF] = useState({ name: "", category: "letterhead" as TemplateCategory, description: "" });
  const [file, setFile] = useState<File | null>(null);
  const [error, setError] = useState<unknown>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const save = useMutation({
    mutationFn: () => {
      const form = new FormData();
      form.append("name", f.name.trim());
      form.append("category", f.category);
      if (f.description.trim()) form.append("description", f.description.trim());
      form.append("file", file as File);
      return api<CompanyTemplate>("/api/templates", { method: "POST", body: form });
    },
    onSuccess: onSaved,
    onError: setError,
  });

  function submit(e: FormEvent) {
    e.preventDefault();
    if (f.name.trim().length < 2) return setError("Give the template a name.");
    const bad = checkPdf(file);
    if (bad) return setError(bad);
    setError(null);
    save.mutate();
  }

  return (
    <Dialog title="Add template" onClose={onClose}>
      <form onSubmit={submit} noValidate style={{ display: "grid", gap: 14 }}>
        <Field id="t-name" label="Name">
          <input id="t-name" className="input" maxLength={120} placeholder="Offer letter" value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} autoFocus />
        </Field>
        <Field id="t-category" label="Category">
          <select id="t-category" className="input" value={f.category} onChange={(e) => setF({ ...f, category: e.target.value as TemplateCategory })}>
            {TEMPLATE_CATEGORIES.map((c) => (
              <option key={c.key} value={c.key}>
                {c.label}
              </option>
            ))}
          </select>
        </Field>
        <Field id="t-description" label="Description" hint="Optional. When to use it.">
          <textarea id="t-description" className="input textarea" maxLength={1000} value={f.description} onChange={(e) => setF({ ...f, description: e.target.value })} />
        </Field>
        <Field id="t-file" label="File">
          <PdfPicker id="t-file" file={file} onChange={setFile} inputRef={fileRef} />
        </Field>
        <FormError error={error} />
        <button className="btn btn-primary" disabled={save.isPending}>
          {save.isPending ? "Uploading…" : "Add template"}
        </button>
      </form>
    </Dialog>
  );
}

function NewVersion({ template, onClose, onSaved }: { template: CompanyTemplate; onClose: () => void; onSaved: (t: CompanyTemplate) => void }) {
  const [note, setNote] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [error, setError] = useState<unknown>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const save = useMutation({
    mutationFn: () => {
      const form = new FormData();
      if (note.trim()) form.append("note", note.trim());
      form.append("file", file as File);
      return api<CompanyTemplate>(`/api/templates/${template.id}/versions`, { method: "POST", body: form });
    },
    onSuccess: onSaved,
    onError: setError,
  });

  function submit(e: FormEvent) {
    e.preventDefault();
    const bad = checkPdf(file);
    if (bad) return setError(bad);
    setError(null);
    save.mutate();
  }

  return (
    <Dialog title={`New version of ${template.name}`} onClose={onClose}>
      <form onSubmit={submit} noValidate style={{ display: "grid", gap: 14 }}>
        <p className="row-sub">Version {template.current.version} is kept and can still be viewed.</p>
        <Field id="v-file" label="File">
          <PdfPicker id="v-file" file={file} onChange={setFile} inputRef={fileRef} />
        </Field>
        <Field id="v-note" label="What changed" hint="Optional, e.g. “Updated clause 4”.">
          <input id="v-note" className="input" maxLength={300} value={note} onChange={(e) => setNote(e.target.value)} />
        </Field>
        <FormError error={error} />
        <button className="btn btn-primary" disabled={save.isPending}>
          {save.isPending ? "Uploading…" : `Save as version ${template.current.version + 1}`}
        </button>
      </form>
    </Dialog>
  );
}

function EditTemplate({ template, onClose, onSaved }: { template: CompanyTemplate; onClose: () => void; onSaved: (t: CompanyTemplate) => void }) {
  const [f, setF] = useState({ name: template.name, category: template.category, description: template.description ?? "" });
  const [error, setError] = useState<unknown>(null);
  const save = useMutation({
    mutationFn: () =>
      api<CompanyTemplate>(`/api/templates/${template.id}`, {
        method: "PUT",
        body: JSON.stringify({ name: f.name.trim(), category: f.category, description: f.description.trim() || null }),
      }),
    onSuccess: onSaved,
    onError: setError,
  });

  function submit(e: FormEvent) {
    e.preventDefault();
    if (f.name.trim().length < 2) return setError("Give the template a name.");
    setError(null);
    save.mutate();
  }

  return (
    <Dialog title="Edit template" onClose={onClose}>
      <form onSubmit={submit} noValidate style={{ display: "grid", gap: 14 }}>
        <Field id="e-name" label="Name">
          <input id="e-name" className="input" maxLength={120} value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} autoFocus />
        </Field>
        <Field id="e-category" label="Category">
          <select id="e-category" className="input" value={f.category} onChange={(e) => setF({ ...f, category: e.target.value as TemplateCategory })}>
            {TEMPLATE_CATEGORIES.map((c) => (
              <option key={c.key} value={c.key}>
                {c.label}
              </option>
            ))}
          </select>
        </Field>
        <Field id="e-description" label="Description">
          <textarea id="e-description" className="input textarea" maxLength={1000} value={f.description} onChange={(e) => setF({ ...f, description: e.target.value })} />
        </Field>
        <FormError error={error} />
        <button className="btn btn-primary" disabled={save.isPending}>
          {save.isPending ? "Saving…" : "Save"}
        </button>
      </form>
    </Dialog>
  );
}
