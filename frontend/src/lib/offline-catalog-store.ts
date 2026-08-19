/**
 * The device's own copy of the offline catalogue, pulled from `GET /catalog/export` into
 * IndexedDB — what lets a set/minifig number resolve to a name, year and image with **zero**
 * backend round trip, which is what camera/manual scanning needs to work away from the LAN this
 * app is hosted on.
 *
 * Mirrors `backend/app/services/catalog.py`'s `lookup_catalog_set`/`lookup_catalog_minifig`
 * exactly (the `-1` suffix tried first, then the bare number) so a set resolves the same way
 * whether the lookup happened on the server or on this device.
 *
 * `catalogMeta` is this *device's* own "when did I last pull this" bookkeeping — distinct from
 * the backend's `CatalogState.downloadedAt`, which is "when did the server last pull from
 * Rebrickable." A device can be behind the server's copy if a pull was interrupted.
 */

import { openDB, type DBSchema, type IDBPDatabase } from 'idb'

import type { LegoSet } from '../api/types'

export type OfflineCatalogName = 'sets' | 'minifigs'

interface CatalogSetRow {
  setNum: string
  name: string
  year: number
  themeId: number
  numParts: number
  setImgUrl: string | null
  firstSeenAt: string | null
}

interface CatalogMinifigRow {
  figNum: string
  name: string
  numParts: number
  imgUrl: string | null
  themeId: number | null
  year: number | null
  containingSetNums: string[]
}

interface CatalogMetaRow {
  name: OfflineCatalogName
  exportedAt: string
  rowCount: number
}

interface OfflineCatalogSchema extends DBSchema {
  catalogSets: { key: string; value: CatalogSetRow }
  catalogMinifigs: { key: string; value: CatalogMinifigRow }
  catalogMeta: { key: string; value: CatalogMetaRow }
}

const DB_NAME = 'brickseeker-catalog'
const DB_VERSION = 1
/** Rows per IndexedDB transaction — big enough that ~28k sets is a few dozen transactions, small
 *  enough that a page reload mid-pull loses at most one chunk rather than the whole import. */
const CHUNK_ROWS = 500

let dbPromise: Promise<IDBPDatabase<OfflineCatalogSchema>> | null = null

function db(): Promise<IDBPDatabase<OfflineCatalogSchema>> {
  dbPromise ??= openDB<OfflineCatalogSchema>(DB_NAME, DB_VERSION, {
    upgrade(database) {
      database.createObjectStore('catalogSets', { keyPath: 'setNum' })
      database.createObjectStore('catalogMinifigs', { keyPath: 'figNum' })
      database.createObjectStore('catalogMeta', { keyPath: 'name' })
    },
  })
  return dbPromise
}

const STORE_FOR: Record<OfflineCatalogName, 'catalogSets' | 'catalogMinifigs'> = {
  sets: 'catalogSets',
  minifigs: 'catalogMinifigs',
}

/** Streams `GET /catalog/export`, NDJSON, one row per line — not routed through `api.get`, which
 *  `JSON.parse`s a whole response body at once; this reads it as text and parses line by line so
 *  neither side ever holds the export as one giant JSON array. */
async function pull(name: OfflineCatalogName): Promise<number> {
  const response = await fetch(`/api/catalog/export?name=${name}`, { credentials: 'same-origin' })
  if (!response.ok) {
    throw new Error(`Synchronisation du catalogue impossible (${response.status})`)
  }
  if (!response.body) {
    throw new Error('Synchronisation du catalogue impossible (réponse vide)')
  }

  const database = await db()
  const storeName = STORE_FOR[name]
  const reader = response.body.pipeThrough(new TextDecoderStream()).getReader()
  let buffered = ''
  let chunk: (CatalogSetRow | CatalogMinifigRow)[] = []
  let imported = 0

  async function flush(): Promise<void> {
    if (chunk.length === 0) return
    const tx = database.transaction(storeName, 'readwrite')
    // `storeName` is a union, so `tx.store` is too and its `put` narrows to the intersection of
    // both row shapes. The row genuinely matches whichever store `name` selected.
    const store = tx.store as unknown as { put: (row: CatalogSetRow | CatalogMinifigRow) => unknown }
    for (const row of chunk) void store.put(row)
    await tx.done
    imported += chunk.length
    chunk = []
  }

  // Parsed off the stream a line at a time rather than from one buffered `response.text()`: the
  // sets export is ~28 000 rows and the minifig one carries a `containingSetNums` array per row,
  // so materialising the whole body as a string *and* an array of every line at once is tens of
  // megabytes held on a phone for no reason — the endpoint streams NDJSON precisely so it needn't
  // be.
  for (;;) {
    const { done, value } = await reader.read()
    if (done) break
    buffered += value
    let newline = buffered.indexOf('\n')
    while (newline !== -1) {
      const line = buffered.slice(0, newline).trim()
      buffered = buffered.slice(newline + 1)
      if (line) chunk.push(JSON.parse(line))
      if (chunk.length >= CHUNK_ROWS) await flush()
      newline = buffered.indexOf('\n')
    }
  }
  // A final line with no trailing newline is legal NDJSON.
  const tail = buffered.trim()
  if (tail) chunk.push(JSON.parse(tail))
  await flush()

  // Counted off the store rather than off this import: rows the server dropped from a later dump
  // are deliberately kept (as they are server-side), so "how many entries does this device hold"
  // is not the same number as "how many arrived just now".
  const rowCount = await database.count(storeName)
  await database.put('catalogMeta', { name, exportedAt: new Date().toISOString(), rowCount })
  return imported
}

async function purgeLocal(name: OfflineCatalogName): Promise<void> {
  const database = await db()
  await database.clear(STORE_FOR[name])
  await database.delete('catalogMeta', name)
}

async function meta(name: OfflineCatalogName): Promise<CatalogMetaRow | undefined> {
  return (await db()).get('catalogMeta', name)
}

async function isEmpty(name: OfflineCatalogName): Promise<boolean> {
  const row = await meta(name)
  return !row || row.rowCount === 0
}

/** Mirrors `lookup_catalog_set`: the `-1` suffix first (what a box number usually omits), then the
 *  bare number. `null` on a miss — never "ambiguous", unlike the live resolver. */
async function lookupSet(setNum: string): Promise<LegoSet | null> {
  const database = await db()
  for (const candidate of [`${setNum}-1`, setNum]) {
    const row = await database.get('catalogSets', candidate)
    if (row) {
      return {
        setNum: row.setNum,
        name: row.name,
        year: row.year,
        themeId: row.themeId,
        numParts: row.numParts,
        setImgUrl: row.setImgUrl,
        setUrl: null,
      }
    }
  }
  return null
}

/** Mirrors `lookup_catalog_minifig` — a minifig has no live single-item Rebrickable lookup at all,
 *  online or off, so this is the only path that can ever resolve a bare fig number. */
async function lookupMinifig(figNum: string): Promise<LegoSet | null> {
  const row = await (await db()).get('catalogMinifigs', figNum)
  if (!row) return null
  return {
    setNum: row.figNum,
    name: row.name,
    year: row.year ?? 0,
    themeId: row.themeId ?? 0,
    numParts: row.numParts,
    setImgUrl: row.imgUrl,
    setUrl: null,
  }
}

export const offlineCatalogStore = {
  pull,
  purge: purgeLocal,
  meta,
  isEmpty,
  lookupSet,
  lookupMinifig,
}
