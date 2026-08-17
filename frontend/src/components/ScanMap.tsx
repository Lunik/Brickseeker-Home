import { useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { MapContainer, Marker, Popup, TileLayer } from 'react-leaflet'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'

import { api } from '../api/client'
import { formatDateTime, formatEUR } from '../lib/format'
import Icon from './Icon'
import { EmptyState, LoadingBlock } from './ui'

interface MapPoint {
  id: number
  setNum: string
  setName: string
  scannedAt: string
  latitude: number
  longitude: number
  placeName: string | null
  priceSeenEur: number | null
}

// Leaflet's default marker icons are resolved relative to the CSS, which Vite's bundling breaks.
// An inline SVG divIcon avoids the broken-image markers entirely and needs no asset pipeline.
const markerIcon = L.divIcon({
  className: '',
  html: '<div style="width:18px;height:18px;border-radius:50%;background:rgb(227,0,11);border:3px solid white;box-shadow:0 1px 4px rgba(0,0,0,.4)"></div>',
  iconSize: [18, 18],
  iconAnchor: [9, 9],
})

export default function ScanMap() {
  const navigate = useNavigate()
  const { data, isLoading, error } = useQuery({
    queryKey: ['scan-map'],
    queryFn: () => api.get<{ points: MapPoint[] }>('/history/map'),
  })

  function openSet(setNum: string) {
    navigate(`/set/${encodeURIComponent(setNum)}`)
  }

  if (isLoading) return <LoadingBlock />
  if (error) return <EmptyState icon={<Icon name="warning" className="h-9 w-9" />} title="Carte indisponible" message={(error as Error).message} />

  const points = data?.points ?? []
  if (!points.length) {
    return (
      <EmptyState
        icon={<Icon name="map" className="h-9 w-9" />}
        title="Aucun scan localisé"
        message="Activez la localisation des scans dans les Paramètres. La position n'est enregistrée que pour les sets absents de votre collection, et elle est effacée dès que vous les ajoutez."
        action={
          <button type="button" className="btn-primary" onClick={() => navigate('/settings')}>
            Ouvrir les Paramètres
          </button>
        }
      />
    )
  }

  const center: [number, number] = [points[0].latitude, points[0].longitude]

  return (
    <div className="space-y-3">
      <div className="h-80 overflow-hidden rounded-card border border-line">
        <MapContainer center={center} zoom={11} scrollWheelZoom className="h-full w-full">
          <TileLayer
            attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
            url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
          />
          {points.map((point) => (
            <Marker key={point.id} position={[point.latitude, point.longitude]} icon={markerIcon}>
              <Popup>
                <strong>{point.setNum}</strong>
                <br />
                {point.setName}
                <br />
                {formatDateTime(point.scannedAt)}
                {point.placeName && (
                  <>
                    <br />
                    {point.placeName}
                  </>
                )}
                {point.priceSeenEur !== null && (
                  <>
                    <br />
                    Vu à {formatEUR(point.priceSeenEur)}
                  </>
                )}
                <br />
                <button type="button" className="text-brand underline" onClick={() => openSet(point.setNum)}>
                  Voir le set
                </button>
              </Popup>
            </Marker>
          ))}
        </MapContainer>
      </div>

      {/* The same data as a list: if the tile host is blocked, the page still says something. */}
      <ul className="divide-y divide-line">
        {points.map((point) => (
          <li key={point.id}>
            <button
              type="button"
              className="w-full py-2 text-left text-sm active:opacity-60"
              onClick={() => openSet(point.setNum)}
            >
              <span className="font-semibold text-ink">{point.setNum}</span>{' '}
              <span className="text-ink-muted">{point.setName}</span>
              <span className="block text-xs text-ink-faint">
                {formatDateTime(point.scannedAt)}
                {point.placeName ? ` · ${point.placeName}` : ''}
                {point.priceSeenEur !== null ? ` · vu à ${formatEUR(point.priceSeenEur)}` : ''}
              </span>
            </button>
          </li>
        ))}
      </ul>
    </div>
  )
}
