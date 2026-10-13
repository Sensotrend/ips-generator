import type { ReviewerRole } from '../api/types'
import { useT, type TKey } from '../lib/i18n'

const CHOICES: { role: ReviewerRole; title: TKey; text: TKey }[] = [
  {
    role: 'patient',
    title: 'role.patient.choice',
    text: 'role.patient.text',
  },
  {
    role: 'clinician',
    title: 'role.clinician.choice',
    text: 'role.clinician.text',
  },
]

export function RoleScreen({ onChoose }: { onChoose: (role: ReviewerRole) => void }) {
  const { t } = useT()
  return (
    <section className="role-screen" aria-labelledby="role-title">
      <h2 id="role-title">{t('role.title')}</h2>
      <p className="muted">{t('role.explain')}</p>
      <div className="role-choices">
        {CHOICES.map((choice) => (
          <button
            key={choice.role}
            type="button"
            className="role-choice"
            onClick={() => onChoose(choice.role)}
          >
            <strong>{t(choice.title)}</strong>
            <span>{t(choice.text)}</span>
          </button>
        ))}
      </div>
    </section>
  )
}
