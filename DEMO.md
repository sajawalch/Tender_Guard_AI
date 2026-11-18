# Demo guide (about 5 minutes, no real tender PDF needed)

The files in `demo_tenders/` are short written tenders. Every value is stated in the text, so the AI should read
them correctly. Each row below shows the result the matching rules give **when the AI reads the values correctly**.
The rules were run on the answer key (`synthetic_ground_truth.json`), not on a live model run. If a result on screen
differs, open "What the AI read" and compare it with the text.

## Set up

```powershell
# terminal 1 (project folder)
conda activate tenderguard
$env:OPENAI_API_KEY="your_key"
python -m uvicorn api_server:app --reload

# terminal 2
cd frontend
npm run dev
```

Open http://localhost:5173. On the "Your criteria" screen tick **"Show demo firms"** to pick the demo firms below.
Then go to "Check a tender", drag in a file from `demo_tenders/`, and press "Check this tender".

## Cases

| Tender file | Firm | Expected | What to point out |
|---|---|---|---|
| `ST-01.txt` | Al-Hamd Builders (Pvt) Ltd | **Select**, 8 of 8 checks | Every check ran and passed. The coverage strip is all green |
| `ST-04.txt` | Sindh Horizon Builders | **Select**, 8 of 8 | A different firm and tender, same rules |
| `ST-10.txt` | Khyber Engineering & Construction Co. | **Select**, 8 of 8 | |
| `ST-05.txt` | Indus Valley Infrastructure Ltd | **Select**, 8 of 8 | A very large project (PEC C-1 firm) |
| `ST-02.txt` | Sindh Horizon Builders | **Reject** | Contract value PKR 420,000,000 is over the firm's PKR 100,000,000 limit, and the bid security PKR 10,500,000 is over its PKR 4,000,000 limit |
| `ST-01.txt` | Pak Frontier Constructors | **Reject**, four reasons | Value, PEC category (C-6 held, C-4 required), bid security and experience all fail. Every reason is shown |
| `ST-03.txt` | Pak Frontier Constructors | **Reject**, 7 of 8 | A single reason: the tender gives 30 days and the firm needs at least 60. One check is skipped and listed |
| `vague-notice.txt` | any firm | **Not enough data** | The notice states no values, so nothing can be compared. The app does not say Select or Reject |

Most firm and tender pairs end in Reject, because the demo firms have fairly tight limits. That is why the Select
cases above are the ones to use.

## After a result

1. Open "What the AI read" and show that every value is there to check against the text.
2. Press "Download draft bid (.docx)" and open it. Point out:
   - the **first page is a cover page** for the contractor only (warnings, a to-do list, and a note that the
     checklist was written by AI and may leave out conditions). It is deleted before submitting;
   - the **date and the price are left blank** on purpose;
   - the declaration carries a drafting note to sign only after checking each requirement.

## Things to say honestly

- The decision comes from plain rules. The AI only reads the document.
- The requirements checklist is written by AI and is not guaranteed complete; read the notice itself.
- No financial checks yet (turnover, cash, value of past contracts).
- Extraction on real tenders is weaker than on these clean written ones. See the accuracy table in the README.

## Screenshots to take for the README

1. "Your criteria" with the live preview.
2. A **Select** result with the coverage strip.
3. A **Reject** result with several failed checks open.
4. The **Not enough data** result.
5. The first page of a draft bid (the cover page).