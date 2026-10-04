// Page-free report rules returning {kind, code, ...context}; twins in report_service, cases in tests.test_rule_cases.
(() => {
  "use strict";

  const setupResults = (report, vocabulary) => {
    const engagement = report?.engagement || {};
    const results = [];
    const issue = (code, context = {}) => results.push({kind:"issue", code, ...context});
    if (!(engagement.app_name || "").trim()) issue("missing_app_name");
    if (!engagement.segment) issue("missing_segment");
    if (!engagement.report_type) issue("missing_report_type");
    if (!(engagement.tester || "").trim()) issue("missing_tester");
    const environments = engagement.tested_environments || [];
    if (!environments.length) issue("no_tested_environment");
    const testedChannels = engagement.tested_channels || [];
    const coveredComponents = vocabulary.component_channels.filter(channel => testedChannels.includes(channel));
    if (coveredComponents.length > 1) issue("mobile_and_thick_client", {app_types:coveredComponents});
    environments.forEach(environment => {
      const testWindow = engagement.test_windows?.[environment] || {};
      if (!testWindow.start_date || !testWindow.end_date) issue("missing_test_dates", {environment});
    });
    return results;
  };

  window.vrRules = {setupResults};
})();
