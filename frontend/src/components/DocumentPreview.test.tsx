import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { PreviewProvider, parseCsv, usePreview, type PreviewRequest } from "./DocumentPreview";
import { Dialog } from "./ui";

vi.mock("../lib/pdfRender", () => ({
  renderPdf: async (_data: ArrayBuffer, host: HTMLElement) => {
    host.textContent = "Rendered PDF page";
    return { pages: 2, destroy: () => undefined };
  },
}));

function Opener({ request, withDialog = false }: { request: PreviewRequest; withDialog?: boolean }) {
  const preview = usePreview();
  const [open, setOpen] = useState(withDialog);
  return (
    <>
      <button onClick={() => preview(request)}>Open preview</button>
      {open && (
        <Dialog title="Form" onClose={() => setOpen(false)}>
          <button onClick={() => preview(request)}>Preview from form</button>
        </Dialog>
      )}
    </>
  );
}

const pdf = () => Promise.resolve(new Blob(["%PDF-1.4"], { type: "application/pdf" }));

afterEach(() => vi.unstubAllGlobals());

describe("Document preview", () => {
  it("shows the document first and downloads exactly what was shown", async () => {
    const user = userEvent.setup();
    const created: Blob[] = [];
    vi.stubGlobal("URL", Object.assign(Object.create(URL), { createObjectURL: (b: Blob) => (created.push(b), "blob:x"), revokeObjectURL: () => undefined }));
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined);
    const load = vi.fn(pdf);
    render(
      <PreviewProvider>
        <Opener request={{ title: "Invoice SP-INV-2026-004", filename: "SP-INV-2026-004.pdf", load }} />
      </PreviewProvider>,
    );
    await user.click(screen.getByRole("button", { name: "Open preview" }));
    const dialog = screen.getByRole("dialog", { name: "Invoice SP-INV-2026-004" });
    expect(await within(dialog).findByText("Rendered PDF page")).toBeInTheDocument();
    expect(within(dialog).getByText("2 pages")).toBeInTheDocument();
    expect(click).not.toHaveBeenCalled();

    await user.click(within(dialog).getByRole("button", { name: "Download" }));
    expect(click).toHaveBeenCalledOnce();
    expect(load).toHaveBeenCalledOnce(); // the same bytes, not a second fetch
    expect(created[0]?.type).toBe("application/pdf");
    expect(within(dialog).getByRole("status")).toHaveTextContent("Saved to your downloads.");
  });

  it("only takes the action once confirmed, and shows the email that will be sent", async () => {
    const user = userEvent.setup();
    const run = vi.fn(async () => undefined);
    const email = async () => ({ to: "thandi@example.com", subject: "Your offer", text: "Hi Thandi" });
    render(
      <PreviewProvider>
        <Opener request={{ title: "Offer for Thandi", filename: "proposal.pdf", load: pdf, email, note: "Check it.", confirm: { label: "Send offer", run } }} />
      </PreviewProvider>,
    );
    await user.click(screen.getByRole("button", { name: "Open preview" }));
    const dialog = screen.getByRole("dialog", { name: "Offer for Thandi" });
    const mail = await within(dialog).findByRole("region", { name: "Email that will be sent" });
    expect(mail).toHaveTextContent("thandi@example.com");
    expect(mail).toHaveTextContent("Hi Thandi");
    expect(within(dialog).queryByRole("button", { name: "Download" })).not.toBeInTheDocument();
    expect(run).not.toHaveBeenCalled();

    await user.click(within(dialog).getByRole("button", { name: "Send offer" }));
    expect(run).toHaveBeenCalledOnce();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("keeps the preview open with the reason when the action fails", async () => {
    const user = userEvent.setup();
    const run = vi.fn(async () => Promise.reject(new Error("The invoice was already issued")));
    render(
      <PreviewProvider>
        <Opener request={{ title: "Invoice draft", filename: "d.pdf", load: pdf, confirm: { label: "Issue invoice", run } }} />
      </PreviewProvider>,
    );
    await user.click(screen.getByRole("button", { name: "Open preview" }));
    const dialog = screen.getByRole("dialog", { name: "Invoice draft" });
    await within(dialog).findByText("Rendered PDF page");
    await user.click(within(dialog).getByRole("button", { name: "Issue invoice" }));
    expect(await within(dialog).findByRole("alert")).toHaveTextContent("already issued");
  });

  it("Escape closes only the preview when it opened from another dialog", async () => {
    const user = userEvent.setup();
    render(
      <PreviewProvider>
        <Opener withDialog request={{ title: "Receipt", filename: "r.pdf", load: pdf }} />
      </PreviewProvider>,
    );
    await user.click(screen.getByRole("button", { name: "Preview from form" }));
    expect(screen.getAllByRole("dialog")).toHaveLength(2);
    await user.keyboard("{Escape}");
    expect(screen.getAllByRole("dialog")).toHaveLength(1);
    expect(screen.getByRole("dialog", { name: "Form" })).toBeInTheDocument();
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(document.body.style.overflow).toBe("");
  });

  it("shows a payment list (CSV) as a table", async () => {
    const user = userEvent.setup();
    const csv = async () => new Blob(['Beneficiary,Amount (ZAR)\r\n"Mokoena, Thabo",1620.00\r\n'], { type: "text/csv" });
    render(
      <PreviewProvider>
        <Opener request={{ title: "Payment list", filename: "payment-list.csv", load: csv }} />
      </PreviewProvider>,
    );
    await user.click(screen.getByRole("button", { name: "Open preview" }));
    const table = await screen.findByRole("table");
    expect(within(table).getByRole("columnheader", { name: "Amount (ZAR)" })).toBeInTheDocument();
    expect(within(table).getByRole("cell", { name: "Mokoena, Thabo" })).toBeInTheDocument();
  });

  it("parses quoted CSV cells", () => {
    expect(parseCsv('a,"b ""c"", d"\n1,2')).toEqual([
      ["a", 'b "c", d'],
      ["1", "2"],
    ]);
  });
});
