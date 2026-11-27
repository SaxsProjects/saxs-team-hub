/**
 * Draws a PDF onto canvases with pdf.js, so a document can be previewed the same way in every browser,
 * on phones and inside the Android app (none of which reliably show PDFs inside a page on their own).
 * Loaded only when a preview opens.
 */
import { GlobalWorkerOptions, getDocument, type PDFDocumentProxy } from "pdfjs-dist";
import workerUrl from "pdfjs-dist/build/pdf.worker.min.mjs?url";

GlobalWorkerOptions.workerSrc = workerUrl;

export interface RenderedPdf {
  pages: number;
  destroy: () => void;
}

/** Render every page into `host` at `zoom` × its width, with each page's text kept for screen readers. */
export async function renderPdf(data: ArrayBuffer, host: HTMLElement, zoom: number, isCancelled: () => boolean): Promise<RenderedPdf> {
  const task = getDocument({
    data: new Uint8Array(data),
    standardFontDataUrl: `${import.meta.env.BASE_URL}assets/pdfjs/standard_fonts/`,
    useWasm: false, // the app's security policy doesn't allow WebAssembly; the JavaScript decoders are used instead
    enableXfa: false,
  });
  const pdf: PDFDocumentProxy = await task.promise;
  const ratio = Math.min(window.devicePixelRatio || 1, 2);
  // Leave room for the scrollbar that appears once the pages are taller than the box.
  const width = Math.max(host.clientWidth - 18, 260);
  host.replaceChildren();

  for (let n = 1; n <= pdf.numPages; n++) {
    if (isCancelled()) break;
    const page = await pdf.getPage(n);
    const base = page.getViewport({ scale: 1 });
    const cssWidth = width * zoom;
    const viewport = page.getViewport({ scale: (cssWidth / base.width) * ratio });

    const figure = document.createElement("figure");
    figure.className = "preview-page";
    // At 100% the page fits the box exactly (and follows it if the window is resized); zoomed, it keeps its size and scrolls.
    figure.style.width = zoom === 1 ? "100%" : `${cssWidth}px`;
    const canvas = document.createElement("canvas");
    canvas.width = Math.floor(viewport.width);
    canvas.height = Math.floor(viewport.height);
    canvas.style.width = "100%";
    canvas.style.height = "auto";
    canvas.setAttribute("aria-hidden", "true");
    figure.append(canvas);

    const text = document.createElement("figcaption");
    text.className = "sr-only";
    const content = await page.getTextContent();
    text.textContent = `Page ${n} of ${pdf.numPages}. ${content.items.map((i) => ("str" in i ? i.str : "")).join(" ")}`;
    figure.append(text);
    host.append(figure);

    await page.render({ canvas, viewport }).promise;
    page.cleanup();
  }
  return { pages: pdf.numPages, destroy: () => void task.destroy() };
}
