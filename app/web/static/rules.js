// Page-free report rules returning {kind, code, ...context}; twins in report_service, cases in tests.test_rule_cases.
(() => {
  "use strict";

  const asString = value => typeof value === "string" ? value : "";

  // Twin of report_service.scope_text_targets; paired by raw index before cleaning, as reconcile_targets does.
  const scopeTargets = (report, vocabulary) => {
    const engagement = report?.engagement || {};
    const testedChannels = engagement.tested_channels || [];
    const covered = vocabulary.channels.map(([channel]) => channel).filter(channel => testedChannels.includes(channel));
    const targets = [];
    (engagement.tested_environments || []).forEach(environment => {
      covered.forEach(channel => {
        const raw = report?.scope_text?.[environment]?.[channel];
        const components = (typeof raw === "string" ? raw : asString(raw?.component)).split("\n");
        const descriptions = asString(raw?.description).split("\n");
        const seen = new Set();
        for (let index = 0; index < Math.max(components.length, descriptions.length); index += 1) {
          const component = (components[index] || "").trim();
          if (!component || component.startsWith("#") || seen.has(component)) continue;
          seen.add(component);
          targets.push({environment, app_type:channel, component, description:(descriptions[index] || "").trim()});
        }
      });
    });
    return targets;
  };

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
    const targets = scopeTargets(report, vocabulary);
    environments.forEach(environment => {
      const testWindow = engagement.test_windows?.[environment] || {};
      if (!testWindow.start_date || !testWindow.end_date) issue("missing_test_dates", {environment});
      const named = targets.filter(target => target.environment === environment);
      if (!named.length) issue("missing_scope_target", {environment});
      named.filter(target => vocabulary.component_channels.includes(target.app_type) && !target.description)
        .forEach(({app_type, component}) => issue("missing_component_description", {environment, app_type, component}));
    });
    return results;
  };

  window.vrRules = {setupResults, scopeTargets};
})();
