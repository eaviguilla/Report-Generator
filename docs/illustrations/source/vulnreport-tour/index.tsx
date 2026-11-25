import { Stage } from '../../kit'
import { FINDINGS } from '../vulnreport-shared/data'
import { ContentPage, FindingsPage, SetupPage } from '../vulnreport-shared/pages'
import { AppWindow } from '../vulnreport-shared/parts'
import './tour.css'

// The whole flow in one picture: Setup, Findings and Content side by side at one height and top,
// as in examples/window-row. The Findings window leads and is the only one with words. The other
// two are the same pages drawn as bars, cut by the stage on the outer side.
export default function Tour() {
  return (
    <Stage width={800} height={480} className="vr vt">
      {() => (
        <>
          <AppWindow step={1} ghost className="vt-win vt-win--left">
            <SetupPage />
          </AppWindow>
          <AppWindow step={2} url="localhost:8765" className="vt-win vt-win--lead">
            <FindingsPage rows={FINDINGS.slice(0, 5)} ghostRows={1} />
          </AppWindow>
          <AppWindow step={3} ghost flush className="vt-win vt-win--right">
            <ContentPage />
          </AppWindow>
        </>
      )}
    </Stage>
  )
}
