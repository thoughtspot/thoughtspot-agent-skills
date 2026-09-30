/**
 * Available Columns:
 * "Pay Invoice Line Descr"
 * "Company Address 1"
 * "Company City"
 * "Company State"
 * "Company Postal"
 * "Trinet Address 1"
 * "Trinet Address 2"
 * "Trinet Address 3"
 * "Trinet Address 4"
 * "Day(Invoice Date)"
 * "Day(Pay End Date)"
 * "Invoice Number"
 * "Company Address 234"
 * "Net Amount (USD)"
 * "Measure names" // If 'measureValues' is enabled.
 * "Measure values" // If 'measureValues' is enabled.
 * --- END --- 
 */

/**************************************************************
 * BULLETPROOF MUZE SENTINEL + INVOICE HTML RENDERER
 *
 * Why sentinel: Muze Studio expects a Muze viz mount as the
 * “rendered” signal; pure HTML often gets discarded. [1](https://trinet-prod.atlassian.net/browse/WFA-10695)[2](https://trinethr-my.sharepoint.com/personal/vamsi_palaverichakravarthy_trinet_com/Documents/Desktop/THOUGHTSPOT%20NOTES/Thoughtspot%20Certification%20Training/1_Professional%20Certification/26.3%20End%20User%20Essentials%20Mar%202026.pdf?web=1)
 *
 * What you get:
 *  - A tiny hidden Muze chart mounted to #muze-sentinel
 *  - Your invoice form rendered to #invoice-root
 *  - Debug always shown in the output (so you can progress)
 **************************************************************/

const ONLY_FIRST_INVOICE = false;   // start with 1 invoice; set false later
const SHOW_SENTINEL_ONSCREEN = false; // set true temporarily if you want to SEE the sentinel

/* ------------------------------------------------------------
   PAGE BREAK OPTIONS (config — drives Viewer AND Export)
   Each invoice renders as its own "sheet": the Viewer shows
   WYSIWYG paper sheets, and Export/print puts one invoice per
   physical page. Change these constants to control paper size.
------------------------------------------------------------ */
const PAGE_SIZE        = "letter";     // "letter" | "a4"
const PAGE_ORIENTATION = "portrait";   // "portrait" | "landscape"
const PAGE_MARGIN_IN   = 0.5;          // printable margin, in inches
const PAGE_BREAK_MODE  = "per-invoice"; // one invoice per page

// ThoughtSpot's native Download (PNG / Liveboard PDF) rasterizes this chart as
// ONE tile, so it can't paginate the report (PNG = first page only, Liveboard =
// clipped). This button runs the browser print pipeline instead, which honors
// the @page / @media print rules and yields a true one-invoice-per-page PDF.
const SHOW_DOWNLOAD_BUTTON = true;     // in-chart "Download PDF" button

const { muze, getDataFromSearchQuery } = viz;
const root = document.getElementById("invoice-root");

/* Translate the PAGE_* constants into CSS vars (--page-w/h/margin)
   for the on-screen sheets and an @page rule for export/print.
   1in = 96px at standard screen DPI, so Viewer == printed size. */
(function applyPageSetup() {
  const SIZES_IN = { letter: [8.5, 11], a4: [8.27, 11.69] };
  let [wIn, hIn] = SIZES_IN[PAGE_SIZE] || SIZES_IN.letter;
  if (PAGE_ORIENTATION === "landscape") [wIn, hIn] = [hIn, wIn];
  const DPI = 96;
  const tag = document.createElement("style");
  tag.id = "invoice-page-setup";
  tag.textContent = `
    :root{
      --page-w: ${Math.round(wIn * DPI)}px;
      --page-h: ${Math.round(hIn * DPI)}px;
      --page-margin: ${Math.round(PAGE_MARGIN_IN * DPI)}px;
    }
    @page{ size: ${wIn}in ${hIn}in; margin: 0; }
  `;
  document.head.appendChild(tag);
})();


/* ------------------------------------------------------------
   DATA SOURCE
   This chart ships with BAKED-IN SAMPLE DATA so it renders in
   ThoughtSpot with NO search / data source attached — just paste
   the code and run. To bind it to a real TS search instead, flip
   USE_SAMPLE_DATA to false; the columns listed at the top of this
   file must then exist in your search.
------------------------------------------------------------ */
const USE_SAMPLE_DATA = true;

const { DataModel } = muze;

// Field types for the (tiny) Muze sentinel DataModel. Only
// "Net Amount (USD)" / "Pay Invoice Line Descr" actually drive the
// sentinel; the rest are carried through for the invoice layout.
const SAMPLE_SCHEMA = [
  { name: "Invoice Number", type: "dimension" },
  { name: "Pay Invoice Line Descr", type: "dimension" },
  { name: "Net Amount (USD)", type: "measure", defAggFn: "sum" },
  { name: "Company Address 1", type: "dimension" },
  { name: "Company Address 234", type: "dimension" },
  { name: "Company City", type: "dimension" },
  { name: "Company State", type: "dimension" },
  { name: "Company Postal", type: "dimension" },
  { name: "Trinet Address 1", type: "dimension" },
  { name: "Trinet Address 2", type: "dimension" },
  { name: "Trinet Address 3", type: "dimension" },
  { name: "Trinet Address 4", type: "dimension" },
  { name: "Day(Invoice Date)", type: "dimension" },
  { name: "Day(Pay End Date)", type: "dimension" },
];

// Fields shared by every line item on a given invoice. One row per
// LINE ITEM; rows are grouped into invoices by "Invoice Number".
// Dates are epoch-ms (what TS sends); the helper also accepts strings.
const TRINET = {
  "Trinet Address 1": "TriNet Group, Inc.",
  "Trinet Address 2": "One Park Place, Suite 600",
  "Trinet Address 3": "Dublin, CA 94568",
  "Trinet Address 4": "EIN 95-3359118",
};
const INV1 = {
  "Invoice Number": "INV-2026-0451",
  "Day(Invoice Date)": 1781524800000, // 2026-06-15
  "Day(Pay End Date)": 1782820800000, // 2026-06-30
  "Company Address 1": "Brightline Logistics, Inc.",
  "Company Address 234": "Attn: Accounts Payable — 1420 Market St, Ste 300",
  "Company City": "San Francisco",
  "Company State": "CA",
  "Company Postal": "94103",
  ...TRINET,
};
const INV2 = {
  "Invoice Number": "INV-2026-0452",
  "Day(Invoice Date)": 1781524800000, // 2026-06-15
  "Day(Pay End Date)": 1782820800000, // 2026-06-30
  "Company Address 1": "Northgate Retail Group, LLC",
  "Company Address 234": "Finance Department — 88 Lakeshore Blvd",
  "Company City": "Chicago",
  "Company State": "IL",
  "Company Postal": "60601",
  ...TRINET,
};
const SAMPLE_DATA = [
  { ...INV1, "Pay Invoice Line Descr": "Payroll Processing — Salaried Employees", "Net Amount (USD)": 12450.00 },
  { ...INV1, "Pay Invoice Line Descr": "Payroll Processing — Hourly Employees",   "Net Amount (USD)": 8230.50 },
  { ...INV1, "Pay Invoice Line Descr": "Employer Payroll Taxes (FICA/FUTA/SUTA)", "Net Amount (USD)": 5640.75 },
  { ...INV1, "Pay Invoice Line Descr": "Health & Welfare Benefits Administration","Net Amount (USD)": 3120.00 },
  { ...INV1, "Pay Invoice Line Descr": "Workers' Compensation Premium",           "Net Amount (USD)": 1875.40 },
  { ...INV1, "Pay Invoice Line Descr": "TriNet Platform Service Fee",             "Net Amount (USD)": 999.00 },
  { ...INV2, "Pay Invoice Line Descr": "Payroll Processing — Salaried Employees", "Net Amount (USD)": 9875.00 },
  { ...INV2, "Pay Invoice Line Descr": "Payroll Processing — Hourly Employees",   "Net Amount (USD)": 14320.25 },
  { ...INV2, "Pay Invoice Line Descr": "Employer Payroll Taxes (FICA/FUTA/SUTA)", "Net Amount (USD)": 6210.10 },
  { ...INV2, "Pay Invoice Line Descr": "401(k) Plan Administration",              "Net Amount (USD)": 2450.00 },
  { ...INV2, "Pay Invoice Line Descr": "TriNet Platform Service Fee",             "Net Amount (USD)": 1299.00 },
];

// Build `rows` (array of objects keyed by column name) for the invoice
// layout, plus `liveDM` (the raw TS DataModel) when bound to a search.
// Sample + live modes both end up with the same object-row shape so the
// rest of the code is identical.
let data = null, rows = [], liveDM = null;
try {
  if (USE_SAMPLE_DATA) {
    rows = SAMPLE_DATA;
  } else {
    liveDM = getDataFromSearchQuery();
    const liveSchema = liveDM.getSchema();
    rows = liveDM.getData().data.map(arr => {
      const o = {};
      liveSchema.forEach((c, i) => { o[c.name] = arr[i]; });
      return o;
    });
  }
} catch (e) {
  root.innerHTML = `<div class="debug"><span class="bad">FAILED</span> — loading data<pre>${String(e)}</pre></div>`;
  console.error(e);
  return;
}

console.log("Row count:", rows.length);
console.log("First row:", rows[0]);

if (!rows || rows.length === 0) {
  root.innerHTML = `<div class="debug"><span class="bad">No rows returned</span></div>`;
  return;
}

// Helper: get value by column name (rows are plain objects now)
function getVal(row, colName) {
  const v = row[colName];
  return v == null ? "" : v;
}

// Convert epoch -> date string. Accepts epoch-ms (TS) or a plain string.
function epochToDateString(v) {
  const n = Number(v);
  if (!n) return String(v || "");
  return new Date(n).toLocaleDateString();
}

// Format a number as USD; non-numeric values pass through unchanged.
function fmtUSD(v) {
  const n = Number(v);
  if (!isFinite(n) || v === "" || v == null) return String(v == null ? "" : v);
  return n.toLocaleString("en-US", { style: "currency", currency: "USD" });
}

/* ------------------------------------------------------------
   1) MUZE SENTINEL MOUNT (this is the critical “render token”)
   Non-fatal: if the mount fails we still render the invoices below,
   so the layout stays visible (e.g. in a plain-browser preview).
------------------------------------------------------------ */
try {
  // Optionally show sentinel onscreen (for debugging only)
  if (SHOW_SENTINEL_ONSCREEN) {
    const s = document.getElementById("muze-sentinel");
    s.style.position = "relative";
    s.style.left = "0";
    s.style.top = "0";
    s.style.width = "220px";
    s.style.height = "120px";
    s.style.opacity = "1";
    s.style.pointerEvents = "auto";
  }

  // Sample mode builds a DataModel from the baked-in rows; live mode
  // reuses the DataModel TS already handed us.
  data = USE_SAMPLE_DATA
    ? new DataModel(DataModel.loadDataSync(SAMPLE_DATA, SAMPLE_SCHEMA))
    : liveDM;

  muze.canvas()
    .rows(["Net Amount (USD)"])             // measure exists in your schema
    .columns(["Pay Invoice Line Descr"])    // dimension exists in your schema
    .data(data)
    .mount("#muze-sentinel");

  console.log("✅ Muze sentinel mounted");
} catch (e) {
  console.warn("⚠️ Muze sentinel mount failed (continuing to render invoices)", e);
}

/* ------------------------------------------------------------
   2) GROUP ROWS BY INVOICE NUMBER (you have Invoice Number)
------------------------------------------------------------ */
const invoices = {};
rows.forEach(r => {
  const invNo = String(getVal(r, "Invoice Number") || "");
  if (!invoices[invNo]) {
    invoices[invNo] = {
      invoiceNumber: invNo,
      invoiceDate: epochToDateString(getVal(r, "Day(Invoice Date)")),
      payEndDate: epochToDateString(getVal(r, "Day(Pay End Date)")),
      companyAddr1: getVal(r, "Company Address 1"),
      companyAddr234: getVal(r, "Company Address 234"),
      companyCity: getVal(r, "Company City"),
      companyState: getVal(r, "Company State"),
      companyPostal: getVal(r, "Company Postal"),
      t1: getVal(r, "Trinet Address 1"),
      t2: getVal(r, "Trinet Address 2"),
      t3: getVal(r, "Trinet Address 3"),
      t4: getVal(r, "Trinet Address 4"),
      items: []
    };
  }
  invoices[invNo].items.push({
    descr: getVal(r, "Pay Invoice Line Descr"),
    amt: getVal(r, "Net Amount (USD)")
  });
});

const invoiceKeys = Object.keys(invoices);


/* ------------------------------------------------------------
   3) RENDER INVOICE HTML
------------------------------------------------------------ */
function renderInvoice(inv) {
  let lines = "";
  let total = 0;
  inv.items.forEach(it => {
    total += Number(it.amt) || 0;
    lines += `
      <div class="table-row">
        <div class="col-desc">${it.descr}</div>
        <div class="col-amt">${fmtUSD(it.amt)}</div>
      </div>
    `;
  });
  lines += `
      <div class="table-row" style="border-bottom:none;border-top:2px solid #777;font-weight:bold;">
        <div class="col-desc">Total</div>
        <div class="col-amt">${fmtUSD(total)}</div>
      </div>
    `;

  return `
    <div class="invoice-page">
      <div class="header">
        <div class="header-left">
          <b>Invoice to</b><br/>
          ${inv.companyAddr1}<br/>
          ${inv.companyAddr234}<br/>
          ${inv.companyCity} ${inv.companyState} ${inv.companyPostal}
        </div>

        <div class="header-right">
          <div><b>Invoice Number</b> ${inv.invoiceNumber}</div>
          <div><b>Invoice Date</b> ${inv.invoiceDate}</div>
          <div><b>Pay End Date</b> ${inv.payEndDate}</div>
        </div>
      </div>

      <div class="table-header">
        <div class="col-desc">Description</div>
        <div class="col-amt">Net Amount (USD)</div>
      </div>

      ${lines}

      <div class="footer">
        <div>
          ${inv.t1}<br/>
          ${inv.t2}<br/>
          ${inv.t3}<br/>
          ${inv.t4}
        </div>
        <div class="footer-right">
          * For billing questions, call your TriNet representative
        </div>
      </div>
    </div>
  `;
}

let html = "";
if (ONLY_FIRST_INVOICE) {
  html = renderInvoice(invoices[invoiceKeys[0]]);
} else {
  invoiceKeys.forEach(k => { html += renderInvoice(invoices[k]); });
}

root.innerHTML += html;
console.log("✅ Invoice HTML rendered");

/* ------------------------------------------------------------
   4) DOWNLOAD AS MULTI-PAGE PDF (one invoice per page)

   ThoughtSpot's BYOC iframe blocks window.print() (no modal
   permission), so we build the PDF in plain JS and download it
   as a Blob — file downloads DO work in the iframe (that's how
   the native PNG export downloads). No print dialog, no popup,
   no external library/CDN (which the sandbox may also block).
------------------------------------------------------------ */
function buildInvoicePdf(list) {
  const PT = 72; // points per inch
  const SIZES_PT = { letter: [612, 792], a4: [595.28, 841.89] };
  let [pw, ph] = SIZES_PT[PAGE_SIZE] || SIZES_PT.letter;
  if (PAGE_ORIENTATION === "landscape") [pw, ph] = [ph, pw];
  const M = PAGE_MARGIN_IN * PT;
  const RX = pw - M; // right edge of the printable area

  // Text widths via canvas. Helvetica metrics ≈ PDF base Helvetica, and the
  // metric ratio is size-unit agnostic, so px width == pt width at equal size.
  const mctx = document.createElement("canvas").getContext("2d");
  const fontCss = (size, w) =>
    `${w === "b" ? "bold " : w === "i" ? "italic " : ""}${size}px Helvetica, Arial, sans-serif`;
  const widthOf = (s, size, w) => { mctx.font = fontCss(size, w); return mctx.measureText(String(s)).width; };

  // Encode JS string -> WinAnsi bytes with PDF string escaping (ASCII output).
  const WINANSI = { 0x2014: 0x97, 0x2013: 0x96, 0x2018: 0x91, 0x2019: 0x92,
                    0x201C: 0x93, 0x201D: 0x94, 0x2022: 0x95, 0x2026: 0x85 };
  const enc = (s) => {
    let out = "";
    for (const ch of String(s)) {
      let c = ch.codePointAt(0);
      if (WINANSI[c] != null) c = WINANSI[c];
      if (c > 0xff) c = 0x3f;                                  // '?' for unencodable
      if (c === 0x28 || c === 0x29 || c === 0x5c) out += "\\" + String.fromCharCode(c); // ( ) \
      else if (c < 0x20) out += " ";
      else if (c > 0x7e) out += "\\" + c.toString(8).padStart(3, "0"); // octal for >126
      else out += String.fromCharCode(c);
    }
    return out;
  };
  const fit = (s, maxW, size, w) => {
    s = String(s);
    if (widthOf(s, size, w) <= maxW) return s;
    while (s.length > 1 && widthOf(s + "…", size, w) > maxW) s = s.slice(0, -1);
    return s + "…";
  };

  const streams = list.map((inv) => {
    const ops = [];
    // y is measured from the TOP; PDF y-up conversion is (ph - y).
    const text = (x, y, s, size, w, col) => {
      const f = w === "b" ? "F2" : w === "i" ? "F3" : "F1";
      const c = col || [0.07, 0.07, 0.07];
      ops.push(`${c[0]} ${c[1]} ${c[2]} rg BT /${f} ${size} Tf 1 0 0 1 ${x.toFixed(2)} ${(ph - y).toFixed(2)} Tm (${enc(s)}) Tj ET`);
    };
    const rtext = (xr, y, s, size, w, col) => text(xr - widthOf(s, size, w), y, s, size, w, col);
    const hline = (x1, x2, y, g, lw) =>
      ops.push(`${g} ${g} ${g} RG ${lw.toFixed(2)} w ${x1.toFixed(2)} ${(ph - y).toFixed(2)} m ${x2.toFixed(2)} ${(ph - y).toFixed(2)} l S`);

    // ---- header (left address block + right meta block) ----
    let y = M + 6;
    text(M, y, "Invoice to", 9, "b");
    text(M, y + 13, inv.companyAddr1, 9, "n");
    text(M, y + 26, inv.companyAddr234, 9, "n");
    text(M, y + 39, `${inv.companyCity} ${inv.companyState} ${inv.companyPostal}`, 9, "n");

    const meta = (label, val, yy) => {
      const lw = widthOf(label + " ", 9, "b"), vw = widthOf(val, 9, "n");
      const x = RX - lw - vw;
      text(x, yy, label, 9, "b");
      text(x + lw, yy, val, 9, "n");
    };
    meta("Invoice Number", String(inv.invoiceNumber), y);
    meta("Invoice Date", String(inv.invoiceDate), y + 13);
    meta("Pay End Date", String(inv.payEndDate), y + 26);

    // ---- line-item table ----
    let ty = y + 64;
    text(M, ty, "Description", 11, "b");
    rtext(RX, ty, "Net Amount (USD)", 11, "b");
    hline(M, RX, ty + 6, 0.47, 1);
    const descMaxW = (RX - 120) - M;
    let total = 0;
    inv.items.forEach((it) => {
      total += Number(it.amt) || 0;
      ty += 20;
      text(M, ty - 4, fit(it.descr, descMaxW, 11, "n"), 11, "n");
      rtext(RX, ty - 4, fmtUSD(it.amt), 11, "n");
      hline(M, RX, ty + 6, 0.87, 0.7);
    });
    // ---- total row ----
    ty += 24;
    hline(M, RX, ty - 14, 0.47, 1);
    text(M, ty - 4, "Total", 11, "b");
    rtext(RX, ty - 4, fmtUSD(total), 11, "b");

    // ---- footer pinned near the bottom ----
    const fy = ph - M - 52;
    text(M, fy, inv.t1, 9, "n");
    text(M, fy + 13, inv.t2, 9, "n");
    text(M, fy + 26, inv.t3, 9, "n");
    text(M, fy + 39, inv.t4, 9, "n");
    rtext(RX, fy, "* For billing questions, call your TriNet representative", 9, "i", [0.2, 0.2, 0.2]);

    return ops.join("\n");
  });

  // ---- assemble objects: 1 catalog, 2 pages, 3-5 fonts, then content+page pairs ----
  const n = streams.length;
  const cStart = 6, pStart = cStart + n, last = pStart + n - 1;
  const objs = [];
  objs[1] = `<< /Type /Catalog /Pages 2 0 R >>`;
  objs[2] = `<< /Type /Pages /Kids [${Array.from({ length: n }, (_, i) => `${pStart + i} 0 R`).join(" ")}] /Count ${n} >>`;
  objs[3] = `<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>`;
  objs[4] = `<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>`;
  objs[5] = `<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Oblique /Encoding /WinAnsiEncoding >>`;
  for (let i = 0; i < n; i++) {
    objs[cStart + i] = `<< /Length ${streams[i].length} >>\nstream\n${streams[i]}\nendstream`;
    objs[pStart + i] = `<< /Type /Page /Parent 2 0 R /MediaBox [0 0 ${pw} ${ph}] ` +
      `/Resources << /Font << /F1 3 0 R /F2 4 0 R /F3 5 0 R >> >> /Contents ${cStart + i} 0 R >>`;
  }

  // ---- serialize with xref (everything is ASCII, so byte offset == string length) ----
  let pdf = "%PDF-1.4\n";
  const off = [];
  for (let i = 1; i <= last; i++) { off[i] = pdf.length; pdf += `${i} 0 obj\n${objs[i]}\nendobj\n`; }
  const xref = pdf.length;
  pdf += `xref\n0 ${last + 1}\n0000000000 65535 f \n`;
  for (let i = 1; i <= last; i++) pdf += `${String(off[i]).padStart(10, "0")} 00000 n \n`;
  pdf += `trailer\n<< /Size ${last + 1} /Root 1 0 R >>\nstartxref\n${xref}\n%%EOF`;
  return pdf;
}

function downloadInvoicesPdf() {
  const list = invoiceKeys.map((k) => invoices[k]);
  const pdf = buildInvoicePdf(list);
  const bytes = new Uint8Array(pdf.length);
  for (let i = 0; i < pdf.length; i++) bytes[i] = pdf.charCodeAt(i) & 0xff;
  const url = URL.createObjectURL(new Blob([bytes], { type: "application/pdf" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = "invoices.pdf";
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 4000);
}

function addDownloadButton() {
  if (!SHOW_DOWNLOAD_BUTTON) return;
  if (document.getElementById("invoice-download-btn")) return; // no duplicates on re-render
  const btn = document.createElement("button");
  btn.id = "invoice-download-btn";
  btn.className = "invoice-download-btn";
  btn.type = "button";
  btn.textContent = "⤓ Download PDF";
  btn.title = "Download all invoices as a multi-page PDF (one invoice per page)";
  btn.addEventListener("click", () => {
    try {
      downloadInvoicesPdf();
    } catch (e) {
      console.error("❌ PDF export failed", e);
      btn.textContent = "⚠ Export failed — see console";
      try { window.print(); } catch (_) {} // last-ditch, if the host allows it
    }
  });
  document.body.appendChild(btn);
}
addDownloadButton();