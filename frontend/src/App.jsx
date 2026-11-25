import { useEffect, useRef, useState } from "react";
import "./App.css";

const LABELS = {
  contract_value: "Contract value",
  pec_category: "PEC category",
  bid_security: "Bid security",
  liquidated_damages: "Liquidated damages",
  advance_payment: "Advance payment",
  active_taxpayer_status: "Active taxpayer status",
  active_taxpayer: "Active taxpayer status",
  experience: "Experience",
  completion_period: "Completion period",
};

const FIELD_ROWS = [
  ["contract_value_pkr", "Contract value", "pkr"],
  ["bid_security_amount_pkr", "Bid security (amount)", "pkr"],
  ["bid_security_percent", "Bid security (% of value)", "pct"],
  ["pec_category_required", "PEC category required", ""],
  ["completion_period_days", "Completion period (days)", ""],
  ["liquidated_damages_rate_percent_per_day", "Liquidated damages (% per day)", ""],
  ["advance_payment_percent", "Advance payment (%)", "pct"],
  ["min_years_experience_required", "Experience required (years)", ""],
  ["annual_turnover_figure", "Annual turnover figure (as written in the notice)", ""],
  ["bid_closing_date", "Bid closing date", ""],
];

const pkr = (n) => "PKR " + Number(n).toLocaleString("en-PK", { maximumFractionDigits: 0 });

function fieldValue(value, kind) {
  if (value === null || value === undefined || value === "") return null;
  if (kind === "pkr") return pkr(value);
  if (kind === "pct") return value + "%";
  return String(value);
}

// The matcher sends the contract-value limit as "min-max" with "None" for unset.
function limitText(criterion, text) {
  if (criterion !== "contract_value" || !text) return text;
  const [lo, hi] = text.split("-");
  const has = (x) => x && x !== "None";
  if (has(lo) && has(hi)) return `${pkr(lo)} to ${pkr(hi)}`;
  if (has(hi)) return `up to ${pkr(hi)}`;
  if (has(lo)) return `from ${pkr(lo)}`;
  return "no limit set";
}

const PEC_OPTIONS = ["C-A", "C-1", "C-2", "C-3", "C-4", "C-5", "C-6"];

// [field, label, kind] - the limits the matcher compares against a tender.
// Leaving one empty means "no limit": that check is skipped, never guessed.
const LIMIT_FIELDS = [
  ["min_contract_value_pkr", "Smallest contract you will bid on (PKR)", "money"],
  ["max_contract_value_pkr", "Largest contract you can handle (PKR)", "money"],
  ["max_bid_security_pkr", "Most bid security you can afford (PKR)", "money"],
  ["max_acceptable_ld_rate_percent_per_day", "Highest liquidated damages you accept (% per day)", ""],
  ["min_required_advance_payment_percent", "Lowest advance payment you accept (%)", ""],
  ["max_acceptable_completion_period_days", "Shortest completion period you can manage (days)", ""],
];

const COMPANY_FIELDS = [
  ["company_address", "Office address"],
  ["contact_person", "Contact person"],
  ["contact_designation", "Designation"],
  ["phone", "Phone"],
  ["email", "Email"],
  ["ntn_number", "NTN"],
];

const EMPTY_DRAFT = {
  contractor_name: "",
  pec_category_held: "C-6",
  years_experience: "0",
  is_active_taxpayer: true,
  ...Object.fromEntries(LIMIT_FIELDS.map(([k]) => [k, ""])),
  ...Object.fromEntries(COMPANY_FIELDS.map(([k]) => [k, ""])),
};

function toDraft(profile) {
  const d = { ...EMPTY_DRAFT };
  for (const key of Object.keys(d)) {
    const v = profile?.[key];
    if (key === "is_active_taxpayer") d[key] = v !== false;
    else d[key] = v === null || v === undefined ? EMPTY_DRAFT[key] : String(v);
  }
  return d;
}

function toPayload(d) {
  const out = {
    contractor_name: d.contractor_name.trim(),
    pec_category_held: d.pec_category_held,
    years_experience: d.years_experience.trim() === "" ? 0 : Number(d.years_experience),
    is_active_taxpayer: d.is_active_taxpayer,
  };
  for (const [k] of LIMIT_FIELDS) out[k] = d[k].trim() === "" ? null : Number(d[k]);
  for (const [k] of COMPANY_FIELDS) out[k] = d[k].trim() === "" ? null : d[k].trim();
  return out;
}

async function errorText(res) {
  try {
    const body = await res.json();
    if (typeof body.detail === "string") return body.detail;
    if (Array.isArray(body.detail)) return body.detail.map((d) => d.msg).join("; ");
  } catch {
    /* not JSON */
  }
  return `Request failed (${res.status}).`;
}

const PEC_ORDER = ["C-6", "C-5", "C-4", "C-3", "C-2", "C-1", "C-A"];
const SYMBOL = { pass: "\u2713", fail: "\u2715", skip: "\u2013" };

const rangeText = (lo, hi) => {
  const a = lo !== "" && !Number.isNaN(Number(lo));
  const b = hi !== "" && !Number.isNaN(Number(hi));
  if (a && b) return `${pkr(lo)} to ${pkr(hi)}`;
  if (b) return `Up to ${pkr(hi)}`;
  if (a) return `From ${pkr(lo)}`;
  return "No limit set";
};

function summaryText(r) {
  const lines = [
    `TenderGuard AI: ${r.decision} for ${r.contractor_name}`,
    `Tender: ${r.tender_title}`,
    r.confidence_note,
    "",
    ...r.results.map((c) => `${c.passed ? "PASS" : "FAIL"}  ${LABELS[c.criterion] || c.criterion}: ${c.reason}`),
  ];
  if (r.deadline_warning) lines.push("", "Deadline: " + r.deadline_warning);
  return lines.join("\n");
}

function FileDrop({ file, onFile, disabled }) {
  const [over, setOver] = useState(false);
  const ref = useRef(null);
  const pick = (f) => f && onFile(f);
  return (
    <div
      className={"drop" + (over ? " over" : "") + (file ? " has" : "")}
      onDragOver={(e) => { e.preventDefault(); setOver(true); }}
      onDragLeave={() => setOver(false)}
      onDrop={(e) => { e.preventDefault(); setOver(false); pick(e.dataTransfer.files?.[0]); }}
    >
      <input ref={ref} type="file" hidden accept=".pdf,.txt,application/pdf"
        onChange={(e) => pick(e.target.files?.[0])} />
      {file ? (
        <div className="drop-file">
          <span className="doc" aria-hidden="true">PDF</span>
          <div>
            <strong>{file.name}</strong>
            <span>{(file.size / 1048576).toFixed(1)} MB</span>
          </div>
          <button type="button" className="linkbtn" disabled={disabled}
            onClick={() => { onFile(null); if (ref.current) ref.current.value = ""; }}>
            Remove
          </button>
        </div>
      ) : (
        <>
          <p className="drop-title">Drop the tender document here</p>
          <button type="button" className="secondary" onClick={() => ref.current?.click()}>
            Choose a file
          </button>
          <p className="hint">PDF up to 25 MB. Scanned PDFs use OCR and can take a few minutes.</p>
        </>
      )}
    </div>
  );
}

function CoverageStrip({ result }) {
  const segs = [
    ...result.results.map((r) => ({ key: r.criterion, state: r.passed ? "pass" : "fail" })),
    ...result.skipped_criteria.map((n) => ({ key: n, state: "skip" })),
  ];
  const passed = result.results.filter((r) => r.passed).length;
  const failed = result.results.length - passed;
  const word = { pass: "passed", fail: "failed", skip: "not checked" };
  return (
    <div className="coverage">
      <div className="strip" role="img"
        aria-label={`${result.criteria_checked} of ${result.criteria_total} checks run: ${passed} passed, ${failed} failed, ${result.skipped_criteria.length} not checked`}>
        {segs.map((sg, i) => (
          <span key={sg.key} className={"seg " + sg.state} style={{ "--i": i }}
            title={`${LABELS[sg.key] || sg.key}: ${word[sg.state]}`}>
            <b aria-hidden="true">{SYMBOL[sg.state]}</b>
            <i>{LABELS[sg.key] || sg.key}</i>
          </span>
        ))}
      </div>
      <p className="legend">
        <span><b className="dot pass" />Passed {passed}</span>
        <span><b className="dot fail" />Failed {failed}</span>
        <span><b className="dot skip" />Not checked {result.skipped_criteria.length}</span>
      </p>
    </div>
  );
}

function CheckCard({ r }) {
  const [open, setOpen] = useState(!r.passed);
  return (
    <details className={"check " + (r.passed ? "ok" : "bad")} open={open}
      onToggle={(e) => setOpen(e.currentTarget.open)}>
      <summary>
        <span className="check-badge" aria-hidden="true">{r.passed ? SYMBOL.pass : SYMBOL.fail}</span>
        <span className="check-name">{LABELS[r.criterion] || r.criterion}</span>
        <span className="check-flag">{r.passed ? "Pass" : "Fail"}</span>
      </summary>
      <p>{r.reason}</p>
      <dl className="pair">
        <div><dt>Tender asks</dt><dd>{r.tender_value}</dd></div>
        <div><dt>Your limit</dt><dd>{limitText(r.criterion, r.criteria_value)}</dd></div>
      </dl>
    </details>
  );
}

export default function App() {
  const [step, setStep] = useState("criteria"); // "criteria" | "tender"
  const [showDemo, setShowDemo] = useState(false);
  const [contractors, setContractors] = useState([]);
  const [contractor, setContractor] = useState("");
  const [editing, setEditing] = useState("");
  const [draft, setDraft] = useState(EMPTY_DRAFT);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState("");
  const [file, setFile] = useState(null);
  const [title, setTitle] = useState("");
  const [loading, setLoading] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const [error, setError] = useState("");
  const [loadError, setLoadError] = useState("");
  const [result, setResult] = useState(null);
  const [bidBusy, setBidBusy] = useState(false);
  const [bidError, setBidError] = useState("");
  const [toast, setToast] = useState("");

  useEffect(() => {
    fetch("/api/contractors")
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error("bad status " + r.status))))
      .then((list) => {
        setContractors(list);
        const mine = list.filter((c) => c.mine);
        if (mine.length) {
          chooseFirm(mine[0].name, list);
          setStep("tender");
        } else {
          setContractor("");
          setEditing("");
          setDraft(EMPTY_DRAFT);
        }
      })
      .catch(() =>
        setLoadError("Cannot reach the backend. Start it with: uvicorn api_server:app --reload")
      );
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!loading) return undefined;
    setElapsed(0);
    const t = setInterval(() => setElapsed((n) => n + 1), 1000);
    return () => clearInterval(t);
  }, [loading]);

  useEffect(() => {
    if (!toast) return undefined;
    const t = setTimeout(() => setToast(""), 2600);
    return () => clearTimeout(t);
  }, [toast]);

  function chooseFirm(name, list = contractors) {
    setSaveError("");
    setContractor(name);
    setEditing(name);
    const found = list.find((c) => c.name === name);
    setDraft(found ? toDraft(found.profile) : EMPTY_DRAFT);
  }

  const setField = (key, value) => setDraft((d) => ({ ...d, [key]: value }));

  async function saveCriteria(e) {
    e.preventDefault();
    setSaveError("");
    const payload = toPayload(draft);
    if (!payload.contractor_name) return setSaveError("Enter your firm's name.");
    const numbers = [payload.years_experience, ...LIMIT_FIELDS.map(([k]) => payload[k])];
    if (numbers.some((n) => n !== null && Number.isNaN(n))) {
      return setSaveError("Use numbers only in the limit fields.");
    }
    setSaving(true);
    try {
      const res = await fetch("/api/contractors", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ original_name: editing || null, profile: payload }),
      });
      if (!res.ok) throw new Error(await errorText(res));
      const saved = await res.json();
      setContractors(await (await fetch("/api/contractors")).json());
      setContractor(saved.name);
      setEditing(saved.name);
      setResult(null);
      setStep("tender");
      setToast("Criteria saved");
    } catch (err) {
      setSaveError(err.message || "Could not save your criteria.");
    } finally {
      setSaving(false);
    }
  }

  async function analyse(e) {
    e.preventDefault();
    if (!file || !contractor) return;
    setLoading(true);
    setError("");
    setBidError("");
    setResult(null);
    const form = new FormData();
    form.append("file", file);
    form.append("contractor_name", contractor);
    form.append("title", title);
    try {
      const res = await fetch("/api/decide", { method: "POST", body: form });
      if (!res.ok) throw new Error(await errorText(res));
      setResult(await res.json());
    } catch (err) {
      setError(err.message || "Something went wrong.");
    } finally {
      setLoading(false);
    }
  }

  async function downloadBid() {
    if (!result) return;
    const force = result.decision === "Reject";
    if (force && !window.confirm(
      "This tender was rejected for your firm. The draft will start with the failed checks listed. Create it anyway?"
    )) return;
    setBidBusy(true);
    setBidError("");
    try {
      const res = await fetch("/api/generate-bid", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ result_id: result.result_id, force }),
      });
      if (!res.ok) throw new Error(await errorText(res));
      const blob = await res.blob();
      const m = /filename="?([^";]+)"?/i.exec(res.headers.get("Content-Disposition") || "");
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = m ? m[1] : "Bid_Draft.docx";
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
      setToast("Draft bid downloaded");
    } catch (err) {
      setBidError(err.message || "Could not create the bid document.");
    } finally {
      setBidBusy(false);
    }
  }

  async function copySummary() {
    try {
      await navigator.clipboard.writeText(summaryText(result));
      setToast("Summary copied");
    } catch {
      setToast("Copy is blocked in this browser");
    }
  }

  const selected = contractors.find((c) => c.name === contractor);
  const visible = contractors.filter((c) => c.mine || showDemo || c.name === contractor);
  const hasMine = contractors.some((c) => c.mine);
  const verdictKind = result?.decision === "Select" ? "select"
    : result?.decision === "Reject" ? "reject" : "unknown";   // "unknown" = Insufficient data
  const isSelect = verdictKind === "select";
  const stepNo = step === "criteria" ? 1 : result ? 3 : 2;
  const STEPS = [
    ["Your criteria", "Set your limits once"],
    ["Tender", "Upload the document"],
    ["Result", "Select or Reject"],
  ];

  return (
    <div className="app">
      <aside className="side">
        <div className="brand">
          <span className="mark" aria-hidden="true">TG</span>
          <div><strong>TenderGuard AI</strong><span>Bid or skip, with reasons</span></div>
        </div>

        <ol className="stepper" aria-label="Progress">
          {STEPS.map(([name, sub], i) => {
            const n = i + 1;
            const cls = n === stepNo ? "on" : n < stepNo ? "done" : "";
            const clickable = n === 1 || (n === 2 && contractor);
            return (
              <li key={name} className={cls} aria-current={n === stepNo ? "step" : undefined}>
                <button type="button" disabled={!clickable}
                  onClick={() => setStep(n === 1 ? "criteria" : "tender")}>
                  <span className="num">{n < stepNo ? SYMBOL.pass : n}</span>
                  <span><strong>{name}</strong><em>{sub}</em></span>
                </button>
              </li>
            );
          })}
        </ol>

        {selected && (
          <div className="firmcard">
            <p className="fc-label">Checking for</p>
            <p className="fc-name">{selected.name}</p>
            <p className="fc-meta">
              <span className="chip dark">PEC {selected.pec_category}</span>
              {selected.max_contract_value_pkr ? ` up to ${pkr(selected.max_contract_value_pkr)}` : ""}
            </p>
            <button type="button" className="linkbtn light" onClick={() => setStep("criteria")}>
              Edit criteria
            </button>
          </div>
        )}
      </aside>

      <main className="main">
        {loadError && <p className="msg error" role="alert">{loadError}</p>}

        {step === "criteria" && (
          <form className="split" onSubmit={saveCriteria}>
            <div className="card">
              <h1>Your criteria</h1>
              <p className="lead">
                Every tender you upload is compared with these limits. Leave a limit empty if you have
                none; that check is then skipped, never guessed.
              </p>
              {!hasMine && (
                <p className="msg warn">
                  <strong>Start here.</strong> Enter your own firm&rsquo;s details and save. Next time the
                  app opens directly on the tender screen.
                </p>
              )}

              <label htmlFor="profile">Saved firm</label>
              <select id="profile" value={editing} onChange={(e) => chooseFirm(e.target.value)}>
                <option value="">New firm</option>
                {visible.map((c) => <option key={c.name} value={c.name}>{c.name}</option>)}
              </select>
              <div className="inline-check">
                <input id="demo" type="checkbox" checked={showDemo}
                  onChange={(e) => setShowDemo(e.target.checked)} />
                <label htmlFor="demo">Show demo firms (examples for trying the app)</label>
              </div>

              <h2>Your firm</h2>
              <label htmlFor="cname">Firm name</label>
              <input id="cname" type="text" value={draft.contractor_name} required
                onChange={(e) => setField("contractor_name", e.target.value)} />

              <label id="pec-l">PEC licence category <span className="opt">lowest to highest</span></label>
              <div className="chips" role="radiogroup" aria-labelledby="pec-l">
                {PEC_ORDER.map((c) => (
                  <button key={c} type="button" role="radio" aria-checked={draft.pec_category_held === c}
                    className={draft.pec_category_held === c ? "chip-btn on" : "chip-btn"}
                    onClick={() => setField("pec_category_held", c)}>
                    {c}
                  </button>
                ))}
              </div>

              <div className="row2">
                <div>
                  <label htmlFor="years">Years of experience</label>
                  <input id="years" type="number" min="0" step="1" value={draft.years_experience}
                    onChange={(e) => setField("years_experience", e.target.value)} />
                </div>
                <div>
                  <span className="lbl" id="tax-l">FBR Active Taxpayer List</span>
                  <button type="button" role="switch" aria-checked={draft.is_active_taxpayer}
                    aria-labelledby="tax-l"
                    className={"switch" + (draft.is_active_taxpayer ? " on" : "")}
                    onClick={() => setField("is_active_taxpayer", !draft.is_active_taxpayer)}>
                    <span className="knob" />
                    <em>{draft.is_active_taxpayer ? "My firm is listed" : "Not listed"}</em>
                  </button>
                </div>
              </div>

              <h2>Your limits</h2>
              <div className="row2">
                {LIMIT_FIELDS.map(([key, label, kind]) => (
                  <div key={key}>
                    <label htmlFor={key}>{label}</label>
                    <input id={key} type="number" min="0" step="any" value={draft[key]}
                      placeholder="No limit" onChange={(e) => setField(key, e.target.value)} />
                    {kind === "money" && draft[key] !== "" && !Number.isNaN(Number(draft[key])) && (
                      <p className="hint">{pkr(draft[key])}</p>
                    )}
                  </div>
                ))}
              </div>

              <details className="more">
                <summary>Details for the draft bid <span className="opt">optional</span></summary>
                <div className="row2">
                  {COMPANY_FIELDS.map(([key, label]) => (
                    <div key={key} className={key === "company_address" ? "full" : ""}>
                      <label htmlFor={key}>{label}</label>
                      <input id={key} type="text" value={draft[key]}
                        onChange={(e) => setField(key, e.target.value)} />
                    </div>
                  ))}
                </div>
              </details>

              <button className="primary" type="submit" disabled={saving}>
                {saving ? "Saving…" : "Save and continue"}
              </button>
              {saveError && <p className="msg error" role="alert">{saveError}</p>}
            </div>

            <aside className="preview" aria-label="Profile preview">
              <p className="fc-label">Preview</p>
              <p className="pv-name">{draft.contractor_name || "Your firm"}</p>
              <p>
                <span className="chip">PEC {draft.pec_category_held}</span>{" "}
                <span className={"chip " + (draft.is_active_taxpayer ? "good" : "muted")}>
                  {draft.is_active_taxpayer ? "Active taxpayer" : "Not on taxpayer list"}
                </span>
              </p>
              <dl>
                <div><dt>Contract size</dt>
                  <dd>{rangeText(draft.min_contract_value_pkr, draft.max_contract_value_pkr)}</dd></div>
                <div><dt>Bid security</dt>
                  <dd>{draft.max_bid_security_pkr === "" ? "No limit set" : "Up to " + pkr(draft.max_bid_security_pkr)}</dd></div>
                <div><dt>Liquidated damages</dt>
                  <dd>{draft.max_acceptable_ld_rate_percent_per_day === "" ? "No limit set" : "Up to " + draft.max_acceptable_ld_rate_percent_per_day + "% per day"}</dd></div>
                <div><dt>Advance payment</dt>
                  <dd>{draft.min_required_advance_payment_percent === "" ? "No limit set" : "At least " + draft.min_required_advance_payment_percent + "%"}</dd></div>
                <div><dt>Completion period</dt>
                  <dd>{draft.max_acceptable_completion_period_days === "" ? "No limit set" : "At least " + draft.max_acceptable_completion_period_days + " days"}</dd></div>
                <div><dt>Experience</dt><dd>{draft.years_experience || 0} years</dd></div>
              </dl>
            </aside>
          </form>
        )}

        {step === "tender" && (
          <>
            <form className="card upload" onSubmit={analyse}>
              <h1>Check a tender</h1>
              <FileDrop file={file} onFile={setFile} disabled={loading} />
              <label htmlFor="title">Project title <span className="opt">optional</span></label>
              <input id="title" type="text" value={title} placeholder="Use when the PDF lists many tenders"
                onChange={(e) => setTitle(e.target.value)} />
              <button className="primary" type="submit" disabled={!file || !contractor || loading}>
                {loading ? "Reading the tender…" : "Check this tender"}
              </button>
              {error && <p className="msg error" role="alert">{error}</p>}
            </form>

            {loading && (
              <div className="card working" role="status">
                <span className="spinner" aria-hidden="true" />
                <div>
                  <strong>Reading the document and comparing it with your limits</strong>
                  <p className="hint">{elapsed} s. Scanned PDFs can take a few minutes.</p>
                </div>
              </div>
            )}

            {result && !loading && (
              <section className="result" aria-live="polite">
                <div className={"verdict " + verdictKind}>
                  <span className="stamp" aria-hidden="true">
                    {verdictKind === "select" ? SYMBOL.pass : verdictKind === "reject" ? SYMBOL.fail : "?"}
                  </span>
                  <div>
                    <p className="v-sub">{result.contractor_name}</p>
                    <p className={"v-word" + (verdictKind === "unknown" ? " long" : "")}>
                      {verdictKind === "unknown" ? "Not enough data" : result.decision}
                    </p>
                    <p className="v-sub">{result.tender_title}</p>
                  </div>
                  <p className="v-count"><b>{result.criteria_checked}</b> of {result.criteria_total}<span>checks run</span></p>
                </div>

                <CoverageStrip result={result} />

                {result.deadline_warning && (
                  <p className="msg warn"><strong>Deadline.</strong> {result.deadline_warning}</p>
                )}
                {verdictKind === "unknown" && (
                  <p className="msg warn"><strong>No verdict.</strong> Only {result.criteria_checked} of {result.criteria_total} checks
                    could run and none failed. That is too little to call this tender a Select, and it is not a Reject either.
                    The document gave few of the values the checks need, or your criteria have no limits for them.
                    Read the full tender yourself.</p>
                )}
                {result.low_confidence && verdictKind !== "unknown" && (
                  <p className="msg warn"><strong>Low confidence.</strong> Most requirements could not be
                    checked. Read the full tender yourself before relying on this result.</p>
                )}
                {result.text_truncated && (
                  <p className="msg warn"><strong>Long document.</strong> Only the first 60,000 of{" "}
                    {result.text_length.toLocaleString("en-PK")} characters were read, so later clauses may be missing.</p>
                )}

                <h2>Why</h2>
                {result.results.length === 0 ? (
                  <p className="hint">No check could run: the tender did not state the values the matcher compares.</p>
                ) : (
                  [...result.results].sort((a, b) => a.passed - b.passed)
                    .map((r) => <CheckCard key={r.criterion} r={r} />)
                )}
                {result.skipped_criteria.length > 0 && (
                  <p className="hint">
                    Not compared: {result.skipped_criteria.map((n) => (LABELS[n] || n).toLowerCase()).join(", ")}.
                    The tender or your profile gave no value.
                  </p>
                )}
                <p className="hint">
                  This tool does not yet check turnover, liquid cash or the value of past contracts.
                  Confirm those in the tender yourself.
                </p>

                <details className="more fields">
                  <summary>What the AI read from the document</summary>
                  <dl>
                    {FIELD_ROWS.map(([key, label, kind]) => {
                      const v = fieldValue(result.extracted_fields[key], kind);
                      return (
                        <div key={key}>
                          <dt>{label}</dt>
                          <dd className={v === null ? "none" : ""}>{v ?? "Not stated"}</dd>
                        </div>
                      );
                    })}
                  </dl>
                  <p className="hint">Check these against the PDF. Anything the document does not state stays empty.</p>
                </details>

                <div className="actions">
                  <button className="primary" onClick={downloadBid} disabled={bidBusy}>
                    {bidBusy ? "Preparing…" : isSelect ? "Download draft bid (.docx)" : "Download draft anyway (.docx)"}
                  </button>
                  <button className="secondary" onClick={copySummary}>Copy summary</button>
                </div>
                <p className="hint">A draft only. Prices, certificates and the bid security are yours to complete before submitting.</p>
                {bidError && <p className="msg error" role="alert">{bidError}</p>}
              </section>
            )}
          </>
        )}
      </main>

      {toast && <div className="toast" role="status">{toast}</div>}
    </div>
  );
}
