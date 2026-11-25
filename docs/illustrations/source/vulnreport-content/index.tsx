import { ChevronDown, ChevronUp, Folder, Trash2 } from 'lucide-react'
import { Bar, Code, Stage } from '../../kit'
import { CONTENT, ENGAGEMENT } from '../vulnreport-shared/data'
import { Block, ContentPage, Fragmentish } from '../vulnreport-shared/pages'
import { AppWindow, Ico, T } from '../vulnreport-shared/parts'
import './content.css'

// The screenshot slot of a finished finding: its number and move arrows, the image, then the
// caption and the environment.
function Evidence() {
  return (
    <div className="vc-ev">
      <div className="vc-ev__spine">
        <Ico icon={ChevronUp} size={11} stroke={1.8} />
        <b>1</b>
        <Ico icon={ChevronDown} size={11} stroke={1.8} />
      </div>
      <div className="vc-ev__thumb">
        <div className="vc-shot">
          <Code numbers={false} lines={['GET /v2/loans/1042', '200 OK', '{"loan_id": 1042,', ' "member": "B-5518"}']} />
        </div>
      </div>
      <div className="vc-ev__meta">
        <span className="vc-ev__caption">{CONTENT.caption}</span>
        <span className="vc-ev__facts">
          <span className="vc-ev__env">
            <T fs={11}>Production</T>
            <Ico icon={ChevronDown} size={12} />
          </span>
          <span className="vc-ev__acts">
            <Ico icon={Folder} size={13} />
            <Ico icon={Trash2} size={13} />
          </span>
        </span>
      </div>
    </div>
  )
}

// The Word output as a ruled page: the finding's title and a table, then the sections and a figure.
function WordPage() {
  return (
    <div className="vc-doc">
      <span className="vc-doc__sev">Critical</span>
      <div className="vc-doc__title">{CONTENT.title}</div>
      <div className="vc-doc__table">
        {[34, 28, 40, 30].map((w, i) => (
          <div key={i} className="vc-doc__cell">
            <Bar w={w} h={4} r={2} tone={3} />
            <Bar w={w - 12} h={4} r={2} tone={2} />
          </div>
        ))}
      </div>
      {['Description', 'Recommended Remediation', 'Proof of Concept'].map((heading, i) => (
        <div key={heading} className="vc-doc__sec">
          <Bar w={[54, 92, 70][i]} h={5} r={2.5} tone={5} />
          <Bar w="100%" h={4} r={2} tone={2} />
          <Bar w="92%" h={4} r={2} tone={2} />
          {i === 2 && <span className="vc-doc__fig" />}
        </div>
      ))}
    </div>
  )
}

// Step three: the writing. One window on a 28px gutter at the top and right that runs off the
// bottom, with the Word page as a satellite across its left edge, over the finding list
// (examples/static-card). Description and Remediation are closed, as the product lets you close
// them, so the numbered steps and the screenshot stay whole. The list and the page are bars.
export default function ContentStep() {
  return (
    <Stage width={800} height={576} className="vr vc">
      {() => (
        <>
          <AppWindow step={3} wide flush url="localhost:8765/reports/r_4c1d9a07e3b2/edit" chips={[ENGAGEMENT.reportType]} tools className="vc-win">
            <ContentPage wide quiet>
              <div className="vr-pair">
                <Block title="Description" meta="1 fragment" collapsed />
                <Block title="Recommended Remediation" meta="1 fragment" collapsed />
              </div>
              <Block title="Proof of Concept" meta="2 fragments">
                <Fragmentish kind="numbered list">
                  <ol className="vc-steps">
                    {CONTENT.steps.map((step) => (
                      <li key={step}>{step}</li>
                    ))}
                  </ol>
                </Fragmentish>
                <Fragmentish kind="evidence">
                  <Evidence />
                </Fragmentish>
              </Block>
            </ContentPage>
          </AppWindow>
          <WordPage />
        </>
      )}
    </Stage>
  )
}
