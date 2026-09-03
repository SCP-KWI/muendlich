// Run with `npm test` (node --test). Plain node, no build step, no browser.
import assert from "node:assert/strict";
import { test } from "node:test";

import {
  EXCEL_HINT,
  MAX_NAMES,
  decodeBytes,
  detectDelimiter,
  parseDelimited,
  parseNames,
} from "../src/nameList.js";

// Shaped like a Swiss school administration's export; the people are made up.
const EXPORT = [
  "Nachname;Vorname;Geschlecht;Klasse;EMail;Geburtstag;Adresse;Ort;PLZ;Telefon;Mobile",
  'Aebi;Lena;w;4a;lena.aebi@example.ch;31.10.2010;"Weg 1";Zürich;8055;"+41 44 000 00 01";',
  'Berger;Lukas;m;4a;lukas.berger@example.ch;03.06.2011;"Strasse 2; Haus B";Uster;8610;;"+41 76 000 00 02"',
  'Christen;Lukas;m;4a;lukas.christen@example.ch;19.10.2010;"Platz 3";"Uitikon Waldegg";8142;;',
  'Dubois;Mia;w;4a;mia.dubois@example.ch;01.09.2010;"Gasse 4";Zürich;8003;;',
  "",
].join("\r\n");

test("one name per line, as typed", () => {
  const r = parseNames("Anna Meier\n\nBen\n  Colin  \n");
  assert.equal(r.kind, "list");
  assert.deepEqual(r.names, ["Anna Meier", "Ben", "Colin"]);
  assert.deepEqual(r.warnings, []);
});

test("list markers and surrounding quotes are dropped", () => {
  const r = parseNames('1. Anna\n2) Ben\n- Colin\n• Dana\n"Eli"');
  assert.deepEqual(r.names, ["Anna", "Ben", "Colin", "Dana", "Eli"]);
});

test("a single line of names side by side", () => {
  assert.deepEqual(parseNames("Anna, Ben,Colin").names, ["Anna", "Ben", "Colin"]);
  assert.deepEqual(parseNames("Anna; Ben").names, ["Anna", "Ben"]);
});

test("empty input is empty, not an error", () => {
  assert.deepEqual(parseNames(""), { kind: "empty", names: [], warnings: [] });
  assert.deepEqual(parseNames("  \n\n").names, []);
  assert.deepEqual(parseNames(null).names, []);
});

test("school export: the Vorname column, nothing else", () => {
  const r = parseNames(EXPORT);
  assert.equal(r.kind, "table");
  assert.equal(r.columns[1], "Vorname");
  assert.equal(r.firstCol, 1);
  assert.equal(r.lastCol, 0);
  // Two pupils called Lukas: both get their surname, nobody else does.
  assert.deepEqual(r.names, ["Lena", "Lukas Berger", "Lukas Christen", "Mia"]);
  assert.deepEqual(r.warnings, []);
});

test("a quoted cell may contain the delimiter", () => {
  const rows = parseDelimited('a;"b; c";"say ""hi"""\n1;2;3', ";");
  assert.deepEqual(rows, [
    ["a", "b; c", 'say "hi"'],
    ["1", "2", "3"],
  ]);
});

test("a copy from a spreadsheet is tab-separated", () => {
  const r = parseNames("Vorname\tNachname\nAnna\tMeier\nBen\tHuber\n");
  assert.equal(detectDelimiter(["Vorname\tNachname"]), "\t");
  assert.deepEqual(r.names, ["Anna", "Ben"]);
  assert.equal(r.firstCol, 0);
  assert.equal(r.lastCol, 1);
});

test("without a heading row the surname is assumed to come first", () => {
  const r = parseNames("Meier, Anna\nHuber, Ben\nHuber, Anna");
  assert.equal(r.kind, "table");
  assert.deepEqual(r.columns, ["Spalte 1", "Spalte 2"]);
  assert.deepEqual(r.names, ["Anna Meier", "Ben", "Anna Huber"]);
});

test("the guess can be overridden column by column", () => {
  const text = "Anna;Meier\nBen;Huber";
  assert.deepEqual(parseNames(text).names, ["Meier", "Huber"]);
  const r = parseNames(text, { firstCol: 0, lastCol: 1 });
  assert.deepEqual(r.names, ["Anna", "Ben"]);
  assert.equal(r.firstCol, 0);
  assert.equal(r.lastCol, 1);
  // Picking the same column twice cannot mean anything: no surname then.
  assert.equal(parseNames(text, { firstCol: 1, lastCol: 1 }).lastCol, -1);
  // Out of range is ignored rather than crashing on a stale choice.
  assert.equal(parseNames(text, { firstCol: 7 }).firstCol, 1);
});

test("without a surname column, shared given names are a warning", () => {
  const r = parseNames(EXPORT, { lastCol: -1 });
  assert.equal(r.lastCol, -1);
  assert.deepEqual(r.names, ["Lena", "Lukas", "Lukas", "Mia"]);
  assert.equal(r.warnings.length, 1);
  assert.match(r.warnings[0], /„Lukas“ kommt 2×/);
});

test("a plain 'Name' column is taken whole", () => {
  const r = parseNames("Name;Klasse\nAnna Meier;4a\nBen Huber;4a");
  assert.deepEqual(r.names, ["Anna Meier", "Ben Huber"]);
});

test("repeated names in a plain list are a warning", () => {
  const r = parseNames("Anna\nBen\nanna");
  assert.deepEqual(r.names, ["Anna", "Ben", "anna"]);
  assert.match(r.warnings[0], /„Anna“ kommt 2×/);
});

test("BOM and CRLF from a Windows export are harmless", () => {
  const r = parseNames("\uFEFFVorname;Nachname\r\nAnna;Meier\r\n");
  assert.deepEqual(r.names, ["Anna"]);
});

test("a heading row is not a pupil, but a single column has no headings", () => {
  assert.deepEqual(parseNames("Vorname;Nachname\nAnna;Meier").names, ["Anna"]);
  // One column is a plain list; a stray "Vorname" would show up in the
  // preview as a name, where the teacher can delete it.
  assert.deepEqual(parseNames("Vorname\nAnna\nBen").names, ["Vorname", "Anna", "Ben"]);
});

test("too many names is a warning, not a silent cut", () => {
  const many = Array.from({ length: MAX_NAMES + 1 }, (_, i) => `Kind ${i}`).join("\n");
  const r = parseNames(many);
  assert.equal(r.names.length, MAX_NAMES + 1);
  assert.match(r.warnings[0], /Höchstens 500/);
});

test("an over-long name is a warning", () => {
  const r = parseNames("Anna\n" + "N".repeat(201));
  assert.match(r.warnings[0], /länger als 200/);
});

test("decodeBytes: UTF-8 as is, cp1252 when UTF-8 does not fit", () => {
  const utf8 = new TextEncoder().encode("Kübler;Jonas");
  assert.equal(decodeBytes(utf8), "Kübler;Jonas");
  const cp1252 = Uint8Array.from(Buffer.from("K\xfcbler;Jonas", "latin1"));
  assert.equal(decodeBytes(cp1252), "Kübler;Jonas");
});

test("decodeBytes: an Excel file is refused with a way out", () => {
  const xlsx = Uint8Array.from([0x50, 0x4b, 0x03, 0x04, 0, 0, 0, 0]);
  assert.throws(() => decodeBytes(xlsx), { message: EXCEL_HINT });
  const xls = Uint8Array.from([0xd0, 0xcf, 0x11, 0xe0, 0xa1, 0xb1, 0x1a, 0xe1]);
  assert.throws(() => decodeBytes(xls), { message: EXCEL_HINT });
});
