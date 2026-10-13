import type { ReviewerRole } from '../api/types'

const CHOICES: { role: ReviewerRole; title: string; text: string }[] = [
  {
    role: 'patient',
    title: 'I am a patient',
    text: 'We will go through your document step by step and ask you to confirm what we found.',
  },
  {
    role: 'clinician',
    title: 'I am a clinician',
    text: 'A compact review of all extracted facts next to the source document.',
  },
]

export function RoleScreen({ onChoose }: { onChoose: (role: ReviewerRole) => void }) {
  return (
    <section className="role-screen" aria-labelledby="role-title">
      <h2 id="role-title">Who is using this service?</h2>
      <p className="muted">
        This only chooses how the review is shown and how your approval is recorded. It does not
        verify who you are.
      </p>
      <div className="role-choices">
        {CHOICES.map((choice) => (
          <button
            key={choice.role}
            type="button"
            className="role-choice"
            onClick={() => onChoose(choice.role)}
          >
            <strong>{choice.title}</strong>
            <span>{choice.text}</span>
          </button>
        ))}
      </div>
    </section>
  )
}
