import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api } from '../api/client'
import type { BatchStatus, CatalogName, CatalogStatus } from '../api/types'
import Icon from '../components/Icon'
import PushToggle from '../components/PushToggle'
import { Badge, ConfirmDialog, ErrorLabel, LoadingBlock, NavBar, Spinner, Toggle } from '../components/ui'
import { offlineCatalogStore, type OfflineCatalogName } from '../lib/offline-catalog-store'
import { useSettings } from '../lib/settings-context'
import { APPEARANCE_LABELS, BRAND_COLORS, type AppearanceMode, type BrandColor } from '../lib/theme'
import { formatDateTime } from '../lib/format'

function Section({
  title,
  footer,
  children,
}: {
  title: string
  footer?: React.ReactNode
  children: React.ReactNode
}) {
  return (
    <section className="space-y-2">
      <h2 className="section-title px-1">{title}</h2>
      <div className="card space-y-3">{children}</div>
      {footer && <p className="section-footer">{footer}</p>}
    </section>
  )
}

function SecretField({
  label,
  value,
  onChange,
  placeholder,
}: {
  label: string
  value: string
  onChange: (value: string) => void
  placeholder?: string
}) {
  const [visible, setVisible] = useState(false)
  return (
    <label className="block space-y-1.5">
      <span className="section-title">{label}</span>
      <span className="flex gap-2">
        <input
          className="input"
          type={visible ? 'text' : 'password'}
          value={value}
          placeholder={placeholder}
          autoComplete="off"
          onChange={(event) => onChange(event.target.value)}
        />
        <button
          type="button"
          className="btn-secondary px-3"
          onClick={() => setVisible((current) => !current)}
          aria-label={visible ? 'Masquer' : 'Afficher'}
        >
          <Icon name={visible ? 'eye-off' : 'eye'} />
        </button>
      </span>
    </label>
  )
}

export default function SettingsPage() {
  const queryClient = useQueryClient()
  const { settings, preferences, updatePreferences, isLoading, refresh } = useSettings()

  const [apiKey, setApiKey] = useState('')
  const [rebrickableUser, setRebrickableUser] = useState({ username: '', password: '' })
  const [bricksetKey, setBricksetKey] = useState('')
  const [bricksetUser, setBricksetUser] = useState({ username: '', password: '' })
  const [bricklink, setBricklink] = useState({
    consumerKey: '',
    consumerSecret: '',
    token: '',
    tokenSecret: '',
  })
  const [confirmClear, setConfirmClear] = useState(false)
  const [pendingDestructive, setPendingDestructive] = useState<
    { title: string; message: string; label: string; run: () => void } | null
  >(null)
  const [feedback, setFeedback] = useState<string | null>(null)

  const catalog = useQuery({
    queryKey: ['catalog-status'],
    queryFn: () => api.get<CatalogStatus>('/catalog/status'),
    refetchInterval: (query) => {
      const data = query.state.data
      const running = data && (['sets', 'themes', 'minifigs'] as CatalogName[]).some(
        (name) => data[name].status?.state === 'running',
      )
      return running ? 2000 : false
    },
  })

  // This device's own IndexedDB copy of the sets/minifigs catalogue — what lets identification
  // work with zero backend round trip while scanning offline. Distinct from `catalog.data` above,
  // which is the *server's* download state.
  const [localCatalog, setLocalCatalog] = useState<
    Partial<Record<OfflineCatalogName, { exportedAt: string; rowCount: number } | null>>
  >({})
  const [catalogSyncing, setCatalogSyncing] = useState<Partial<Record<OfflineCatalogName, boolean>>>({})
  const previousDownloadedAt = useRef<Partial<Record<OfflineCatalogName, string | null | undefined>>>({})

  async function refreshLocalCatalog(name: OfflineCatalogName) {
    const meta = await offlineCatalogStore.meta(name)
    setLocalCatalog((current) => ({ ...current, [name]: meta ?? null }))
  }

  useEffect(() => {
    void refreshLocalCatalog('sets')
    void refreshLocalCatalog('minifigs')
  }, [])

  async function syncCatalogToDevice(name: OfflineCatalogName) {
    setCatalogSyncing((current) => ({ ...current, [name]: true }))
    try {
      await offlineCatalogStore.pull(name)
      await refreshLocalCatalog(name)
      setFeedback('Catalogue synchronisé sur cet appareil.')
    } catch (error) {
      setFeedback(error instanceof Error ? error.message : 'Synchronisation impossible')
    } finally {
      setCatalogSyncing((current) => ({ ...current, [name]: false }))
    }
  }

  // Auto-pull the moment a backend download finishes, so "télécharger le catalogue" is one action
  // that transparently also lands a local copy — no separate step for the common path. Keyed on
  // `downloadedAt` *changing* from what was last observed, not on catching a transient `'running'`
  // poll: a fast/local download can complete well within the 2s polling interval, so the status
  // query's very first post-download read may already show `state: null` with `downloadedAt` set —
  // a transition-based check would silently never fire. The first observation only seeds the ref
  // (no pull), so a catalogue downloaded in a previous session doesn't trigger a redundant pull on
  // every mount; every later change fires one.
  useEffect(() => {
    for (const name of ['sets', 'minifigs'] as const) {
      const entry = catalog.data?.[name]
      const downloadedAt = entry?.downloadedAt ?? null
      const previous = previousDownloadedAt.current[name]
      if (previous !== undefined && previous !== downloadedAt && downloadedAt) {
        void syncCatalogToDevice(name)
      }
      previousDownloadedAt.current[name] = downloadedAt
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- syncCatalogToDevice is stable enough here; keyed on catalog.data
  }, [catalog.data])

  async function purgeCatalogEverywhere(name: OfflineCatalogName) {
    await api.delete(`/catalog/${name}`)
    await offlineCatalogStore.purge(name)
    await refreshLocalCatalog(name)
  }

  const batch = useQuery({
    queryKey: ['priceBatch'],
    queryFn: () => api.get<BatchStatus>('/prices/batch/status'),
    refetchInterval: (query) => (query.state.data?.isRunning ? 2000 : false),
  })

  function run<T>(action: () => Promise<T>, message: string) {
    return async () => {
      try {
        await action()
        setFeedback(message)
        await refresh()
        await queryClient.invalidateQueries()
      } catch (error) {
        setFeedback(error instanceof Error ? error.message : 'Action impossible')
      }
    }
  }

  const clearCache = useMutation({
    mutationFn: () => api.post('/settings/clear-cache'),
    onSuccess: async () => {
      setConfirmClear(false)
      setFeedback('Cache vidé.')
      await queryClient.invalidateQueries()
    },
  })

  if (isLoading || !settings || !preferences) return <LoadingBlock />

  const credentials = settings.credentials
  const brandColor = preferences['appTheme.brandColor'] as BrandColor
  const appearance = preferences['appTheme.appearanceMode'] as AppearanceMode

  return (
    <div className="space-y-6 pb-8">
      <NavBar title="Paramètres" backLabel="Fermer" />
      <h1 className="text-[34px] font-bold leading-tight text-ink">Paramètres</h1>
      {feedback && <p className="text-sm text-brand">{feedback}</p>}

      <Section
        title="Thème"
        footer="Choisissez la couleur de marque et l'apparence claire/sombre de l'application."
      >
        <div className="flex gap-4 pb-1">
          {(Object.keys(BRAND_COLORS) as BrandColor[]).map((color) => (
            <button
              key={color}
              type="button"
              className={`h-12 w-12 rounded-full transition-transform active:scale-95 ${
                brandColor === color ? 'ring-2 ring-ink ring-offset-2 ring-offset-[rgb(var(--surface-raised))]' : ''
              }`}
              style={{ backgroundColor: BRAND_COLORS[color].hex }}
              onClick={() => void updatePreferences({ 'appTheme.brandColor': color })}
              aria-label={BRAND_COLORS[color].label}
              aria-pressed={brandColor === color}
            />
          ))}
        </div>
        <div className="border-t border-line pt-3">
          <div className="segmented">
            {(Object.keys(APPEARANCE_LABELS) as AppearanceMode[]).map((mode) => (
              <button
                key={mode}
                type="button"
                className={`segmented-option ${appearance === mode ? 'segmented-option-active' : ''}`}
                onClick={() => void updatePreferences({ 'appTheme.appearanceMode': mode })}
                aria-pressed={appearance === mode}
              >
                {APPEARANCE_LABELS[mode]}
              </button>
            ))}
          </div>
        </div>
      </Section>

      <Section
        title="Valeur cible"
        footer="Seuil de €/pièce en dessous duquel un set est considéré comme un bon rapport qualité-prix. Affiché en vert sur la fiche set si le prix est inférieur à cette valeur, en rouge au-dessus."
      >
        <label className="flex items-center gap-3">
          <span className="flex-1 text-[17px] text-ink">Cible €/pièce</span>
          <input
            className="w-24 bg-transparent text-right text-[17px] text-ink focus:outline-none"
            type="number"
            step="0.01"
            min="0"
            defaultValue={String(preferences['appTheme.preferredPricePerPart'] ?? 0.12)}
            onBlur={(event) =>
              void updatePreferences({ 'appTheme.preferredPricePerPart': Number(event.target.value) })
            }
          />
          <span className="text-[17px] text-ink-faint">€</span>
        </label>
      </Section>

      <Section title="Compte Rebrickable">
        <div className="flex flex-wrap gap-2">
          <Badge tone={credentials.rebrickableApiKey ? 'positive' : 'warning'}>
            {credentials.rebrickableApiKey ? 'Clé API configurée' : 'Clé API manquante'}
          </Badge>
          <Badge tone={credentials.rebrickableLinked ? 'positive' : 'neutral'}>
            {credentials.rebrickableLinked ? 'Compte lié' : 'Compte non lié'}
          </Badge>
        </div>
        <SecretField label="Clé API" value={apiKey} onChange={setApiKey} placeholder="rebrickable.com/profile" />
        <div className="flex gap-2">
          <button
            type="button"
            className="btn-secondary flex-1"
            disabled={!apiKey}
            onClick={run(async () => {
              await api.put('/settings/credentials/rebrickable-key', { apiKey })
              setApiKey('')
            }, 'Clé API enregistrée.')}
          >
            Enregistrer la clé
          </button>
          {credentials.rebrickableApiKey && (
            <button
              type="button"
              className="btn-ghost"
              onClick={() =>
                setPendingDestructive({
                  title: 'Supprimer la clé API Rebrickable ?',
                  message: "L'identification des sets et la synchronisation cesseront de fonctionner.",
                  label: 'Supprimer',
                  run: run(() => api.delete('/settings/credentials/rebrickable-key'), 'Clé supprimée.'),
                })
              }
            >
              Effacer
            </button>
          )}
        </div>

        <div className="space-y-2 border-t border-line pt-3">
          <p className="text-xs text-ink-faint">
            Lier votre compte permet de synchroniser votre collection. Votre mot de passe sert une
            seule fois à obtenir un jeton et n'est jamais enregistré.
          </p>
          <input
            className="input"
            placeholder="Nom d'utilisateur"
            autoComplete="username"
            value={rebrickableUser.username}
            onChange={(event) => setRebrickableUser({ ...rebrickableUser, username: event.target.value })}
          />
          <input
            className="input"
            type="password"
            placeholder="Mot de passe"
            autoComplete="current-password"
            value={rebrickableUser.password}
            onChange={(event) => setRebrickableUser({ ...rebrickableUser, password: event.target.value })}
          />
          <div className="flex gap-2">
            <button
              type="button"
              className="btn-primary flex-1"
              disabled={!rebrickableUser.username || !rebrickableUser.password}
              onClick={run(async () => {
                await api.post('/settings/link/rebrickable', { ...rebrickableUser, apiKey: apiKey || null })
                setRebrickableUser({ username: '', password: '' })
              }, 'Compte Rebrickable lié.')}
            >
              Lier mon compte
            </button>
            {credentials.rebrickableLinked && (
              <button
                type="button"
                className="btn-secondary"
                onClick={() =>
                  setPendingDestructive({
                    title: 'Délier le compte Rebrickable ?',
                    message:
                      'La synchronisation de la collection sera interrompue. Votre clé API est conservée.',
                    label: 'Délier',
                    run: run(() => api.post('/settings/unlink/rebrickable'), 'Compte délié.'),
                  })
                }
              >
                Délier
              </button>
            )}
          </div>
        </div>
      </Section>

      <Section title="Compte Brickset">
        <div className="flex flex-wrap gap-2">
          <Badge tone={credentials.bricksetApiKey ? 'positive' : 'neutral'}>
            {credentials.bricksetApiKey ? 'Clé API configurée' : 'Clé API manquante'}
          </Badge>
          <Badge tone={credentials.bricksetLinked ? 'positive' : 'neutral'}>
            {credentials.bricksetLinked ? 'Compte lié' : 'Compte non lié'}
          </Badge>
        </div>
        <p className="text-xs text-ink-faint">
          Compte séparé de Rebrickable : la liste cadeaux est stockée sur Brickset. Sans lui, l'écran
          « Liste cadeaux » reste simplement vide.
        </p>
        <SecretField label="Clé API Brickset" value={bricksetKey} onChange={setBricksetKey} />
        <div className="flex gap-2">
          <button
            type="button"
            className="btn-secondary flex-1"
            disabled={!bricksetKey}
            onClick={run(async () => {
              await api.put('/settings/credentials/brickset-key', { apiKey: bricksetKey })
              setBricksetKey('')
            }, 'Clé Brickset enregistrée.')}
          >
            Enregistrer la clé
          </button>
          {credentials.bricksetApiKey && (
            <button
              type="button"
              className="btn-ghost"
              onClick={() =>
                setPendingDestructive({
                  title: 'Supprimer la clé API Brickset ?',
                  message: 'La liste cadeaux ne sera plus accessible tant qu\'une clé n\'est pas ressaisie.',
                  label: 'Supprimer',
                  run: run(() => api.delete('/settings/credentials/brickset-key'), 'Clé supprimée.'),
                })
              }
            >
              Effacer
            </button>
          )}
        </div>
        <input
          className="input"
          placeholder="Nom d'utilisateur"
          value={bricksetUser.username}
          onChange={(event) => setBricksetUser({ ...bricksetUser, username: event.target.value })}
        />
        <input
          className="input"
          type="password"
          placeholder="Mot de passe"
          value={bricksetUser.password}
          onChange={(event) => setBricksetUser({ ...bricksetUser, password: event.target.value })}
        />
        <div className="flex gap-2">
          <button
            type="button"
            className="btn-primary flex-1"
            disabled={!bricksetUser.username || !bricksetUser.password}
            onClick={run(async () => {
              await api.post('/settings/link/brickset', { ...bricksetUser, apiKey: bricksetKey || null })
              setBricksetUser({ username: '', password: '' })
            }, 'Compte Brickset lié.')}
          >
            Lier mon compte
          </button>
          {credentials.bricksetLinked && (
            <button
              type="button"
              className="btn-secondary"
              onClick={() =>
                setPendingDestructive({
                  title: 'Délier le compte Brickset ?',
                  message: 'La liste cadeaux ne sera plus synchronisée. Votre clé API est conservée.',
                  label: 'Délier',
                  run: run(() => api.post('/settings/unlink/brickset'), 'Compte Brickset délié.'),
                })
              }
            >
              Délier
            </button>
          )}
        </div>
      </Section>

      <Section title="Compte BrickLink">
        <Badge tone={credentials.bricklink ? 'positive' : 'neutral'}>
          {credentials.bricklink ? 'Identifiants configurés' : 'Non configuré'}
        </Badge>
        <p className="text-xs text-ink-faint">
          Générez les 4 valeurs OAuth sur{' '}
          <a
            className="underline"
            href="https://www.bricklink.com/v3/api.page"
            target="_blank"
            rel="noreferrer noopener"
          >
            bricklink.com/v3/api.page
          </a>
          . Sans elles, les lignes BrickLink sont simplement omises.
        </p>
        <SecretField
          label="Consumer Key"
          value={bricklink.consumerKey}
          onChange={(value) => setBricklink({ ...bricklink, consumerKey: value })}
        />
        <SecretField
          label="Consumer Secret"
          value={bricklink.consumerSecret}
          onChange={(value) => setBricklink({ ...bricklink, consumerSecret: value })}
        />
        <SecretField
          label="Token"
          value={bricklink.token}
          onChange={(value) => setBricklink({ ...bricklink, token: value })}
        />
        <SecretField
          label="Token Secret"
          value={bricklink.tokenSecret}
          onChange={(value) => setBricklink({ ...bricklink, tokenSecret: value })}
        />
        <div className="flex gap-2">
          <button
            type="button"
            className="btn-primary flex-1"
            disabled={!Object.values(bricklink).every(Boolean)}
            onClick={run(async () => {
              await api.put('/settings/credentials/bricklink', bricklink)
              setBricklink({ consumerKey: '', consumerSecret: '', token: '', tokenSecret: '' })
            }, 'Identifiants BrickLink enregistrés.')}
          >
            Enregistrer
          </button>
          {credentials.bricklink && (
            <button
              type="button"
              className="btn-secondary"
              onClick={() =>
                setPendingDestructive({
                  title: 'Supprimer les identifiants BrickLink ?',
                  message: 'Les prix BrickLink ne seront plus récupérés tant qu\'ils ne sont pas ressaisis.',
                  label: 'Supprimer',
                  run: run(
                    () => api.delete('/settings/credentials/bricklink'),
                    'Identifiants supprimés.',
                  ),
                })
              }
            >
              Supprimer
            </button>
          )}
        </div>
      </Section>

      <Section
        title="Catalogue hors-ligne"
        footer="Une fois synchronisé sur cet appareil, le catalogue permet d'identifier un set ou une minifig par son numéro sans connexion — utile pour scanner hors-ligne."
      >
        {(['sets', 'minifigs'] as OfflineCatalogName[]).map((name) => {
          const entry = catalog.data?.[name]
          const running = entry?.status?.state === 'running'
          const local = localCatalog[name]
          const syncing = Boolean(catalogSyncing[name])
          return (
            <div key={name} className="space-y-1.5 border-b border-line pb-3 last:border-0 last:pb-0">
              <div className="flex items-center justify-between gap-2">
                <span className="text-sm font-semibold text-ink">
                  {name === 'sets' ? 'Sets' : 'Minifigs'}
                </span>
                <span className="text-xs text-ink-faint">
                  {entry?.rowCount ? `${entry.rowCount.toLocaleString('fr-FR')} entrées` : 'Non téléchargé'}
                  {entry?.downloadedAt ? ` · ${formatDateTime(entry.downloadedAt)}` : ''}
                </span>
              </div>
              {running && (
                <div className="space-y-1">
                  <div className="h-1.5 overflow-hidden rounded-full bg-line">
                    <div
                      className="h-full bg-brand transition-all"
                      style={{ width: `${Math.round((entry?.status?.progress ?? 0) * 100)}%` }}
                    />
                  </div>
                  <p className="text-xs text-ink-faint">{entry?.status?.message ?? 'Téléchargement…'}</p>
                </div>
              )}
              {entry?.status?.state === 'error' && (
                <ErrorLabel message={entry.status.message ?? 'Téléchargement échoué'} />
              )}
              <div className="flex gap-2">
                <button
                  type="button"
                  className="btn-secondary flex-1 text-xs"
                  disabled={running}
                  onClick={run(
                    () => api.post(`/catalog/${name}/download`),
                    'Téléchargement lancé.',
                  )}
                >
                  {running ? <Spinner className="h-4 w-4" /> : entry?.rowCount ? 'Mettre à jour' : 'Télécharger'}
                </button>
                {(entry?.rowCount ?? 0) > 0 && (
                  <button
                    type="button"
                    className="btn-ghost text-xs"
                    onClick={run(() => purgeCatalogEverywhere(name), 'Catalogue supprimé.')}
                  >
                    Purger
                  </button>
                )}
              </div>
              {/* Distinct from the block above: that's the server's own download from Rebrickable,
                  this is whether *this browser* has pulled a copy into IndexedDB yet. */}
              {(entry?.rowCount ?? 0) > 0 && (
                <div className="flex items-center justify-between gap-2 pt-0.5">
                  <span className="text-[11px] text-ink-faint">
                    Sur cet appareil :{' '}
                    {local?.rowCount
                      ? `${local.rowCount.toLocaleString('fr-FR')} entrées · ${formatDateTime(local.exportedAt)}`
                      : 'pas encore synchronisé'}
                  </span>
                  <button
                    type="button"
                    className="btn-ghost px-2 py-0.5 text-[11px]"
                    disabled={syncing}
                    onClick={() => void syncCatalogToDevice(name)}
                  >
                    {syncing ? <Spinner className="h-3.5 w-3.5" /> : 'Resynchroniser sur cet appareil'}
                  </button>
                </div>
              )}
            </div>
          )
        })}
      </Section>

      <Section title="Prix de la collection">
        <p className="text-xs text-ink-faint">
          La mise à jour traite les sets un par un, avec une pause entre chacun. C'est lent
          volontairement : enchaîner des dizaines de navigateurs en parallèle sur les mêmes sites
          ferait passer votre IP pour du trafic abusif.
        </p>
        {batch.data?.isRunning ? (
          <div className="space-y-2">
            <div className="flex items-center gap-2 text-sm">
              <Spinner className="h-4 w-4" />
              <span>
                {batch.data.done} / {batch.data.total}
                {batch.data.currentSetNum ? ` · ${batch.data.currentSetNum}` : ''}
              </span>
            </div>
            <div className="h-1.5 overflow-hidden rounded-full bg-line">
              <div
                className="h-full bg-brand transition-all"
                style={{
                  width: `${batch.data.total ? (batch.data.done / batch.data.total) * 100 : 0}%`,
                }}
              />
            </div>
            <button
              type="button"
              className="btn-secondary w-full"
              onClick={run(() => api.post('/prices/batch/cancel'), 'Mise à jour interrompue.')}
            >
              Interrompre (la progression est conservée)
            </button>
          </div>
        ) : (
          <div className="space-y-2">
            {batch.data?.lastCompletedAt && (
              <p className="text-xs text-ink-faint">
                Dernière mise à jour complète : {formatDateTime(batch.data.lastCompletedAt)}
              </p>
            )}
            <button
              type="button"
              className="btn-secondary w-full"
              onClick={run(() => api.post('/prices/batch/start', {}), 'Mise à jour lancée.')}
            >
              Mettre à jour tous les prix
            </button>
            <button
              type="button"
              className="btn-ghost w-full text-xs"
              onClick={run(
                () => api.post('/prices/batch/start', { onlyMissing: true }),
                'Complément lancé.',
              )}
            >
              Compléter uniquement les prix manquants
            </button>
          </div>
        )}
      </Section>

      <Section title="Alertes et notifications">
        <Link to="/alerts" className="btn-secondary w-full">
          Gérer mes alertes de prix
        </Link>
        <label className="flex items-center justify-between gap-3">
          <span className="text-sm text-ink">Rafraîchissement en arrière-plan</span>
          <Toggle
            checked={Boolean(preferences['backgroundRefresh.enabled'])}
            onChange={(checked) => void updatePreferences({ 'backgroundRefresh.enabled': checked })}
          />
        </label>
        <PushToggle />
      </Section>

      <Section title="Découverte">
        <label className="flex items-start justify-between gap-3">
          <span className="text-sm text-ink">
            Masquer les non-sets
            <span className="block text-xs text-ink-faint">
              Produits dérivés, livres et exclusivités internes sont masqués des écrans qui
              *suggèrent* des sets. Rien de ce que vous possédez ne disparaît.
            </span>
          </span>
          <Toggle
            checked={Boolean(preferences.hide_wearables_enabled)}
            onChange={(checked) => void updatePreferences({ hide_wearables_enabled: checked })}
          />
        </label>
      </Section>

      <Section title="Localisation des scans">
        <label className="flex items-start justify-between gap-3">
          <span className="text-sm text-ink">
            Enregistrer où j'ai scanné
            <span className="block text-xs text-ink-faint">
              Désactivé par défaut. La position n'est enregistrée que pour les sets absents de ta
              collection, et elle est effacée dès que vous ajoutez le set — son seul intérêt est
              « dans quel magasin l'ai-je vu ».
            </span>
          </span>
          <Toggle
            checked={Boolean(preferences.scan_location_enabled)}
            onChange={(checked) => void updatePreferences({ scan_location_enabled: checked })}
          />
        </label>
      </Section>

      <Section title="Données">
        <button type="button" className="btn-danger w-full" onClick={() => setConfirmClear(true)}>
          Vider le cache
        </button>
        <p className="text-xs text-ink-faint">
          Supprime les sets en cache, les listes, les prix courants et les ventes BrickLink.
          <strong className="text-ink"> Conserve</strong> vos scans, vos prix payés, vos alertes,
          l'historique des prix et la valeur quotidienne de votre collection — rien de tout cela ne se
          re-télécharge.
        </p>
      </Section>

      <Section title="Confidentialité">
        <ul className="space-y-1.5 text-xs text-ink-muted">
          <li>• Vos identifiants tiers sont chiffrés dans la base : le fichier seul ne suffit pas à les lire.</li>
          <li>• Vos mots de passe Rebrickable et Brickset ne sont jamais enregistrés.</li>
          <li>• Aucune analytique, aucun envoi vers un service que vous n'avez pas configuré.</li>
          <li>• Tout reste dans votre conteneur, sur votre machine.</li>
        </ul>
      </Section>

      <ConfirmDialog
        open={pendingDestructive !== null}
        title={pendingDestructive?.title ?? ''}
        message={pendingDestructive?.message}
        confirmLabel={pendingDestructive?.label}
        destructive
        onConfirm={() => {
          pendingDestructive?.run()
          setPendingDestructive(null)
        }}
        onCancel={() => setPendingDestructive(null)}
      />

      <ConfirmDialog
        open={confirmClear}
        title="Vider le cache"
        message="Les sets en cache, listes, prix courants et ventes BrickLink seront supprimés. Vos scans, prix payés, alertes et historiques sont conservés."
        confirmLabel="Vider"
        destructive
        onConfirm={() => clearCache.mutate()}
        onCancel={() => setConfirmClear(false)}
      />
    </div>
  )
}
