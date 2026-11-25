// Invented content for every scene. The client, the API, the targets and the findings are fictional;
// the severities, statuses, report types and app types are the product's own labels.

export type Severity = 'critical' | 'high' | 'medium' | 'low' | 'informational'

export const SEVERITY_LABEL: Record<Severity, string> = {
  critical: 'Critical',
  high: 'High',
  medium: 'Medium',
  low: 'Low',
  informational: 'Informational',
}

export const ENGAGEMENT = {
  name: 'Marlow Member API',
  reportType: 'Annual Pentest',
  ci: 'CI-204817',
  tester: 'Sam Ortega',
  reportDate: '11/20/2026',
  start: '10/12/2026',
  end: '10/23/2026',
  saved: 'Saved 14:06',
}

export const WEB_TARGETS = ['https://portal.marlow-cu.example', 'https://login.marlow-cu.example']
export const API_TARGETS = ['https://api.marlow-cu.example/v2']

export type Finding = {
  name: string
  severity: Severity
  likelihood: string
  impact: string
  status: string
}

export const FINDINGS: Finding[] = [
  { name: 'Broken Object Authorization', severity: 'critical', likelihood: 'High', impact: 'Critical', status: 'Open (New)' },
  { name: 'Missing Rate Limit on Login', severity: 'high', likelihood: 'High', impact: 'Medium', status: 'Open (New)' },
  { name: 'Token Valid After Logout', severity: 'medium', likelihood: 'Medium', impact: 'Medium', status: 'Open (New)' },
  { name: 'Verbose Error Messages', severity: 'low', likelihood: 'Medium', impact: 'Low', status: 'Resolved' },
  { name: 'Server Version Disclosed', severity: 'informational', likelihood: 'Low', impact: 'Low', status: 'Open (New)' },
  { name: 'Weak TLS Configuration', severity: 'medium', likelihood: 'Low', impact: 'High', status: 'Open (New)' },
]

export const CONTENT = {
  title: 'Broken Object Authorization',
  description:
    "The loan lookup endpoint returns a member's loan record when the ID in the path belongs to someone else. The API checks that the token is valid, but not that the loan belongs to the member who sent it.",
  remediation:
    'Check on the server that the loan belongs to the signed-in member before returning it. Answer with 404 for any other loan, so the response does not confirm that it exists.',
  steps: [
    'Sign in as member A.',
    'Request /v2/loans/1042, a loan of member B.',
    'The API returns that loan with status 200.',
  ],
  caption: "Member A reads B's loan",
}
