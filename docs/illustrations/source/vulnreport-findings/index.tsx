import { Stage } from '../../kit'
import { ENGAGEMENT, FINDINGS } from '../vulnreport-shared/data'
import { FindingsPage } from '../vulnreport-shared/pages'
import { AppWindow } from '../vulnreport-shared/parts'
import './findings.css'

// Step two: the findings table. One window on a 28px gutter that runs off the bottom
// (examples/static-card). The first finding is open on the targets it affects, which the tester
// ticks from step one. Three real rows and three of bars, so the crop only cuts filler.
export default function FindingsStep() {
  return (
    <Stage width={800} height={592} className="vr vf">
      {() => (
        <AppWindow step={2} wide url="localhost:8765/reports/r_4c1d9a07e3b2/findings" chips={[ENGAGEMENT.reportType, ENGAGEMENT.ci]} tools className="vf-win">
          <FindingsPage wide rows={FINDINGS.slice(0, 3)} expand={0} ghostRows={3} />
        </AppWindow>
      )}
    </Stage>
  )
}
