import type { ResearchNotes as Notes } from './types'

const credits = (value: number | null) => (value === null ? 'n/a' : value.toLocaleString(undefined, { maximumFractionDigits: 2 }))

/** What the researchers found before the PM planned (Advanced research). Everything here was
 * counted by the tools, not reported by the AI; the text itself is a summary of web pages and is
 * information to weigh, not fact. */
export function ResearchNotes({ notes }: { notes: Notes }) {
  return (
    <section className="research-notes" aria-label="Research">
      <h3>Research</h3>
      <p className="mission__muted">
        Looked up on the web before planning. These are summaries of web pages written by an AI: check anything
        that matters. Search cost: {credits(notes.credits)} Tavily credit(s).
      </p>
      {notes.findings.length === 0 ? (
        <p className="mission__muted">The PM found nothing it needed to look up.</p>
      ) : (
        <ol>
          {notes.findings.map((finding) => (
            <li key={finding.question}>
              <strong>{finding.question}</strong>
              {finding.error ? (
                <p role="alert" className="mission__error">
                  Not answered: {finding.error}
                </p>
              ) : (
                <>
                  <p>{finding.answer}</p>
                  {finding.sources.length > 0 ? (
                    <ul aria-label="Sources">
                      {finding.sources.map((source) => (
                        <li key={source.url}>
                          {source.title || 'Untitled'} <code>{source.url}</code>
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <p className="mission__muted">No source was read.</p>
                  )}
                  {finding.gaps && <p className="mission__muted">Not found: {finding.gaps}</p>}
                </>
              )}
              <p className="mission__muted">
                {finding.searches} search(es), {finding.pages} page(s) read, {credits(finding.credits)} credit(s)
              </p>
            </li>
          ))}
        </ol>
      )}
    </section>
  )
}
