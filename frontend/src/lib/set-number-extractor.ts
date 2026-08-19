/**
 * Picking a set number out of OCR text — the regex layer that used to live server-side, in
 * `backend/app/services/ocr.py`, before OCR moved entirely on-device and that file was deleted.
 * This is now the only copy. Used by every OCR path (`lib/offline-ocr.ts`, the camera loop and
 * photo import both): a set number is never the only thing OCR reads off a box — a barcode, a
 * phone number, a copyright year, an age rating all show up in the same output.
 */

/** 4-6 digits, optionally with Rebrickable's `-N` variant suffix. */
const SET_NUMBER = /\b(\d{4,6})(-\d{1,2})?\b/g
/** The explicitly labelled form printed on European packaging. */
const LABELLED = /(?:Set No\.?|Art\.?\s?Nr\.?)\s*(\d{4,6})/i
/** LEGO's own customer-service number is printed on every box and matches the set-number shape. */
const PHONE = /\b\d{1,3}-\d{3}-\d{3}-\d{4}\b/

function isPlausible(numberText: string): boolean {
  const value = Number(numberText)
  if (!Number.isInteger(value)) return false
  // A copyright year is a 4-digit number in exactly this range and appears on every box.
  if (numberText.length === 4 && value >= 1949 && value <= 2035) return false
  // A full EAN-13 barcode read as text.
  return numberText.length < 12
}

/** Every plausible set number in the OCR output, in order, deduped. */
export function extractSetNumbers(candidates: string[]): string[] {
  const results: string[] = []
  const seen = new Set<string>()

  function keep(value: string): void {
    if (!seen.has(value)) {
      seen.add(value)
      results.push(value)
    }
  }

  for (const text of candidates) {
    if (PHONE.test(text)) continue

    const labelled = LABELLED.exec(text)
    if (labelled && isPlausible(labelled[1])) {
      keep(labelled[1])
    }

    // `SET_NUMBER` carries the `g` flag and so its own `lastIndex` state across calls — reset it
    // before each text, or a match found near the end of one candidate silently skips the start
    // of the next.
    SET_NUMBER.lastIndex = 0
    let match: RegExpExecArray | null
    while ((match = SET_NUMBER.exec(text)) !== null) {
      const number = match[1]
      if (!isPlausible(number)) continue
      keep(match[2] ? number + match[2] : number)
    }
  }

  return results
}
