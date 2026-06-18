import { useEffect, useRef, useState } from 'react'
import { api, type HomepageSettings } from '../api'
import { Button, InfoTip } from '../ui'

/**
 * Editor for the published homepage's content fields (masthead, banner, CTA,
 * about, NotebookLM features). Lives in the homepage editor view and persists
 * to the "homepage" settings store. The memoir timeline is NOT edited here —
 * it is derived from the library groups shown in the block editor below.
 */
export function HomepageContentPanel({ onSaved }: { onSaved?: () => void } = {}) {
  const [hp, setHp] = useState<HomepageSettings | null>(null)
  const [hpState, setHpState] = useState('')
  const [open, setOpen] = useState(true)
  const bannerInputs = useRef<(HTMLInputElement | null)[]>([])

  useEffect(() => {
    api.settings().then(
      (s) => {
        const feats = [...s.homepage.notebooklm_features]
        while (feats.length < 4) feats.push('')
        setHp({ ...s.homepage, notebooklm_features: feats.slice(0, 4) })
      },
      () => {},
    )
  }, [])

  const setHpField = <K extends keyof HomepageSettings>(k: K, v: HomepageSettings[K]) =>
    setHp((p) => (p ? { ...p, [k]: v } : p))
  const setSlotField = (i: number, patch: Partial<HomepageSettings['banner_slots'][number]>) =>
    setHp((p) =>
      p ? { ...p, banner_slots: p.banner_slots.map((s, idx) => (idx === i ? { ...s, ...patch } : s)) } : p,
    )
  const setFeature = (i: number, v: string) =>
    setHp((p) =>
      p ? { ...p, notebooklm_features: p.notebooklm_features.map((f, idx) => (idx === i ? v : f)) } : p,
    )

  const saveHomepage = () => {
    if (!hp) return
    setHpState('saving')
    api.saveHomepageSettings(hp).then(
      (r) => {
        setHp((p) => (p ? { ...p, banner_slots: r.homepage.banner_slots } : p))
        setHpState('Saved')
        onSaved?.()
      },
      (e) => setHpState(`Failed: ${e}`),
    )
  }

  const uploadBanner = (i: number, file: File) => {
    setHpState(`Uploading image for slot ${i + 1}…`)
    api.uploadBannerImage(i, file).then(
      ({ image_url, image_asset_id }) => {
        setSlotField(i, { image_url, image_asset_id })
        setHpState('Image uploaded — Save to keep other field changes')
        onSaved?.()
      },
      (e) => setHpState(`Failed: ${e}`),
    )
  }

  if (!hp) return null

  return (
    <div className="homepage-content">
      <div className="homepage-content-head">
        <button
          type="button"
          className="homepage-content-toggle"
          aria-expanded={open}
          onClick={() => setOpen((o) => !o)}
        >
          <i className={`ti ${open ? 'ti-chevron-down' : 'ti-chevron-right'}`} aria-hidden />
          Homepage content
          <InfoTip label="About homepage content">
            The masthead, banner, NotebookLM call-to-action, and closing “about” text of the
            published homepage. The memoir timeline is built from the library groups shown in the
            block editor below — edit group names and order there.
          </InfoTip>
        </button>
        <div className="settings-save-row" style={{ paddingTop: 0 }}>
          <Button variant="primary" onClick={saveHomepage}>Save homepage content</Button>
          {hpState && <span className="settings-state muted">{hpState}</span>}
        </div>
      </div>

      {open && (
        <>
          {/* Subject */}
          <section className="settings-section">
            <div className="settings-section-head">
              <h2>Subject</h2>
              <p>The masthead at the top of the published homepage — name, dates and the opening tagline.</p>
            </div>
            <div className="settings-fields">
              <div className="settings-row">
                <label htmlFor="hp-name">Full name</label>
                <div className="settings-control">
                  <input id="hp-name" value={hp.subject_name}
                    onChange={(e) => setHpField('subject_name', e.target.value)}
                    placeholder="Robert Francis Skitch" />
                </div>
              </div>
              <div className="settings-row">
                <label htmlFor="hp-birth">
                  Birth year{' '}
                  <InfoTip label="About the birth year">Rendered as “b. 1934” under the name. No end date is shown.</InfoTip>
                </label>
                <div className="settings-control">
                  <input id="hp-birth" value={hp.subject_birth}
                    onChange={(e) => setHpField('subject_birth', e.target.value)} placeholder="1934" />
                </div>
              </div>
              <div className="settings-row">
                <label htmlFor="hp-place">Place</label>
                <div className="settings-control">
                  <input id="hp-place" value={hp.subject_place}
                    onChange={(e) => setHpField('subject_place', e.target.value)}
                    placeholder="Collie, Western Australia" />
                </div>
              </div>
              <div className="settings-row settings-row-tall">
                <label htmlFor="hp-tagline">Tagline</label>
                <div className="settings-control">
                  <textarea id="hp-tagline" rows={3} value={hp.tagline}
                    onChange={(e) => setHpField('tagline', e.target.value)} />
                </div>
              </div>
              <div className="settings-row settings-row-tall">
                <label htmlFor="hp-dedication">
                  Dedication{' '}
                  <InfoTip label="About the dedication">Italic line beneath the tagline. Leave blank for none.</InfoTip>
                </label>
                <div className="settings-control">
                  <input id="hp-dedication" value={hp.dedication}
                    onChange={(e) => setHpField('dedication', e.target.value)} />
                </div>
              </div>
            </div>
          </section>

          {/* Illustration banner */}
          <section className="settings-section">
            <div className="settings-section-head">
              <h2>Illustration banner</h2>
              <p>Three fixed cells beneath the masthead. Upload an image per cell, or leave it blank to show the placeholder sketch.</p>
            </div>
            <div className="settings-fields">
              {hp.banner_slots.map((slot, i) => (
                <div className="settings-row settings-row-tall" key={i}>
                  <label>Slot {i + 1}</label>
                  <div className="settings-control">
                    <input value={slot.era} placeholder="Era label (e.g. Army Years)"
                      onChange={(e) => setSlotField(i, { era: e.target.value })} />
                    <input value={slot.caption} placeholder="Caption" style={{ marginTop: 6 }}
                      onChange={(e) => setSlotField(i, { caption: e.target.value })} />
                    <label className="settings-check" style={{ marginTop: 6, display: 'block' }}>
                      <input type="checkbox" checked={slot.notebooklm_adapted}
                        onChange={(e) => setSlotField(i, { notebooklm_adapted: e.target.checked })} />
                      {' '}NotebookLM edition — image adapted
                    </label>
                    <div style={{ marginTop: 8, display: 'flex', alignItems: 'center', gap: 10 }}>
                      {slot.image_url
                        ? <img src={slot.image_url} alt={slot.caption}
                            style={{ height: 48, borderRadius: 4, border: '1px solid var(--color-border-tertiary)' }} />
                        : <span className="settings-hint">No image — placeholder shown</span>}
                      <input ref={(el) => { bannerInputs.current[i] = el }} type="file" accept="image/*"
                        style={{ display: 'none' }}
                        onChange={(e) => { const f = e.target.files?.[0]; if (f) uploadBanner(i, f); e.target.value = '' }} />
                      <Button onClick={() => bannerInputs.current[i]?.click()}>
                        {slot.image_url ? 'Replace image' : 'Upload image'}
                      </Button>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </section>

          {/* NotebookLM CTA */}
          <section className="settings-section">
            <div className="settings-section-head">
              <h2>NotebookLM CTA</h2>
              <p>The call-to-action bar linking to the collection in Google NotebookLM.</p>
            </div>
            <div className="settings-fields">
              <div className="settings-row">
                <label htmlFor="hp-cta-title">Title</label>
                <div className="settings-control">
                  <input id="hp-cta-title" value={hp.notebooklm_cta_title}
                    onChange={(e) => setHpField('notebooklm_cta_title', e.target.value)} />
                </div>
              </div>
              <div className="settings-row settings-row-tall">
                <label htmlFor="hp-cta-sub">Subtitle</label>
                <div className="settings-control">
                  <textarea id="hp-cta-sub" rows={2} value={hp.notebooklm_cta_subtitle}
                    onChange={(e) => setHpField('notebooklm_cta_subtitle', e.target.value)} />
                </div>
              </div>
              <div className="settings-row">
                <label htmlFor="hp-url">
                  NotebookLM URL{' '}
                  <InfoTip label="About the NotebookLM URL">Used by both the CTA bar and the link in the closing section.</InfoTip>
                </label>
                <div className="settings-control">
                  <input id="hp-url" value={hp.notebooklm_url}
                    onChange={(e) => setHpField('notebooklm_url', e.target.value)}
                    placeholder="https://notebooklm.google.com/notebook/…" />
                </div>
              </div>
            </div>
          </section>

          {/* About this archive */}
          <section className="settings-section">
            <div className="settings-section-head">
              <h2>About this archive</h2>
              <p>Left column of the closing section. Separate paragraphs with a blank line.</p>
            </div>
            <div className="settings-fields">
              <div className="settings-row settings-row-tall">
                <label htmlFor="hp-about-archive">Body text</label>
                <div className="settings-control">
                  <textarea id="hp-about-archive" rows={8} value={hp.about_archive}
                    onChange={(e) => setHpField('about_archive', e.target.value)} />
                </div>
              </div>
              <div className="settings-row">
                <label htmlFor="hp-signoff">Signoff</label>
                <div className="settings-control">
                  <input id="hp-signoff" value={hp.signoff}
                    onChange={(e) => setHpField('signoff', e.target.value)} placeholder="— Christopher Skitch" />
                </div>
              </div>
            </div>
          </section>

          {/* Exploring with NotebookLM */}
          <section className="settings-section">
            <div className="settings-section-head">
              <h2>Exploring with NotebookLM</h2>
              <p>Right column of the closing section — intro text and four feature bullets.</p>
            </div>
            <div className="settings-fields">
              <div className="settings-row settings-row-tall">
                <label htmlFor="hp-about-nlm">Intro text</label>
                <div className="settings-control">
                  <textarea id="hp-about-nlm" rows={5} value={hp.about_notebooklm}
                    onChange={(e) => setHpField('about_notebooklm', e.target.value)} />
                </div>
              </div>
              {[0, 1, 2, 3].map((i) => (
                <div className="settings-row" key={i}>
                  <label htmlFor={`hp-feat-${i}`}>Feature {i + 1}</label>
                  <div className="settings-control">
                    <input id={`hp-feat-${i}`} value={hp.notebooklm_features[i] ?? ''}
                      onChange={(e) => setFeature(i, e.target.value)} />
                  </div>
                </div>
              ))}
              <div className="settings-save-row">
                <Button variant="primary" onClick={saveHomepage}>Save homepage content</Button>
                {hpState && <span className="settings-state muted">{hpState}</span>}
              </div>
            </div>
          </section>
        </>
      )}
    </div>
  )
}
