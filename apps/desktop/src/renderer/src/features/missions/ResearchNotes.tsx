import type { ResearchClaim, ResearchNotes as Notes } from './types'

const credits = (value: number | null) => (value === null ? 'n/a' : value.toLocaleString(undefined, { maximumFractionDigits: 2 }))

const CHECK: Record<ResearchClaim['status'], { label: string; help: string }> = {
  verified: { label: 'quote found on the page', help: 'The quote is in the page the researcher read.' },
  snippet: { label: 'search snippet only', help: 'The quote is only in a search result’s snippet; the page was not read.' },
  unverified: { label: 'not checked', help: 'No usable quote, or the quote was not found in anything the researcher was shown.' }
}

/** What the researchers found before the PM planned (Advanced research). Everything here was
 * counted by the tools, not reported by the AI. Each claim says whether its quote was found in
 * what the researcher actually read; the text itself is a summary of web pages, so weigh it. */
export function ResearchNotes({ notes }: { notes: Notes }) {
  return (
    <section className="research-notes" aria-label="Research">
      <h3>Research</h3>
      <p className="mission__muted">
        Looked up on the web before planning. These are summaries of web pages written by an AI: a claim marked
        “quote found on the page” is backed by words on a page it read, but that is not proof the claim is true.
        Search cost: {credits(notes.credits)} Tavily credit(s).
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
                  {(finding.claims ?? []).length > 0 && (
                    <ul aria-label="Claims">
                      {(finding.claims ?? []).map((claim) => (
                        <li key={`${claim.url}|${claim.claim}`} data-status={claim.status}>
                          {claim.claim}{' '}
                          <span className="mission__muted" title={CHECK[claim.status].help}>
                            [{CHECK[claim.status].label}]
                          </span>
                          {claim.quote && <q> {claim.quote} </q>}
                          <code>{claim.url}</code>
                        </li>
                      ))}
                    </ul>
                  )}
                  {finding.sources.length > 0 ? (
                    <ul aria-label="Sources">
                      {finding.sources.map((source) => (
                        <li key={source.url}>
                          {source.title || 'Untitled'} <code>{source.url}</code>
                          {source.read === false && <span className="mission__muted"> (not opened, search result only)</span>}
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
