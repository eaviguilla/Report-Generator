import { Stage } from '../../kit'
import { ENGAGEMENT } from '../vulnreport-shared/data'
import { SetupPage } from '../vulnreport-shared/pages'
import { AppWindow } from '../vulnreport-shared/parts'
import './setup.css'

// Step one: the engagement. One window on a 28px gutter that runs off the bottom
// (examples/static-card). The page keeps the real order of Application, Test Coverage and Scope;
// Test Accounts and Limitations are left out so the targets stay in view.
export default function SetupStep() {
  return (
    <Stage width={800} height={592} className="vr vs">
      {() => (
        <AppWindow step={1} wide url="localhost:8765/reports/r_4c1d9a07e3b2/setup" chips={[ENGAGEMENT.reportType, ENGAGEMENT.ci]} tools className="vs-win">
          <SetupPage wide />
        </AppWindow>
      )}
    </Stage>
  )
}
