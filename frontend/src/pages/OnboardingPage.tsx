import { useState } from 'react'
import { useNavigate } from 'react-router-dom'

import Icon, { type IconName } from '../components/Icon'
import { useSettings } from '../lib/settings-context'

const STEPS: { icon: IconName; title: string; body: string }[] = [
  {
    icon: 'camera',
    title: 'Scanne un set',
    body: "Vise le numéro imprimé sur la boîte. Tu peux aussi le taper à la main ou importer une photo — la caméra n'est jamais un passage obligé.",
  },
  {
    icon: 'box',
    title: 'Retrouve ta collection',
    body: "Lie ton compte Rebrickable pour savoir si un set est déjà chez toi, dans quelle liste, et combien tu en as.",
  },
  {
    icon: 'tag',
    title: 'Compare les prix',
    body: "lego.com, BrickLink neuf et occasion, Amazon et Cdiscount côte à côte, avec l'écart face au prix officiel.",
  },
  {
    icon: 'settings',
    title: 'Configure tes accès',
    body: "Une clé API Rebrickable suffit pour commencer. Brickset (liste cadeaux) et BrickLink (cote) sont optionnels et s'ajoutent quand tu veux.",
  },
]

/** Runs once, gated on the same `hasSeenOnboarding` preference the iOS app uses. */
export default function OnboardingPage() {
  const navigate = useNavigate()
  const { updatePreferences } = useSettings()
  const [step, setStep] = useState(0)
  const current = STEPS[step]
  const isLast = step === STEPS.length - 1

  async function finish() {
    await updatePreferences({ hasSeenOnboarding: true })
    navigate('/', { replace: true })
  }

  return (
    <div className="mx-auto flex min-h-[70vh] max-w-md flex-col justify-between gap-8 py-8">
      <div className="space-y-4 text-center">
        <p className="text-2xl font-extrabold">
          Brick<span className="text-brand">Seeker</span>
        </p>
        <div className="card space-y-3 py-10">
          <Icon name={current.icon} className="mx-auto h-12 w-12 text-brand" />
          <h1 className="text-xl font-bold text-ink">{current.title}</h1>
          <p className="text-sm text-ink-muted">{current.body}</p>
        </div>
        <div className="flex justify-center gap-1.5" aria-hidden="true">
          {STEPS.map((item, index) => (
            <span
              key={item.title}
              className={`h-1.5 w-6 rounded-full ${index === step ? 'bg-brand' : 'bg-line'}`}
            />
          ))}
        </div>
      </div>

      <div className="space-y-2">
        <button
          type="button"
          className="btn-primary w-full"
          onClick={() => (isLast ? void finish() : setStep(step + 1))}
        >
          {isLast ? 'Commencer' : 'Suivant'}
        </button>
        <button type="button" className="btn-ghost w-full" onClick={() => void finish()}>
          Passer
        </button>
      </div>
    </div>
  )
}
