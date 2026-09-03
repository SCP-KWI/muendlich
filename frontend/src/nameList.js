// Turning whatever a teacher pastes or uploads into a list of pupil names.
//
// Everything here runs in the browser. A school's export carries far more than
// names — birthdays, addresses, phone numbers — and none of it may leave the
// device. Only the names picked out below are ever sent to the backend, which
// has no endpoint that would take the rest.
//
// No JSX and no imports, so `node --test` can exercise it directly
// (frontend/test/nameList.test.js, `npm test`).

// Mirrors MAX_BATCH in backend/app/schemas.py.
export const MAX_NAMES = 500;
// Mirrors MAX_NAME in backend/app/schemas.py.
const MAX_NAME_LENGTH = 200;

// Column headings a school export or a spreadsheet is likely to use.
const FIRST_NAME_HEADER = /^(vorname|vornamen|rufname|first ?name|given ?name|pr[ée]nom)$/i;
const LAST_NAME_HEADER = /^(nachname|familienname|last ?name|surname|family ?name|nom)$/i;
// A single "Name" column is taken as it is, whatever it contains.
const NAME_HEADER = /^(name|namen|schüler\/?in|schüler|schülerin|person|pupil|student)$/i;
// Any of these in the first row makes it a heading row rather than a pupil.
const ANY_HEADER = new RegExp(
  "^(vorname|vornamen|rufname|nachname|familienname|name|namen|geschlecht|klasse|e-?mail|" +
    "geburtstag|geburtsdatum|adresse|strasse|ort|plz|telefon|mobile|" +
    "first ?name|last ?name|surname|given ?name|family ?name|gender|class|" +
    "birthday|address|phone|pr[ée]nom|nom)$",
  "i"
);

/** Split delimited text into rows of cells (RFC 4180 quoting, any newline). */
export function parseDelimited(text, delimiter) {
  const rows = [];
  let row = [];
  let cell = "";
  let quoted = false;
  for (let i = 0; i < text.length; i++) {
    const ch = text[i];
    if (quoted) {
      if (ch !== '"') cell += ch;
      else if (text[i + 1] === '"') {
        cell += '"';
        i++;
      } else quoted = false;
      continue;
    }
    if (ch === '"' && cell === "") {
      quoted = true;
    } else if (ch === delimiter) {
      row.push(cell);
      cell = "";
    } else if (ch === "\n" || ch === "\r") {
      if (ch === "\r" && text[i + 1] === "\n") i++;
      row.push(cell);
      rows.push(row);
      row = [];
      cell = "";
    } else {
      cell += ch;
    }
  }
  if (cell !== "" || row.length) {
    row.push(cell);
    rows.push(row);
  }
  return rows;
}

/** Tab beats everything (that is what a copy from a spreadsheet produces);
 *  otherwise the separator that most lines contain. null: no table at all. */
export function detectDelimiter(lines) {
  if (lines.some((l) => l.includes("\t"))) return "\t";
  const half = Math.ceil(lines.length / 2);
  for (const d of [";", ","]) {
    if (lines.filter((l) => l.includes(d)).length >= half) return d;
  }
  return null;
}

function cleanName(raw) {
  return String(raw ?? "")
    .replace(/^\s*(?:[-–—•*·]|\d{1,3}[.)])\s+/, "") // "1. Anna", "- Anna"
    .replace(/^"(.*)"$/s, "$1")
    .replace(/\s+/g, " ")
    .trim();
}

const key = (name) => name.toLowerCase();

function tally(names) {
  const counts = new Map();
  for (const n of names) {
    const k = key(n);
    const entry = counts.get(k) ?? { count: 0, display: n };
    entry.count++;
    counts.set(k, entry);
  }
  return counts;
}

/** Final names from {given, surname} pairs, with the warnings a teacher should
 *  see before pressing the button. A given name shared by two pupils gets the
 *  surname attached — that is also what the teacher will have to *say* when
 *  dictating about one of them, so the roster should read the same way. */
function buildNames(entries) {
  const givenCount = tally(entries.map((e) => e.given));
  const names = entries.map((e) =>
    givenCount.get(key(e.given)).count > 1 && e.surname
      ? `${e.given} ${e.surname}`
      : e.given
  );

  const warnings = [];
  for (const { count, display } of tally(names).values()) {
    if (count > 1) {
      warnings.push(
        `„${display}“ kommt ${count}× vor – so wird nur eine Person angelegt. ` +
          "Machen Sie die Namen unterscheidbar, z. B. mit dem Nachnamen."
      );
    }
  }
  for (const n of names) {
    if (n.length > MAX_NAME_LENGTH) {
      warnings.push(`„${n.slice(0, 30)}…“ ist länger als ${MAX_NAME_LENGTH} Zeichen.`);
    }
  }
  if (names.length > MAX_NAMES) {
    warnings.push(
      `Höchstens ${MAX_NAMES} Personen auf einmal – diese Liste hat ${names.length}.`
    );
  }
  return { names, warnings };
}

const isCol = (v, width) => Number.isInteger(v) && v >= 0 && v < width;

function listResult(names) {
  return {
    kind: "list",
    ...buildNames(names.filter(Boolean).map((n) => ({ given: n, surname: "" }))),
  };
}

/**
 * Names out of pasted text or a file's content.
 *
 * Returns {kind, names, warnings} plus, for a table, {columns, firstCol,
 * lastCol} so the UI can offer to pick other columns; pass those back as
 * `overrides` ({firstCol, lastCol}; lastCol -1 means none).
 *
 *  - one name per line → taken as typed ("list")
 *  - one line, comma- or semicolon-separated → the same
 *  - several lines with ; , or tab → a table: the "Vorname" column, or the
 *    first column with a heading such as "Name", or a guess without headings
 */
export function parseNames(text, overrides = {}) {
  const source = String(text ?? "").replace(/^\uFEFF/, "");
  const lines = source.split(/\r\n|\r|\n/).filter((l) => l.trim() !== "");
  if (lines.length === 0) return { kind: "empty", names: [], warnings: [] };

  const delimiter = detectDelimiter(lines);
  if (delimiter === null) return listResult(lines.map(cleanName));

  const rows = parseDelimited(source, delimiter).filter((r) =>
    r.some((c) => c.trim() !== "")
  );
  // One line of names side by side: "Anna, Ben, Colin".
  if (rows.length < 2) return listResult((rows[0] ?? []).map(cleanName));

  const hasHeader = rows[0].some((c) => ANY_HEADER.test(c.trim()));
  const header = hasHeader ? rows[0].map((c) => c.trim()) : null;
  const body = hasHeader ? rows.slice(1) : rows;
  const width = Math.max(...rows.map((r) => r.length));
  const columns = Array.from(
    { length: width },
    (_, i) => header?.[i] || `Spalte ${i + 1}`
  );

  let firstCol;
  let lastCol;
  if (header) {
    firstCol = header.findIndex((h) => FIRST_NAME_HEADER.test(h));
    if (firstCol < 0) firstCol = header.findIndex((h) => NAME_HEADER.test(h));
    if (firstCol < 0) firstCol = 0;
    lastCol = header.findIndex((h) => LAST_NAME_HEADER.test(h));
  } else {
    // No heading row. Lists sorted by surname put the surname first ("Meier,
    // Anna"), and so does the school administration's export this was built
    // against — so that is the guess. The pickers in the UI are for when it
    // is wrong.
    firstCol = width >= 2 ? 1 : 0;
    lastCol = width >= 2 ? 0 : -1;
  }
  if (isCol(overrides.firstCol, width)) firstCol = overrides.firstCol;
  if (overrides.lastCol !== undefined) {
    lastCol = isCol(overrides.lastCol, width) ? overrides.lastCol : -1;
  }
  if (lastCol === firstCol) lastCol = -1;

  const entries = [];
  for (const row of body) {
    const given = cleanName(row[firstCol]);
    if (!given) continue;
    entries.push({ given, surname: lastCol >= 0 ? cleanName(row[lastCol]) : "" });
  }
  return { kind: "table", columns, firstCol, lastCol, ...buildNames(entries) };
}

const ZIP_MAGIC = [0x50, 0x4b, 0x03, 0x04]; // .xlsx is a zip
const OLE_MAGIC = [0xd0, 0xcf, 0x11, 0xe0]; // .xls
const startsWith = (bytes, magic) => magic.every((b, i) => bytes[i] === b);

export const EXCEL_HINT =
  "Excel-Dateien kann die App nicht lesen. Bitte in Excel «Speichern unter → CSV UTF-8» wählen und diese Datei nehmen.";

/** Text from a file's bytes: UTF-8, or the Windows encoding older exports use. */
export function decodeBytes(buffer) {
  const bytes = new Uint8Array(buffer);
  if (startsWith(bytes, ZIP_MAGIC) || startsWith(bytes, OLE_MAGIC)) {
    throw new Error(EXCEL_HINT);
  }
  const utf8 = new TextDecoder("utf-8").decode(bytes);
  // A cp1252 export shows up as replacement characters exactly where the
  // umlauts are; decode it as such rather than creating a pupil "H�ring".
  return utf8.includes("\uFFFD")
    ? new TextDecoder("windows-1252").decode(bytes)
    : utf8;
}

const MAX_FILE_BYTES = 2 * 1024 * 1024;

export async function readNameFile(file) {
  if (file.size > MAX_FILE_BYTES) {
    throw new Error("Die Datei ist grösser als 2 MB – das ist keine Klassenliste.");
  }
  return decodeBytes(await file.arrayBuffer());
}
