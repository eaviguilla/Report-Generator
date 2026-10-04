// Page-free report rules returning {kind, code, ...context}; twins in report_service, cases in tests.test_rule_cases.
(() => {
  "use strict";

  const asString = value => typeof value === "string" ? value : "";

  // Python's str.strip(): String.prototype.trim also strips U+FEFF but keeps U+001C-U+001F and U+0085.
  const strip = text => text.replace(/^[\t-\r\x1c-\x20\x85\xa0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]+|[\t-\r\x1c-\x20\x85\xa0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]+$/g, "");

  // Letters and digits by the browser's own Unicode categories, as Setup has always judged them.
  const invalidCharacters = (value, rule) => [...new Set([...value].filter(character => !(
    (rule.letters && /\p{L}/u.test(character))
    || (rule.numbers && /\p{Nd}/u.test(character))
    || (rule.spaces && character === " ")
    || (rule.line_breaks && (character === "\r" || character === "\n"))
    || rule.symbols.includes(character)
  )))];

  const scopeBoxText = raw => [typeof raw === "string" ? raw : asString(raw?.component), asString(raw?.description)];

  // Twin of report_service.scope_box_refusals.
  const scopeBoxRefusals = (environment, channel, componentText, descriptionText, vocabulary) => {
    if (!vocabulary.component_channels.includes(channel)) return [];
    const components = componentText.split("\n");
    const descriptions = descriptionText.split("\n");
    const named = [];
    for (let line = 0; line < Math.max(components.length, descriptions.length); line += 1) {
      const component = strip(components[line] || "");
      if (component && !component.startsWith("#")) named.push({line, component, description:strip(descriptions[line] || "")});
    }
    const seen = new Set();
    const repeated = [];
    named.forEach(({component}) => {
      if (seen.has(component) && !repeated.includes(component)) repeated.push(component);
      seen.add(component);
    });
    const results = repeated.map(component => ({kind:"refusal", code:"duplicate_component", environment, app_type:channel, component}));
    const rule = vocabulary.character_rules.component_scope;
    named.forEach(({line, component, description}) => {
      [["component", component], ["description", description]].forEach(([box, text]) => {
        const characters = invalidCharacters(text, rule);
        if (characters.length) results.push({kind:"refusal", code:"invalid_characters", field:"component_scope", environment, app_type:channel, box, line, characters});
      });
    });
    return results;
  };

  // Twin of report_service.scope_text_refusals.
  const scopeRefusals = (report, vocabulary) => {
    const engagement = report?.engagement || {};
    const testedChannels = engagement.tested_channels || [];
    if (!testedChannels.length) return [{kind:"refusal", code:"no_app_type"}];
    const covered = vocabulary.channels.map(([channel]) => channel).filter(channel => testedChannels.includes(channel));
    return (engagement.tested_environments || []).flatMap(environment => covered.flatMap(channel =>
      scopeBoxRefusals(environment, channel, ...scopeBoxText(report?.scope_text?.[environment]?.[channel]), vocabulary)));
  };

  // Twin of report_service.scope_text_targets; paired by raw index before cleaning, as reconcile_targets does.
  const scopeTargets = (report, vocabulary) => {
    const engagement = report?.engagement || {};
    const testedChannels = engagement.tested_channels || [];
    const covered = vocabulary.channels.map(([channel]) => channel).filter(channel => testedChannels.includes(channel));
    const targets = [];
    (engagement.tested_environments || []).forEach(environment => {
      covered.forEach(channel => {
        const raw = report?.scope_text?.[environment]?.[channel];
        const [componentText, descriptionText] = scopeBoxText(raw);
        const components = componentText.split("\n");
        const descriptions = descriptionText.split("\n");
        const seen = new Set();
        for (let index = 0; index < Math.max(components.length, descriptions.length); index += 1) {
          const component = strip(components[index] || "");
          if (!component || component.startsWith("#") || seen.has(component)) continue;
          seen.add(component);
          targets.push({environment, app_type:channel, component, description:strip(descriptions[index] || "")});
        }
      });
    });
    return targets;
  };

  // Twin of report_service.USERNAME_PATTERN, which the vocabulary does not serve.
  const USERNAME_PATTERN = /^[A-Za-z0-9](?:[ A-Za-z0-9._@\\-]*[A-Za-z0-9])?$/;

  // What a save says about one username: null, invalid characters, or a bad first or last character.
  const usernameRefusal = (username, vocabulary) => {
    if (!username || username === "N/A" || USERNAME_PATTERN.test(username)) return null;
    const characters = invalidCharacters(username, vocabulary.character_rules.username);
    return characters.length ? {code:"invalid_characters", field:"username", characters} : {code:"invalid_username"};
  };

  // Twin of report_service.setup_field_refusals.
  const fieldRefusals = (engagement, vocabulary) => {
    const results = [];
    const refuse = (code, context = {}) => results.push({kind:"refusal", code, ...context});
    const check = (field, value, context = {}) => {
      if (typeof value !== "string" || !value) return;
      const characters = invalidCharacters(value, vocabulary.character_rules[field]);
      if (characters.length) refuse("invalid_characters", {field, ...context, characters});
    };
    ["app_name", "ci_number", "bsn_number", "app_owner", "tester"].forEach(field => check(field, engagement[field]));
    const environments = engagement.tested_environments || [];
    environments.forEach(environment => {
      const testWindow = engagement.test_windows?.[environment];
      if (!testWindow || typeof testWindow !== "object" || Array.isArray(testWindow)) return;
      const {start_date:start, end_date:end} = testWindow;
      if (typeof start === "string" && typeof end === "string" && start && end && start > end) refuse("test_dates_out_of_order", {environment});
      check("test_time", testWindow.test_time, {environment});
    });
    (engagement.test_accounts || []).forEach((account, index) => {
      if (!account || typeof account !== "object" || Array.isArray(account)) return;
      check("user_role", account.user_role, {account:index + 1});
      const username = usernameRefusal(typeof account.username === "string" ? account.username : "", vocabulary);
      if (username) refuse(username.code, {...username, account:index + 1});
    });
    check("limitations", engagement.limitations);
    // Stripped as the model's strip_label does before the save checks it.
    if (environments.includes("non_production")) check("non_production_label", typeof engagement.non_production_label === "string" ? strip(engagement.non_production_label) : engagement.non_production_label);
    return results;
  };

  const setupResults = (report, vocabulary) => {
    const engagement = report?.engagement || {};
    const results = [...scopeRefusals(report, vocabulary), ...fieldRefusals(engagement, vocabulary)];
    const issue = (code, context = {}) => results.push({kind:"issue", code, ...context});
    if (!strip(asString(engagement.app_name))) issue("missing_app_name");
    if (!engagement.segment) issue("missing_segment");
    if (!engagement.report_type) issue("missing_report_type");
    if (!strip(asString(engagement.tester))) issue("missing_tester");
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

  window.vrRules = {setupResults, scopeTargets, scopeRefusals, invalidCharacters, strip, usernameRefusal};
})();
